from dataclasses import replace

import pytest

from cropplan.model import build_model, extract_assignments
from cropplan.overrides import Overrides
from cropplan.solve import solve
from conftest import tiny_inputs

NO_DIVERSITY = Overrides(diversity_cap=1.0, corn_price_per_bu=1.0)


def test_known_optimum(tiny):
    # W1 holds 3 fields; HB covers 2 fields. Best: 2xHB + 3xHA with W1 used by the best 3.
    # Both {HB-W1, HB-W1, HA-W1, HA-W2, HA-W2} and {HB-W2, HB-W2, HA-W1 x3} score 52 bu -> 5200.
    built = build_model(tiny, NO_DIVERSITY)
    outcome = solve(built, NO_DIVERSITY)
    assert outcome.status == "done"
    assert outcome.objective == pytest.approx(5200.0)
    a = extract_assignments(built, tiny)
    assert a["hybrid_id"].value_counts().to_dict() == {"HA": 3, "HB": 2}
    assert (a["window"] == "W1").sum() == 3
    assert a["exp_margin"].sum() == pytest.approx(5200.0)


def test_unplanted_when_supply_runs_out(tiny):
    o = replace(NO_DIVERSITY, supply_pct={"HA": 0.1})  # HA: 100 units -> 1 field; HB: 2 fields
    built = build_model(tiny, o)
    assert solve(built, o).status == "done"
    a = extract_assignments(built, tiny)
    assert a["hybrid_id"].isna().sum() == 2
    assert a.loc[a["hybrid_id"].isna(), "exp_margin"].eq(0).all()


def test_diversity_cap_spreads_hybrids(tiny):
    o = replace(NO_DIVERSITY, diversity_cap=0.34)  # G1 has 300 acres -> at most 1 field per hybrid
    built = build_model(tiny, o)
    assert solve(built, o).status == "done"
    a = extract_assignments(built, tiny).merge(tiny.fields[["field_id", "grower_id"]])
    g1 = a[a["grower_id"] == "G1"]
    assert g1["hybrid_id"].dropna().value_counts().max() <= 1
    assert g1["hybrid_id"].isna().sum() == 1  # only 2 hybrids exist, so one G1 field stays unplanted


def test_fixed_request_with_window_is_honored(tiny):
    inputs = tiny_inputs(fixed=[("F5", "HA", "W4")])
    built = build_model(inputs, NO_DIVERSITY)
    assert solve(built, NO_DIVERSITY).status == "done"
    a = extract_assignments(built, inputs).set_index("field_id")
    assert (a.at["F5", "hybrid_id"], a.at["F5", "window"], a.at["F5", "is_fixed"]) == ("HA", "W4", True)


def test_fixed_request_without_window_picks_any_window(tiny):
    inputs = tiny_inputs(fixed=[("F5", "HA", None)])
    built = build_model(inputs, NO_DIVERSITY)
    assert solve(built, NO_DIVERSITY).status == "done"
    assert extract_assignments(built, inputs).set_index("field_id").at["F5", "hybrid_id"] == "HA"


def test_fixed_requests_ignored_when_disabled(tiny):
    inputs = tiny_inputs(fixed=[("F5", "HA", "W4")])
    o = replace(NO_DIVERSITY, fixed_requests_enabled=False)
    built = build_model(inputs, o)
    outcome = solve(built, o)
    assert outcome.objective == pytest.approx(5200.0)
    assert not extract_assignments(built, inputs)["is_fixed"].any()


def test_infeasible_when_fixed_requests_exceed_capacity(tiny):
    inputs = tiny_inputs(fixed=[(f"F{i}", "HA", "W1") for i in range(1, 5)])  # 400 acres > 300 in W1
    assert solve(build_model(inputs, NO_DIVERSITY), NO_DIVERSITY).status == "infeasible"


def test_unavailable_solver_fails_cleanly(tiny, monkeypatch):
    from pyomo.contrib.appsi.solvers import Gurobi
    monkeypatch.setattr(Gurobi, "available", lambda self: False)
    o = replace(NO_DIVERSITY, solver="gurobi")
    outcome = solve(build_model(tiny, o), o)
    assert outcome.status == "failed"
    assert "not available" in outcome.error


def test_same_settings_give_identical_objective():
    from cropplan.generate import seeded_scenarios
    inputs, o = seeded_scenarios()["baseline-2027"]
    o = replace(o, time_limit_s=600)
    first = solve(build_model(inputs, o), o)
    second = solve(build_model(inputs, o), o)
    assert first.termination == second.termination == "optimal"
    assert first.objective == pytest.approx(second.objective, abs=1e-6)


def _fake_results(termination, objective=None):
    from types import SimpleNamespace
    return SimpleNamespace(termination_condition=termination, best_feasible_objective=objective,
                           best_objective_bound=None, solution_loader=SimpleNamespace(load_vars=lambda: None))


def test_time_limit_without_solution_fails_with_readable_error(tiny, monkeypatch):
    from pyomo.contrib.appsi.base import TerminationCondition as TC
    from pyomo.contrib.appsi.solvers import Highs
    monkeypatch.setattr(Highs, "solve", lambda self, model: _fake_results(TC.maxTimeLimit))
    outcome = solve(build_model(tiny, NO_DIVERSITY), replace(NO_DIVERSITY, time_limit_s=7))
    assert outcome.status == "failed"
    assert outcome.error == "no feasible solution within 7s time limit"


def test_solver_error_reports_termination(tiny, monkeypatch):
    from pyomo.contrib.appsi.base import TerminationCondition as TC
    from pyomo.contrib.appsi.solvers import Highs
    monkeypatch.setattr(Highs, "solve", lambda self, model: _fake_results(TC.error))
    outcome = solve(build_model(tiny, NO_DIVERSITY), NO_DIVERSITY)
    assert outcome.status == "failed"
    assert outcome.error == "solver stopped: error"
