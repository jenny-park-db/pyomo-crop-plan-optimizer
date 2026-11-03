"""Checks against the deployed dev target: Genie space content, and the app's write paths.

Run after `databricks bundle deploy` and `databricks bundle run seed_data` (from bundle/):
    UV_HTTP_TIMEOUT=180 uv run pytest -m integration tests/integration/test_app_deployed.py -v
Env: DATABRICKS_CONFIG_PROFILE (default pyomo-crop-plan), BUNDLE_TARGET (default dev).
Takes ~5 minutes (one serverless solve, one failing job run, a few Genie questions).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("databricks.sdk")
yaml = pytest.importorskip("yaml")
from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementParameterListItem, StatementState  # noqa: E402

pytestmark = pytest.mark.integration

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "pyomo-crop-plan")
TARGET = os.environ.get("BUNDLE_TARGET", "dev")
ROOT = Path(__file__).resolve().parents[2]
STAMP = time.strftime("%Y%m%d%H%M%S")
FINAL = {"done", "invalid", "infeasible", "failed"}


@pytest.fixture(scope="module")
def env():
    out = subprocess.run(["databricks", "bundle", "summary", "-t", TARGET, "-o", "json", "--profile", PROFILE],
                         cwd=ROOT / "bundle", check=True, capture_output=True, text=True).stdout
    summary = json.loads(out)
    w = WorkspaceClient(profile=PROFILE)
    v = summary["variables"]
    app = w.apps.get(summary["resources"]["apps"]["crop_plan_studio"]["name"])
    return {"w": w, "warehouse": v["warehouse_id"]["value"], "catalog": v["catalog"]["value"],
            "schema": summary["resources"]["schemas"]["crop_plan"]["name"],
            "space_id": summary["resources"]["genie_spaces"]["crop_plan_results"]["id"],
            "jobs": {k: int(j["id"]) for k, j in summary["resources"]["jobs"].items()},
            "app_url": app.url.rstrip("/"), "me": w.current_user.me().user_name}


def sql(env, statement: str, **params) -> list[dict]:
    w = env["w"]
    r = w.statement_execution.execute_statement(
        statement=statement.replace("{fq}", f"`{env['catalog']}`.`{env['schema']}`"), warehouse_id=env["warehouse"],
        wait_timeout="50s", parameters=[StatementParameterListItem(name=k, value=str(p)) for k, p in params.items()])
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
    assert r.status.state == StatementState.SUCCEEDED, r.status.error
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def app_call(env, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Call the deployed app as the test user (Apps accept the workspace OAuth token as a bearer token)."""
    headers = {"Content-Type": "application/json", **env["w"].config.authenticate()}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(env["app_url"] + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _examples() -> list[dict]:
    space = yaml.safe_load((ROOT / "genie" / "crop_plan_results.yml").read_text())
    return space["resources"]["genie_spaces"]["crop_plan_results"]["serialized_space"]["instructions"]["example_question_sqls"]


@pytest.mark.parametrize("example", _examples(), ids=lambda e: e["question"][0][:40])
def test_every_genie_example_query_runs(env, example):
    statement = "".join(example["sql"]).replace("${var.catalog}", env["catalog"]).replace("${var.schema}", env["schema"])
    sql(env, statement)


def test_genie_answers_demo_step_6_with_sql_over_seed_utilization(env):
    msg = env["w"].genie.start_conversation_and_wait(
        env["space_id"], "Across today's scenarios, which hybrids always hit their supply limit?")
    queries = [a.query.query for a in (msg.attachments or []) if a.query and a.query.query]
    assert queries and "seed_utilization" in queries[0], msg


def test_app_reports_its_config_and_the_signed_in_user(env):
    status, cfg = app_call(env, "GET", "/api/studio/config")
    assert status == 200 and cfg["schema"] == env["schema"] and cfg["solveJobId"] == env["jobs"]["solve_scenario"]
    status, me = app_call(env, "GET", "/api/studio/whoami")
    assert status == 200 and me["email"] == env["me"]


def test_submit_dedupes_and_the_job_reuses_the_apps_row(env):
    run_id = f"it-app-{STAMP}"
    body = {"mode": "resolve", "source_scenario_id": "baseline-2027", "run_id": run_id}
    s1, first = app_call(env, "POST", "/api/studio/runs", body)
    s2, second = app_call(env, "POST", "/api/studio/runs", body)
    assert (s1, s2) == (200, 200) and first["deduped"] is False and second["deduped"] is True
    assert second["job_run_id"] == first["job_run_id"]
    deadline = time.time() + 600
    while True:
        row = sql(env, "SELECT status, triggered_by, job_run_id, submitted_at FROM {fq}.runs WHERE run_id = :r", r=run_id)
        assert len(row) == 1
        if row[0]["status"] in FINAL or time.time() > deadline:
            break
        time.sleep(15)
    assert row[0]["status"] == "done" and row[0]["triggered_by"] == env["me"]
    assert row[0]["job_run_id"] == first["job_run_id"] and row[0]["submitted_at"]


def test_a_job_that_dies_before_opening_its_row_is_reconciled_to_failed(env):
    """solve_scenario rejects an empty scenario_id before it opens the row, like a crash at import time."""
    run_id = f"it-app-dead-{STAMP}"
    w = env["w"]
    waiter = w.jobs.run_now(job_id=env["jobs"]["solve_scenario"],
                            job_parameters={"scenario_id": "", "run_id": run_id, "triggered_by": env["me"]})
    job_run_id = waiter.run_id
    sql(env, "INSERT INTO {fq}.runs (run_id, scenario_id, triggered_by, status, submitted_at, job_run_id) "
             "VALUES (:r, 'baseline-2027', :who, 'queued', current_timestamp(), :j)", r=run_id, who=env["me"], j=job_run_id)
    try:
        waiter.result()
    except Exception:  # noqa: BLE001 — the job is supposed to fail
        pass
    time.sleep(4)  # outside the sync throttle window
    status, out = app_call(env, "POST", "/api/studio/runs/sync", {})
    assert status == 200, out
    row = sql(env, "SELECT status, error FROM {fq}.runs WHERE run_id = :r", r=run_id)[0]
    assert row["status"] == "failed" and "scenario_id" in row["error"], row


def test_a_crafted_submit_cannot_choose_triggered_by_or_skip_validation(env):
    status, out = app_call(env, "POST", "/api/studio/runs", {
        "mode": "new", "source_scenario_id": "baseline-2027", "run_id": f"it-app-bad-{STAMP}", "name": "x",
        "overrides": {"diversity_cap": "0.4"}, "triggered_by": "someone-else@example.com"})
    assert status == 400 and out["path"] == "diversity_cap"
