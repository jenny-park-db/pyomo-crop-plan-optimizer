"""scripts/smoke_test.py: each spec §10 check passes on the bootstrapped numbers and fails on a broken rebuild."""
import json

import smoke_test as s

BASE = {"scenario_id": "baseline-2027", "status": "done", "mlflow_run_id": "abc", "gross_margin": "1.8811018E7",
        "unplanted_fields": "4", "run_id": "r1"}
REV = {"scenario_id": "revision-1-2027", "status": "done", "mlflow_run_id": "def", "gross_margin": "1.8839272E7",
       "unplanted_fields": "4", "run_id": "r2"}
STRESS = [{"stress_id": "stress-baseline-2027-n500", "n": "500", "n_solved": "500", "p10_gross_margin": "1.76893499E7"},
          {"stress_id": "stress-revision-1-2027-n500", "n": "500", "n_solved": "500", "p10_gross_margin": "1.7806807975E7"}]


def tool(name, payload):
    return {"type": "tool", "name": name, "content": json.dumps(payload)}


def test_seeded_needs_150_fields_in_each_seeded_scenario():
    assert s.check_seeded({"baseline-2027": 150, "grower-commitments-2027": 150, "revision-1-2027": 150}).ok
    assert not s.check_seeded({"baseline-2027": 150, "grower-commitments-2027": 150}).ok


def test_baseline_must_reproduce_its_margin_unplanted_fields_and_mlflow_run():
    assert s.check_baseline(BASE).ok
    assert not s.check_baseline({**BASE, "gross_margin": "1.88E7"}).ok  # a different plan after the rebuild
    assert not s.check_baseline({**BASE, "unplanted_fields": "3"}).ok
    assert not s.check_baseline({**BASE, "mlflow_run_id": None}).ok
    assert not s.check_baseline({**BASE, "status": "failed", "gross_margin": None, "unplanted_fields": None}).ok
    assert not s.check_baseline(None).ok


def test_revision_must_be_done_and_beat_the_baseline():
    assert s.check_revision(REV).ok
    assert not s.check_revision({**REV, "gross_margin": "1.8E7"}).ok
    assert not s.check_revision(None).ok


def test_commitments_must_be_infeasible_on_ia_w1_capacity():
    row = {"status": "infeasible", "run_id": "r3"}
    binding = [{"rule": "capacity", "entity": "IA/W1", "detail": "Planting capacity IA/W1 short by 290 acres"}]
    assert s.check_infeasible(row, binding).ok
    assert "290 acres" in s.check_infeasible(row, binding).detail
    assert not s.check_infeasible(row, [{"rule": "supply", "entity": "H-112", "detail": "x"}]).ok
    assert not s.check_infeasible({"status": "done", "run_id": "r3"}, binding).ok


def test_stored_stress_tests_need_both_n500_runs_and_revision_ahead_on_p10():
    assert s.check_stress(STRESS).ok
    assert not s.check_stress(STRESS[:1]).ok
    swapped = [{**STRESS[0], "p10_gross_margin": "1.79E7"}, STRESS[1]]
    assert not s.check_stress(swapped).ok
    assert not s.check_stress([STRESS[0], {**STRESS[1], "n_solved": "499"}]).ok


def test_genie_turn_needs_sql_over_seed_utilization():
    ok = {"status": "completed", "messages": [
        tool("genie_agent_ask", {"attachments": [{"query": {"query": "SELECT hybrid_id FROM x.seed_utilization"}}]})]}
    assert s.check_genie_turn(ok).ok
    assert not s.check_genie_turn({"status": "completed", "messages": [tool("genie_agent_ask", {"attachments": []})]}).ok
    assert not s.check_genie_turn({"status": "failed", "error": "403"}).ok


def test_what_if_turn_needs_a_done_solve_with_the_iowa_override_and_returns_its_scenario():
    solve = {"status": "done", "scenario_id": "iowa-w1-x", "overrides": {"capacity_pct": {"IA": {"W1": 0.5}}},
             "delta_vs_base": {"gross_margin": -250000.0}}
    check, scenario = s.check_what_if_turn({"status": "completed", "messages": [tool("solve_scenario", solve)]})
    assert check.ok and scenario == "iowa-w1-x"
    wrong = {**solve, "overrides": {"capacity_pct": {"IA": {"W1": 0.75}}}}
    assert not s.check_what_if_turn({"status": "completed", "messages": [tool("solve_scenario", wrong)]})[0].ok
    check, scenario = s.check_what_if_turn({"status": "completed", "messages": []})
    assert not check.ok and scenario is None


def test_report_lists_every_check_and_passes_only_when_all_do():
    lines = []
    assert s.report([s.Check("a", True, "x"), s.Check("b", True, "y")], lines.append)
    assert not s.report([s.Check("a", True, "x"), s.Check("b", False, "y")], lines.append)
    assert lines[-1] == "Smoke test: 1/2 checks passed." and "FAIL  b: y" in lines[-2]


class FakeStudio:
    def __init__(self, solve):
        self.asked, self.solve = [], solve

    def turn(self, message):
        self.asked.append(message)
        if message == s.GENIE_QUESTION:
            return {"status": "completed", "messages": [tool("genie_agent_ask", {"attachments": [
                {"query": {"query": "SELECT * FROM seed_utilization"}}]})]}
        return {"status": "completed", "messages": [tool("solve_scenario", self.solve)]}


def test_agent_checks_ask_genie_before_the_what_if_and_delete_the_what_if_scenario():
    solve = {"status": "done", "scenario_id": "iowa-w1-x", "overrides": {"capacity_pct": {"IA": {"W1": 0.5}}},
             "delta_vs_base": {"gross_margin": -1.0}}
    studio, deleted = FakeStudio(solve), []
    checks = s.agent_checks(studio, deleted.append)
    assert [c.ok for c in checks] == [True, True]
    assert studio.asked == [s.GENIE_QUESTION, s.WHAT_IF] and deleted == ["iowa-w1-x"]
    kept = []
    s.agent_checks(FakeStudio(solve), kept.append, keep_scenario=True)
    assert kept == []
