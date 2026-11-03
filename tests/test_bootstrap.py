"""scripts/bootstrap.py: catalog naming, step selection, the pre-deploy DDL, and the skip checks."""
import json

import pytest

import bootstrap
from cropplan_jobs.tables import TABLES


def test_catalog_is_derived_from_the_workspace_host():
    assert bootstrap.catalog_for_host("https://fevm-example-demo.cloud.databricks.com") == "example_demo_catalog"
    assert bootstrap.catalog_for_host("https://fevm-Crop-Demo-2.cloud.databricks.com/") == "crop_demo_2_catalog"
    assert bootstrap.catalog_for_host("https://my-ws.cloud.databricks.com") == "my_ws_catalog"
    with pytest.raises(SystemExit, match="--catalog"):
        bootstrap.catalog_for_host("https://fevm-.cloud.databricks.com")


def test_steps_run_in_order_from_a_start_or_alone():
    assert bootstrap.steps_to_run(None, None) == list(bootstrap.STEPS)
    assert bootstrap.steps_to_run("precompute", None) == ["precompute", "agent", "grants", "smoke"]
    assert bootstrap.steps_to_run(None, "grants") == ["grants"]
    with pytest.raises(SystemExit, match="Unknown step"):
        bootstrap.steps_to_run("teardown", None)


def test_tables_exist_before_the_first_deploy_so_genie_can_be_created():
    # The Genie space's create call fails with "Schema '<catalog>.<schema>.fields' does not exist".
    statements = bootstrap.table_statements("c", "s")
    assert statements[0].startswith("CREATE SCHEMA IF NOT EXISTS `c`.`s`")
    created = {s.split("`.`")[-1].split("`")[0] for s in statements[1:]}
    assert created == set(TABLES) and len(statements) == 1 + len(TABLES)
    assert all(s.startswith("CREATE TABLE IF NOT EXISTS `c`.`s`.") for s in statements[1:])
    genie_tables = {"fields", "hybrids", "plan_assignments", "run_summary", "runs", "scenarios", "seed_utilization",
                    "stress_test_summary", "violations"}
    assert genie_tables <= created


def test_seed_is_skipped_only_when_all_three_seeded_scenarios_are_complete():
    full = {"baseline-2027": 150, "grower-commitments-2027": 150, "revision-1-2027": 150}
    rows = {"baseline-2027", "grower-commitments-2027", "revision-1-2027"}
    assert bootstrap.is_seeded(full, rows)
    assert not bootstrap.is_seeded({**full, "revision-1-2027": 0}, rows)
    assert not bootstrap.is_seeded({"baseline-2027": 150}, rows)
    assert not bootstrap.is_seeded({}, set())


def test_seed_that_died_before_writing_a_scenario_row_is_not_finished():
    # write_scenario writes fields first and the scenarios row last: fields alone don't prove the seed finished.
    full = {"baseline-2027": 150, "grower-commitments-2027": 150, "revision-1-2027": 150}
    assert not bootstrap.is_seeded(full, {"baseline-2027", "grower-commitments-2027"})


def test_precompute_is_skipped_only_with_its_three_solves_and_both_n500_stress_tests():
    runs = {"baseline-2027": "done", "grower-commitments-2027": "infeasible", "revision-1-2027": "done"}
    stress = {"stress-baseline-2027-n500": (500, 500), "stress-revision-1-2027-n500": (500, 500)}
    assert bootstrap.is_precomputed(runs, stress)
    assert not bootstrap.is_precomputed({**runs, "baseline-2027": "failed"}, stress)
    assert not bootstrap.is_precomputed(runs, {"stress-baseline-2027-n500": (500, 500)})
    assert not bootstrap.is_precomputed(runs, {**stress, "stress-revision-1-2027-n500": (20, 20)})
    assert not bootstrap.is_precomputed({}, {})


def test_a_stress_test_with_unsolved_samples_is_not_a_finished_precompute():
    runs = {"baseline-2027": "done", "grower-commitments-2027": "infeasible", "revision-1-2027": "done"}
    stress = {"stress-baseline-2027-n500": (500, 500), "stress-revision-1-2027-n500": (500, 497)}
    assert not bootstrap.is_precomputed(runs, stress)


class FakeSql:
    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def rows(self, statement):
        self.seen.append(statement)
        return next(v for k, v in self.answers.items() if k in statement)


def precompute_bootstrap(monkeypatch, recompute, active_runs):
    from demo_env import Target
    t = Target(profile="p", target="dev", catalog="c", schema="s", warehouse_id="w", studio_app="crop-plan-studio",
               space_id="sp", experiment_id="e", jobs={"precompute": 42})
    b = bootstrap.Bootstrap("p", "dev", None, False, {}, recompute=recompute)
    done = {"`runs`": [{"scenario_id": "baseline-2027", "status": "done"},
                       {"scenario_id": "grower-commitments-2027", "status": "infeasible"},
                       {"scenario_id": "revision-1-2027", "status": "done"}],
            "`stress_test_summary`": [{"stress_id": i, "n": "500", "n_solved": "500"}
                                      for i in ("stress-baseline-2027-n500", "stress-revision-1-2027-n500")]}
    monkeypatch.setattr(b, "deployed", lambda: t)
    monkeypatch.setattr(b, "sql", lambda warehouse_id=None: FakeSql(done))
    cli_calls, jobs = [], []
    monkeypatch.setattr(b, "cli", lambda *a, capture=False: cli_calls.append(a) or json.dumps(active_runs))
    monkeypatch.setattr(b, "run_job", lambda key, *p: jobs.append(key))
    return b, cli_calls, jobs


def test_recompute_reruns_precompute_even_when_it_looks_finished(monkeypatch):
    b, _, jobs = precompute_bootstrap(monkeypatch, recompute=False, active_runs=[])
    b.precompute()
    assert jobs == []
    b, _, jobs = precompute_bootstrap(monkeypatch, recompute=True, active_runs=[])
    b.precompute()
    assert jobs == ["precompute"]


def test_a_precompute_run_still_active_stops_the_rerun_and_says_where_it_is(monkeypatch):
    active = [{"run_id": 7, "run_page_url": "https://h/jobs/42/runs/7", "state": {"life_cycle_state": "RUNNING"}}]
    b, cli_calls, jobs = precompute_bootstrap(monkeypatch, recompute=True, active_runs=active)
    with pytest.raises(SystemExit, match="still active.*https://h/jobs/42/runs/7"):
        b.precompute()
    assert jobs == []
    assert any("--active-only" in call and "42" in call for call in cli_calls)


def test_the_schema_is_bound_only_when_the_bundle_does_not_manage_it_yet():
    assert not bootstrap.schema_bound({"resources": {"jobs": {}}})
    assert not bootstrap.schema_bound({"resources": {"schemas": {"crop_plan": {"name": "crop_plan"}}}})
    assert bootstrap.schema_bound({"resources": {"schemas": {"crop_plan": {"id": "c.crop_plan"}}}})


def test_a_catalog_the_user_cannot_see_stops_preflight_and_names_the_fix(tmp_path, monkeypatch):
    import subprocess
    b = bootstrap.Bootstrap("p", "dev", None, False, {})
    b.override = tmp_path / "variable-overrides.json"

    def cli(*args, capture=False):
        if args[0] == "current-user":
            return '{"userName": "me@x.com"}'
        if args[0] == "auth":
            return '{"details": {"host": "https://fevm-example.cloud.databricks.com"}}'
        raise subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(b, "cli", cli)
    with pytest.raises(SystemExit, match="example_catalog.*--catalog"):
        b.preflight()
    assert not b.override.exists()


def test_preflight_records_the_catalog_for_every_later_bundle_command(tmp_path, monkeypatch):
    import json
    b = bootstrap.Bootstrap("p", "dev", None, False, {"CROP_PLAN_CATALOG": "chosen_catalog"})
    b.override = tmp_path / "variable-overrides.json"
    b.override.write_text('{"agent_url": "https://a.aws.databricksapps.com"}')
    answers = {"current-user": '{"userName": "me@x.com"}', "auth": '{"details": {"host": "https://h"}}', "catalogs": "{}"}
    monkeypatch.setattr(b, "cli", lambda *args, capture=False: answers[args[0]])
    b.preflight()
    assert json.loads(b.override.read_text()) == {"agent_url": "https://a.aws.databricksapps.com", "catalog": "chosen_catalog"}


def test_studio_is_deployed_again_unless_its_last_deployment_succeeded_and_it_runs():
    running = {"app_status": {"state": "RUNNING"}, "active_deployment": {"status": {"state": "SUCCEEDED"}}}
    assert not bootstrap.app_needs_deploy(running)
    # A first deploy that failed after creating the app: no deployment, and `bundle deploy` says "unchanged".
    assert bootstrap.app_needs_deploy({"app_status": {"state": "UNAVAILABLE"}, "compute_status": {"state": "ACTIVE"}})
    assert bootstrap.app_needs_deploy({**running, "active_deployment": {"status": {"state": "FAILED"}}})
    assert bootstrap.app_needs_deploy({**running, "app_status": {"state": "CRASHED"}})


def seed_bootstrap(monkeypatch, scenario_ids, reseed=False):
    from demo_env import Target
    t = Target(profile="p", target="dev", catalog="c", schema="s", warehouse_id="w", studio_app="crop-plan-studio",
               space_id="sp", experiment_id="e", jobs={"seed_data": 41})
    b = bootstrap.Bootstrap("p", "dev", None, reseed, {})
    fake = FakeSql({"`fields`": [{"scenario_id": s, "n": "150"} for s in bootstrap.SEEDED],
                    "`scenarios`": [{"scenario_id": s} for s in scenario_ids]})
    monkeypatch.setattr(b, "deployed", lambda: t)
    monkeypatch.setattr(b, "sql", lambda warehouse_id=None: fake)
    jobs = []
    monkeypatch.setattr(b, "run_job", lambda key, *p: jobs.append(key))
    return b, fake, jobs


def test_seed_runs_when_a_seeded_scenario_row_is_missing_even_if_its_inputs_are_there(monkeypatch):
    b, fake, jobs = seed_bootstrap(monkeypatch, list(bootstrap.SEEDED)[:2])
    b.seed()
    assert jobs == ["seed_data"]
    assert any("`scenarios`" in st and "source = 'seed'" in st for st in fake.seen)


def test_seed_is_skipped_when_every_seeded_scenario_is_complete_unless_reseed(monkeypatch):
    b, _, jobs = seed_bootstrap(monkeypatch, list(bootstrap.SEEDED))
    b.seed()
    assert jobs == []
    b, _, jobs = seed_bootstrap(monkeypatch, list(bootstrap.SEEDED), reseed=True)
    b.seed()
    assert jobs == ["seed_data"]
