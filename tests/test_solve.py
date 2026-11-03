import pytest
from pyomo.contrib.appsi.base import TerminationCondition as TC

from cropplan.solve import classify, relative_gap


@pytest.mark.parametrize("termination, has_solution, expected", [
    (TC.optimal, True, "done"),
    (TC.maxTimeLimit, True, "done"),
    (TC.maxTimeLimit, False, "failed"),
    (TC.interrupted, True, "done"),
    (TC.maxIterations, True, "done"),
    (TC.interrupted, False, "failed"),
    (TC.infeasible, False, "infeasible"),
    (TC.infeasibleOrUnbounded, False, "infeasible"),
    (TC.error, False, "failed"),
])
def test_classify(termination, has_solution, expected):
    assert classify(termination, has_solution) == expected


def test_gurobi_gets_seed_threads_and_gap(monkeypatch):
    from pyomo.contrib.appsi.solvers import Gurobi
    from cropplan.overrides import Overrides
    from cropplan.solve import _make_solver
    monkeypatch.setattr(Gurobi, "available", lambda self: True)
    opt = _make_solver(Overrides(solver="gurobi", random_seed=7, threads=2, mip_rel_gap=0.01))
    assert opt.gurobi_options == {"MIPGap": 0.01, "Threads": 2, "Seed": 7}


def test_relative_gap():
    assert relative_gap(100.0, 101.0) == pytest.approx(0.01)
    assert relative_gap(None, 101.0) is None
    assert relative_gap(100.0, float("inf")) is None
