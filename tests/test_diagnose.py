import pytest

from cropplan import diagnose as diag
from cropplan.diagnose import (DIAGNOSIS_FAILED, EXPLAINED, FIXED_IMPOSSIBLE, BindingConstraint, Diagnosis,
                               diagnose, infeasibility_reason)
from cropplan.overrides import Overrides
from cropplan.solve import SolveOutcome
from conftest import tiny_inputs

O = Overrides(diversity_cap=1.0, corn_price_per_bu=1.0)
OVER_W1 = [(f"F{i}", "HA", "W1") for i in range(1, 5)]  # 400 fixed acres in a 300-acre window


def test_explained_names_the_binding_constraint():
    d = diagnose(tiny_inputs(fixed=OVER_W1), O)
    assert d.outcome == EXPLAINED
    assert [(b.constraint, b.entity, b.shortfall) for b in d.binding] == [("capacity", "R1/W1", 100.0)]


def test_contradictory_fixed_requests_are_reported_as_impossible():
    # Two pinned windows for one field can't both hold even with every resource relaxed.
    d = diagnose(tiny_inputs(fixed=[("F1", "HA", "W1"), ("F1", "HA", "W2")]), O)
    assert d == Diagnosis(FIXED_IMPOSSIBLE)
    assert infeasibility_reason(d) == "Infeasible: fixed requests cannot be satisfied even with relaxed resources"


def test_non_optimal_relaxed_solve_is_a_failed_diagnosis_not_a_shortfall(monkeypatch):
    stopped = SolveOutcome("done", "maxTimeLimit", 5.0, 0.2, "highs", "1.15.1", 60.0)
    monkeypatch.setattr(diag, "solve", lambda built, overrides: stopped)
    d = diagnose(tiny_inputs(fixed=OVER_W1), O)
    assert d.outcome == DIAGNOSIS_FAILED and d.binding == []
    assert infeasibility_reason(d) == (
        "Infeasible: diagnosis failed (relaxed solve stopped: maxTimeLimit); binding constraint unknown")


def test_relaxed_solver_error_is_a_failed_diagnosis(monkeypatch):
    broken = SolveOutcome("failed", "error", None, None, "highs", "1.15.1", 0.1, "solver stopped: error")
    monkeypatch.setattr(diag, "solve", lambda built, overrides: broken)
    d = diagnose(tiny_inputs(fixed=OVER_W1), O)
    assert d.outcome == DIAGNOSIS_FAILED and "solver stopped: error" in infeasibility_reason(d)


@pytest.mark.parametrize("amount, text", [(290.4, "short by 290 acres"), (1.0, "short by 1 acres"),
                                          (0.04, "short by 0.04 acres"), (0.5, "short by 0.5 acres")])
def test_describe_never_says_short_by_zero(amount, text):
    assert BindingConstraint("capacity", "IA/W1", amount, "acres").describe().endswith(text)
