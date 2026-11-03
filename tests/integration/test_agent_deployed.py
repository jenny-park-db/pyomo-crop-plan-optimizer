"""Checks against the deployed agent and Crop Plan Studio (spec §10 demo steps 5-6, through the app's proxy).

Run after `uv run python scripts/deploy_agent.py --profile <profile>`:
    UV_HTTP_TIMEOUT=180 uv run pytest -m integration tests/integration/test_agent_deployed.py -v
Env: DATABRICKS_CONFIG_PROFILE (default pyomo-crop-plan), BUNDLE_TARGET (default dev),
CROP_PLAN_STUDIO_APP / CROP_PLAN_AGENT_APP to point at other deployments (default: the bundle's app and
agent-bricks-crop-plan-agent). Takes ~5 minutes (one agent what-if = one serverless solve, one Genie question).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

pytest.importorskip("databricks.sdk")
from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.sql import StatementParameterListItem, StatementState  # noqa: E402

pytestmark = pytest.mark.integration

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "pyomo-crop-plan")
TARGET = os.environ.get("BUNDLE_TARGET", "dev")
ROOT = Path(__file__).resolve().parents[2]
TURN_TIMEOUT_S = 600


@pytest.fixture(scope="module")
def env():
    out = subprocess.run(["databricks", "bundle", "summary", "-t", TARGET, "-o", "json", "--profile", PROFILE],
                         cwd=ROOT / "bundle", check=True, capture_output=True, text=True).stdout
    summary = json.loads(out)
    w = WorkspaceClient(profile=PROFILE)
    studio = w.apps.get(os.environ.get("CROP_PLAN_STUDIO_APP") or summary["resources"]["apps"]["crop_plan_studio"]["name"])
    agent = w.apps.get(os.environ.get("CROP_PLAN_AGENT_APP", "agent-bricks-crop-plan-agent"))
    return {"w": w, "studio_url": studio.url.rstrip("/"), "agent": agent, "agent_url": agent.url.rstrip("/"),
            "warehouse": summary["variables"]["warehouse_id"]["value"], "catalog": summary["variables"]["catalog"]["value"],
            "schema": summary["resources"]["schemas"]["crop_plan"]["name"], "me": w.current_user.me().user_name}


def sql(env, statement: str, **params) -> list[dict]:
    r = env["w"].statement_execution.execute_statement(
        statement=statement.replace("{fq}", f"`{env['catalog']}`.`{env['schema']}`"), warehouse_id=env["warehouse"],
        wait_timeout="50s", parameters=[StatementParameterListItem(name=k, value=str(p)) for k, p in params.items()])
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(3)
        r = env["w"].statement_execution.get_statement(r.statement_id)
    assert r.status.state == StatementState.SUCCEEDED, r.status.error
    cols = [c.name for c in r.manifest.schema.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]


def studio(env, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Call Crop Plan Studio as the test user (Apps accept the workspace OAuth token as a bearer token)."""
    headers = {"Content-Type": "application/json", **env["w"].config.authenticate()}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(env["studio_url"] + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def turn(env, message: str) -> dict:
    """One agent turn through Studio's proxy, polled like the Agent tab does."""
    status, started = studio(env, "POST", "/api/studio/agent/turns", {"session_id": str(uuid.uuid4()), "message": message})
    assert status == 200, started
    deadline = time.time() + TURN_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(3)
        status, state = studio(env, "GET", f"/api/studio/agent/turns/{started['id']}")
        assert status == 200, state
        if state["status"] in ("completed", "failed"):
            return state
    raise AssertionError(f"no answer in {TURN_TIMEOUT_S} s")


def tool_results(state: dict, name: str) -> list[dict]:
    return [json.loads(m["content"]) for m in state["messages"] if m["type"] == "tool" and m["name"] == name]


def test_agent_app_runs_as_the_user_with_sql_and_genie_scopes(env):
    agent = env["agent"]
    assert agent.compute_status.state.value == "ACTIVE"
    assert {"sql", "dashboards.genie"} <= set(agent.user_api_scopes or [])


def test_studio_points_its_agent_tab_at_the_agent(env):
    status, cfg = studio(env, "GET", "/api/studio/config")
    assert status == 200 and cfg["agentUrl"] == env["agent_url"]


def test_a_bad_turn_is_a_400_and_reaches_no_agent(env):
    status, out = studio(env, "POST", "/api/studio/agent/turns", {"session_id": "not-a-uuid", "message": "hi"})
    assert status == 400 and out["path"] == "session_id"


def test_demo_step_6_genie_answer_shows_sql_over_seed_utilization(env):
    state = turn(env, "Across today's scenarios, which hybrids always hit their supply limit?")
    assert state["status"] == "completed", state["error"]
    sqls = [a["query"]["query"] for r in tool_results(state, "genie_agent_ask") for a in r.get("attachments", [])
            if a.get("query", {}).get("query")]
    assert sqls and any("seed_utilization" in q for q in sqls), sqls


def test_demo_step_5_what_if_creates_an_agent_scenario_the_user_owns(env):
    state = turn(env, "What if Iowa loses half its W1 planting capacity to rain?")
    assert state["status"] == "completed", state["error"]
    [solve] = tool_results(state, "solve_scenario")
    assert solve["status"] == "done", solve
    assert solve["overrides"]["capacity_pct"] == {"IA": {"W1": 0.5}}
    assert solve["delta_vs_base"]["gross_margin"] < 0 and solve["base"]["scenario_id"] == "baseline-2027"
    [scenario] = sql(env, "SELECT source, created_by, parent_scenario_id FROM {fq}.scenarios WHERE scenario_id = :s",
                     s=solve["scenario_id"])
    assert scenario == {"source": "agent", "created_by": env["me"], "parent_scenario_id": "baseline-2027"}
    [run] = sql(env, "SELECT status, triggered_by FROM {fq}.runs WHERE run_id = :r", r=solve["run_id"])
    assert run == {"status": "done", "triggered_by": env["me"]}
