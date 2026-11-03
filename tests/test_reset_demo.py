"""scripts/reset_demo.py: what a reset deletes, and what it never touches."""
import re

import pytest

import reset_demo as r
from demo_env import Target

T = Target(profile="p", target="dev", catalog="c", schema="s", warehouse_id="w", studio_app="crop-plan-studio",
           space_id="sp", experiment_id="e", jobs={})


def target_table(statement: str) -> str:
    return re.match(r"DELETE FROM `c`\.`s`\.`(\w+)`", statement).group(1)


def test_deleting_a_scenario_clears_every_table_keyed_by_scenario_id_and_the_scenario_row_last():
    statements = r.delete_scenario_statements(T, ["iowa-w1-abc", "revision-a-3uwglv"])
    assert statements[-1] == "DELETE FROM `c`.`s`.`scenarios` WHERE scenario_id IN ('iowa-w1-abc', 'revision-a-3uwglv')"
    tables = {target_table(st) for st in statements}
    assert {"fields", "fixed_requests", "runs", "plan_assignments", "run_summary", "seed_utilization", "violations",
            "stress_test_results", "stress_test_summary", "scenarios"} <= tables
    assert r.delete_scenario_statements(T, []) == []


def test_seeded_scenarios_are_never_deleted():
    with pytest.raises(ValueError, match="seeded"):
        r.delete_scenario_statements(T, ["iowa-w1-abc", "baseline-2027"])


def test_extra_runs_of_seeded_scenarios_go_but_precompute_runs_stay():
    statements = r.extra_run_statements(T)
    assert statements[-1].startswith("DELETE FROM `c`.`s`.`runs` WHERE run_id IN (SELECT run_id")
    assert all("<> 'precompute'" in st and "'baseline-2027'" in st for st in statements)
    assert [target_table(st) for st in statements[:-1]] == r.RUN_OUTPUTS


def test_runs_whose_scenario_no_longer_exists_go_too():
    # A failed integration-test run (scenario 'it-no-such-scenario') showed on the Runs page during the dry run.
    for st in r.extra_run_statements(T):
        assert "scenario_id NOT IN (SELECT scenario_id FROM `c`.`s`.`scenarios`)" in st
    assert r.extra_run_ids_sql(T) in r.extra_run_statements(T)[-1]


def test_only_the_two_precomputed_stress_tests_are_kept():
    for st in r.extra_stress_statements(T):
        assert st.endswith("WHERE stress_id NOT IN ('stress-baseline-2027-n500', 'stress-revision-1-2027-n500')")


class RecordingSql:
    """Answers reset_demo.main's preview queries and records every statement it is given."""
    def __init__(self, profile=None, warehouse_id=None):
        self.seen = []

    def rows(self, statement):
        self.seen.append(statement)
        if statement.startswith("DELETE"):
            return []
        if statement.startswith("SELECT scenario_id") and "source IN ('app', 'agent')" in statement:
            return [{"scenario_id": "iowa-w1-abc"}]
        if statement.startswith("SELECT count(*) AS n FROM ("):
            return [{"n": "2"}]
        if statement.startswith("SELECT stress_id"):
            return [{"stress_id": "st-live-1"}]
        if "status IN ('queued'" in statement:
            return [{"n": "0"}]
        raise AssertionError(f"unexpected statement: {statement}")


@pytest.fixture
def recording(monkeypatch):
    made = []

    def factory(profile, warehouse_id):
        made.append(RecordingSql())
        return made[-1]

    monkeypatch.setattr(r, "load_target", lambda profile, target: T)
    monkeypatch.setattr(r, "Sql", factory)
    return made


def test_reset_without_yes_only_previews_and_deletes_nothing(recording, capsys):
    r.main(["--profile", "p"])
    assert not any(st.startswith("DELETE") for st in recording[0].seen)
    assert "Dry run" in capsys.readouterr().out


def test_reset_with_yes_issues_the_deletes(recording):
    r.main(["--profile", "p", "--yes"])
    deletes = [st for st in recording[0].seen if st.startswith("DELETE")]
    assert deletes
    assert any("iowa-w1-abc" in st for st in deletes)
