"""Spec §9 integration test against a deployed bundle target (default: dev).

Run after `databricks bundle deploy` (from bundle/):
    UV_HTTP_TIMEOUT=180 uv run pytest -m integration tests/integration -v
Env: DATABRICKS_CONFIG_PROFILE (default pyomo-crop-plan), BUNDLE_TARGET (default dev),
     DATABRICKS_WAREHOUSE_ID (default: first warehouse in the workspace).
Takes ~10 minutes: serverless cold starts plus one AI Runtime task.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("databricks.sdk")
from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementParameterListItem, StatementState  # noqa: E402

pytestmark = pytest.mark.integration

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "pyomo-crop-plan")
TARGET = os.environ.get("BUNDLE_TARGET", "dev")
BUNDLE_DIR = Path(__file__).resolve().parents[2] / "bundle"
STAMP = time.strftime("%Y%m%d%H%M%S")
WHO = "integration-test@example.com"
STATE: dict = {}


@pytest.fixture(scope="module")
def env():
    out = subprocess.run(["databricks", "bundle", "summary", "-t", TARGET, "-o", "json", "--profile", PROFILE],
                         cwd=BUNDLE_DIR, check=True, capture_output=True, text=True).stdout
    summary = json.loads(out)
    w = WorkspaceClient(profile=PROFILE)
    warehouse = os.environ.get("DATABRICKS_WAREHOUSE_ID") or next(iter(w.warehouses.list())).id
    variables = summary["variables"]
    return {"w": w, "warehouse": warehouse,
            "jobs": {k: int(v["id"]) for k, v in summary["resources"]["jobs"].items()},
            "experiment_id": summary["resources"]["experiments"]["scenarios"]["id"],
            "fq": f"`{variables['catalog']['value']}`.`{variables['schema']['value']}`"}


def sql(env, statement: str, **params) -> list[dict]:
    w = env["w"]
    r = w.statement_execution.execute_statement(
        statement=statement.replace("{fq}", env["fq"]), warehouse_id=env["warehouse"], wait_timeout="50s",
        parameters=[StatementParameterListItem(name=k, value=str(v)) for k, v in params.items()])
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        r = w.statement_execution.get_statement(r.statement_id)
    assert r.status.state == StatementState.SUCCEEDED, r.status.error
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def run_job(env, job: str, **params):
    """Run a bundle job and wait. Returns the finished run (raises if it failed)."""
    waiter = env["w"].jobs.run_now(job_id=env["jobs"][job], job_parameters={k: str(v) for k, v in params.items()})
    return waiter.result(timeout=timedelta(minutes=30))


def run_row(env, run_id: str) -> dict:
    rows = sql(env, "SELECT * FROM {fq}.runs WHERE run_id = :r", r=run_id)
    assert len(rows) == 1, rows
    return rows[0]


def test_seed_writes_three_scenarios(env):
    run_job(env, "seed_data", triggered_by=WHO)
    rows = sql(env, "SELECT s.scenario_id, s.source, count(f.field_id) AS n FROM {fq}.scenarios s "
                    "JOIN {fq}.fields f USING (scenario_id) GROUP BY ALL ORDER BY 1")
    assert [(r["scenario_id"], r["source"], r["n"]) for r in rows] == [
        ("baseline-2027", "seed", "150"), ("grower-commitments-2027", "seed", "150"), ("revision-1-2027", "seed", "150")]


def test_baseline_is_done_with_about_four_unplanted_ne_fields(env):
    run_id = STATE["base"] = f"it-{STAMP}-base"
    job = run_job(env, "solve_scenario", scenario_id="baseline-2027", run_id=run_id, triggered_by=WHO)
    row = run_row(env, run_id)
    assert (row["status"], row["termination"], row["triggered_by"]) == ("done", "optimal", WHO)
    assert row["job_run_id"] == str(job.run_id) and row["mlflow_run_id"]
    unplanted = sql(env, "SELECT p.field_id, f.region FROM {fq}.plan_assignments p JOIN {fq}.fields f "
                         "ON f.scenario_id = p.scenario_id AND f.field_id = p.field_id "
                         "WHERE p.run_id = :r AND p.hybrid_id IS NULL", r=run_id)
    assert 3 <= len(unplanted) <= 5 and {u["region"] for u in unplanted} == {"NE"}
    summary = sql(env, "SELECT * FROM {fq}.run_summary WHERE run_id = :r", r=run_id)[0]
    assert int(summary["unplanted_fields"]) == len(unplanted) and summary["violations_count"] == "0"
    ml = env["w"].experiments.get_run(row["mlflow_run_id"]).run
    assert ml.info.experiment_id == env["experiment_id"]
    tags = {t.key: t.value for t in ml.data.tags}
    assert (tags["scenario_id"], tags["run_id"], tags["job_run_id"]) == ("baseline-2027", run_id, str(job.run_id))


def test_grower_commitments_is_infeasible_at_ia_w1(env):
    run_id = f"it-{STAMP}-commit"
    run_job(env, "solve_scenario", scenario_id="grower-commitments-2027", run_id=run_id, triggered_by=WHO)
    row = run_row(env, run_id)
    assert row["status"] == "infeasible"
    assert row["infeasibility_reason"].startswith("Infeasible: Planting capacity IA/W1 short by")
    v = sql(env, "SELECT rule, entity, severity FROM {fq}.violations WHERE run_id = :r", r=run_id)
    assert {"rule": "capacity", "entity": "IA/W1", "severity": "binding"} in v
    assert any(x["rule"] == "capacity_below_fixed" and x["severity"] == "warning" for x in v)


def test_unknown_scenario_fails_once_and_marks_the_run_failed(env):
    run_id = f"it-{STAMP}-missing"
    waiter = env["w"].jobs.run_now(job_id=env["jobs"]["solve_scenario"], job_parameters={
        "scenario_id": "it-no-such-scenario", "run_id": run_id, "triggered_by": WHO})
    with pytest.raises(Exception):
        waiter.result(timeout=timedelta(minutes=30))
    row = run_row(env, run_id)
    assert row["status"] == "failed" and row["error"].startswith("ScenarioNotFound")
    attempts = [t for t in env["w"].jobs.get_run(waiter.run_id).tasks if t.task_key == "solve"]
    assert len(attempts) == 1  # no silent serverless auto-retry


def test_stress_test_n20(env):
    stress_id = f"it-{STAMP}-stress"
    run_job(env, "stress_test", scenario_id="baseline-2027", n=20, seed=2027, stress_id=stress_id, triggered_by=WHO)
    s = sql(env, "SELECT * FROM {fq}.stress_test_summary WHERE stress_id = :s", s=stress_id)
    assert len(s) == 1 and s[0]["n"] == "20" and s[0]["triggered_by"] == WHO
    counted = sum(int(s[0][k]) for k in ("n_solved", "n_invalid", "n_infeasible", "n_failed"))
    assert counted == 20 and int(s[0]["n_solved"]) >= 15 and s[0]["p50_gross_margin"] is not None
    n = sql(env, "SELECT count(*) AS n FROM {fq}.stress_test_results WHERE stress_id = :s", s=stress_id)[0]["n"]
    assert n == "20"
    ml = env["w"].experiments.get_run(s[0]["mlflow_run_id"]).run
    assert ml.info.experiment_id == env["experiment_id"]
    assert {t.key: t.value for t in ml.data.tags}["stress_id"] == stress_id


def test_resolving_an_older_scenario_reproduces_the_objective(env):
    first = run_row(env, STATE["base"])
    run_id = f"it-{STAMP}-base-again"
    run_job(env, "solve_scenario", scenario_id="baseline-2027", run_id=run_id, triggered_by=WHO)
    again = run_row(env, run_id)
    assert first["termination"] == again["termination"] == "optimal"
    assert abs(float(first["objective"]) - float(again["objective"])) <= 1e-6
