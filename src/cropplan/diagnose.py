"""Explain infeasibility by re-solving with slack on resource constraints."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pyomo.environ as pe

from cropplan.data import ScenarioInputs
from cropplan.model import build_model
from cropplan.overrides import Overrides
from cropplan.solve import solve

# Slack below this is solver noise, not a shortfall worth reporting.
TOLERANCE = 1e-3
UNITS = {"supply": "seed units", "capacity": "acres", "diversity": "acres"}
LABELS = {"supply": "Seed supply", "capacity": "Planting capacity", "diversity": "Diversity cap"}

EXPLAINED = "explained"
FIXED_IMPOSSIBLE = "fixed_requests_impossible"
DIAGNOSIS_FAILED = "diagnosis_failed"


def format_amount(amount: float) -> str:
    """Whole numbers for real shortfalls; two significant digits below 1 so we never print "short by 0"."""
    return f"{amount:,.0f}" if amount >= 1 else f"{amount:.2g}"


@dataclass(frozen=True)
class BindingConstraint:
    constraint: str  # "supply" | "capacity" | "diversity"
    entity: str  # e.g. "H-112", "IA/W1", "G-03/H-112"
    shortfall: float
    unit: str

    def describe(self) -> str:
        return f"{LABELS[self.constraint]} {self.entity} short by {format_amount(self.shortfall)} {self.unit}"


@dataclass(frozen=True)
class Diagnosis:
    outcome: str  # EXPLAINED | FIXED_IMPOSSIBLE | DIAGNOSIS_FAILED
    binding: list[BindingConstraint] = field(default_factory=list)
    detail: str | None = None  # why diagnosis failed, when it did


def diagnose(inputs: ScenarioInputs, overrides: Overrides) -> Diagnosis:
    """Find the resource constraints that must be relaxed (and by how much) to make the plan feasible.

    The relaxed model can only be infeasible when fixed requests contradict each other or the
    field-assignment rule, so an infeasible relaxed solve means "fixed requests impossible". Any other
    non-optimal relaxed solve (time limit, solver error) means the diagnosis itself failed: slack
    amounts from a non-optimal solve aren't minimal, so they're not reported.
    """
    built = build_model(inputs, overrides, relax=True)
    outcome = solve(built, replace(overrides, time_limit_s=max(overrides.time_limit_s, 60)))
    if outcome.status == "infeasible":
        return Diagnosis(FIXED_IMPOSSIBLE)
    if outcome.termination != "optimal":
        return Diagnosis(DIAGNOSIS_FAILED, detail=outcome.error or f"relaxed solve stopped: {outcome.termination}")
    m = built.model
    found = []
    for name, var in (("supply", m.s_supply), ("capacity", m.s_capacity), ("diversity", m.s_diversity)):
        for key in var:
            amount = pe.value(var[key])
            if amount > TOLERANCE:
                entity = "/".join(key) if isinstance(key, tuple) else str(key)
                found.append(BindingConstraint(name, entity, round(float(amount), 6), UNITS[name]))
    if not found:
        return Diagnosis(DIAGNOSIS_FAILED, detail="relaxed solve needed no slack; the infeasibility is unexplained")
    return Diagnosis(EXPLAINED, sorted(found, key=lambda b: -b.shortfall))


def infeasibility_reason(diagnosis: Diagnosis) -> str:
    if diagnosis.outcome == FIXED_IMPOSSIBLE:
        return "Infeasible: fixed requests cannot be satisfied even with relaxed resources"
    if diagnosis.outcome == DIAGNOSIS_FAILED:
        return f"Infeasible: diagnosis failed ({diagnosis.detail}); binding constraint unknown"
    return "Infeasible: " + "; ".join(b.describe() for b in diagnosis.binding)
