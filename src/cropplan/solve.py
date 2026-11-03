"""Run a built model through the configured solver and classify the outcome."""

from __future__ import annotations

import time
from dataclasses import dataclass

from pyomo.contrib.appsi.base import TerminationCondition as TC
from pyomo.contrib.appsi.solvers import Gurobi, Highs

from cropplan.model import BuiltModel
from cropplan.overrides import Overrides


class SolverUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SolveOutcome:
    status: str  # "done" | "infeasible" | "failed"
    termination: str
    objective: float | None
    mip_gap: float | None
    solver: str
    solver_version: str
    runtime_s: float
    error: str | None = None


def _make_solver(overrides: Overrides):
    if overrides.solver == "highs":
        opt = Highs()
        options = {"mip_rel_gap": overrides.mip_rel_gap}
        if overrides.threads is not None:
            options["threads"] = overrides.threads
        if overrides.random_seed is not None:
            options["random_seed"] = overrides.random_seed
        opt.highs_options = options
    else:
        opt = Gurobi()
        opt.gurobi_options = {"MIPGap": overrides.mip_rel_gap}
        if overrides.threads is not None:
            opt.gurobi_options["Threads"] = overrides.threads
        if overrides.random_seed is not None:
            opt.gurobi_options["Seed"] = overrides.random_seed
    if not opt.available():
        raise SolverUnavailable(f"solver {overrides.solver!r} is not available in this environment")
    opt.config.load_solution = False
    opt.config.time_limit = overrides.time_limit_s
    return opt


# Terminations where the solver stopped before proving optimality; with an incumbent the plan is usable.
STOPPED_EARLY = (TC.maxTimeLimit, TC.interrupted, TC.maxIterations)


def classify(termination: TC, has_solution: bool) -> str:
    if termination == TC.optimal:
        return "done"
    if termination in (TC.infeasible, TC.infeasibleOrUnbounded):
        return "infeasible"
    if termination in STOPPED_EARLY and has_solution:
        return "done"
    return "failed"


def relative_gap(objective: float | None, bound: float | None) -> float | None:
    if objective is None or bound is None or abs(bound) == float("inf"):
        return None
    return abs(bound - objective) / max(abs(objective), 1e-9)


def solve(built: BuiltModel, overrides: Overrides) -> SolveOutcome:
    try:
        opt = _make_solver(overrides)
    except SolverUnavailable as exc:
        return SolveOutcome("failed", "unavailable", None, None, overrides.solver, "n/a", 0.0, str(exc))
    version = ".".join(str(p) for p in opt.version())
    start = time.monotonic()
    res = opt.solve(built.model)
    runtime = time.monotonic() - start
    has_solution = res.best_feasible_objective is not None
    status = classify(res.termination_condition, has_solution)
    if has_solution:
        res.solution_loader.load_vars()
    error = None
    if status == "failed":
        error = (
            f"no feasible solution within {overrides.time_limit_s}s time limit"
            if res.termination_condition == TC.maxTimeLimit
            else f"solver stopped: {res.termination_condition.name}"
        )
    objective = res.best_feasible_objective
    gap = relative_gap(objective, res.best_objective_bound)
    return SolveOutcome(status, res.termination_condition.name, objective, gap, overrides.solver,
                        version, runtime, error)
