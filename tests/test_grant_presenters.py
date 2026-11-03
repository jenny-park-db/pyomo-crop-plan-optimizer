"""scripts/grant_presenters.py: the least-privilege grant plan for other presenters."""
import pytest

import grant_presenters as g
from demo_env import Target

T = Target(profile="p", target="dev", catalog="x_catalog", schema="crop_plan", warehouse_id="wh1",
           studio_app="crop-plan-studio", space_id="space1", experiment_id="exp1",
           jobs={"seed_data": 1, "solve_scenario": 2, "stress_test": 3, "precompute": 4})


def by_path(calls):
    return {c.path: c.body for c in calls}


def test_users_and_groups_get_the_right_acl_field():
    assert g.acl(["a@x.com", "Planners"], "CAN_USE") == {"access_control_list": [
        {"user_name": "a@x.com", "permission_level": "CAN_USE"},
        {"group_name": "Planners", "permission_level": "CAN_USE"}]}


def test_the_plan_covers_both_apps_genie_warehouse_jobs_and_experiment():
    calls = by_path(g.grant_plan(T, "agent-bricks-crop-plan-agent", ["a@x.com"]))
    level = lambda path: calls[path]["access_control_list"][0]["permission_level"]  # noqa: E731
    assert level("/api/2.0/permissions/apps/crop-plan-studio") == "CAN_USE"
    assert level("/api/2.0/permissions/apps/agent-bricks-crop-plan-agent") == "CAN_USE"
    assert level("/api/2.0/permissions/genie/space1") == "CAN_RUN"
    assert level("/api/2.0/permissions/warehouses/wh1") == "CAN_USE"
    assert level("/api/2.0/permissions/jobs/2") == "CAN_VIEW" and level("/api/2.0/permissions/jobs/3") == "CAN_VIEW"
    assert level("/api/2.0/permissions/experiments/exp1") == "CAN_READ"
    # Seed and precompute are the deployer's; presenters never see or run them.
    assert "/api/2.0/permissions/jobs/1" not in calls and "/api/2.0/permissions/jobs/4" not in calls
    assert all(c.method == "PATCH" for c in g.grant_plan(T, "agent-bricks-crop-plan-agent", ["a@x.com"]))


def test_uc_is_read_everything_but_write_only_what_studio_writes_as_the_user():
    calls = by_path(g.grant_plan(T, "agent-bricks-crop-plan-agent", ["a@x.com", "Planners"]))
    uc = {path.removeprefix("/api/2.1/unity-catalog/permissions/"): body["changes"]
          for path, body in calls.items() if "unity-catalog" in path}
    assert uc["catalog/x_catalog"] == [{"principal": "a@x.com", "add": ["USE_CATALOG"]},
                                       {"principal": "Planners", "add": ["USE_CATALOG"]}]
    assert uc["schema/x_catalog.crop_plan"][0]["add"] == ["USE_SCHEMA", "SELECT"]
    modify = {k.removeprefix("table/x_catalog.crop_plan.") for k, v in uc.items() if v[0]["add"] == ["MODIFY"]}
    assert modify == {"scenarios", "runs", "fields", "hybrids", "seed_supply", "yield_forecast", "planting_capacity",
                      "fixed_requests"}
    # Outputs are written by the jobs (as the deployer), never by the user.
    assert not modify & {"plan_assignments", "run_summary", "seed_utilization", "violations", "stress_test_summary"}


def test_no_presenters_or_no_genie_space_is_an_error_not_a_silent_no_op():
    with pytest.raises(SystemExit, match="No presenters"):
        g.grant_plan(T, "agent-bricks-crop-plan-agent", [])
    with pytest.raises(SystemExit, match="Genie space"):
        g.grant_plan(Target(**{**T.__dict__, "space_id": None}), "agent-bricks-crop-plan-agent", ["a@x.com"])


def test_the_user_written_tables_match_what_studio_writes():
    # app/server/studio/sql.ts writes the six INPUT_TABLES plus scenarios and runs, as the signed-in user.
    from pathlib import Path
    sql_ts = (Path(__file__).resolve().parents[1] / "app" / "server" / "studio" / "sql.ts").read_text()
    for table in g.USER_WRITTEN_TABLES:
        assert f"'{table}'" in sql_ts


def test_every_call_is_tried_and_failures_are_reported_with_the_uc_group_hint():
    calls = g.grant_plan(T, "agent-bricks-crop-plan-agent", ["Planners"])
    done = []

    def do(method, path, body):
        if "unity-catalog" in path:
            raise RuntimeError("Could not find principal with name Planners.")
        done.append(path)
    failures = g.apply(calls, do, out=lambda line: None)
    assert len(done) == 7 and len(failures) == 10  # 2 apps, Genie, warehouse, 2 jobs, experiment; 10 UC securables
    assert all("Could not find principal" in f for f in failures)
    assert "account-level group" in g.UC_HINT
