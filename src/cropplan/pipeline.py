"""validate → solve → (diagnose) → postcheck → summarize, with a stage callback for status updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from cropplan import __version__
from cropplan.data import ScenarioInputs
from cropplan.diagnose import BindingConstraint, diagnose, infeasibility_reason
from cropplan.model import build_model, extract_assignments
from cropplan.overrides import Overrides
from cropplan.solve import solve
from cropplan.summary import issues_to_rows, postcheck, summarize
from cropplan.validate import validate

MODEL_VERSION = f"cropplan@{__version__}"
Stage = Callable[[str], None]


@dataclass
class PipelineResult:
    status: str  # "done" | "invalid" | "infeasible" | "failed"
    model_version: str = MODEL_VERSION
    solver: str | None = None
    solver_version: str | None = None
    termination: str | None = None  # solver termination name, e.g. "optimal", "maxTimeLimit"
    objective: float | None = None  # best feasible objective (net margin) when one exists
    mip_gap: float | None = None
    runtime_s: float | None = None
    error: str | None = None
    infeasibility_reason: str | None = None
    diagnosis: str | None = None  # "explained" | "fixed_requests_impossible" | "diagnosis_failed"
    binding: list[BindingConstraint] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)  # validation errors/warnings
    violations: list[dict] = field(default_factory=list)  # post-solve
    assignments: pd.DataFrame | None = None
    summary: dict | None = None
    seed_utilization: pd.DataFrame | None = None


def run_pipeline(inputs: ScenarioInputs, overrides: Overrides, on_stage: Stage = lambda s: None) -> PipelineResult:
    on_stage("validating")
    report = validate(inputs, overrides)
    issues = issues_to_rows(report.issues)
    if not report.ok:
        return PipelineResult(status="invalid", issues=issues,
                              error="; ".join(i.detail for i in report.errors))

    on_stage("solving")
    built = build_model(inputs, overrides)
    outcome = solve(built, overrides)
    result = PipelineResult(status=outcome.status, solver=outcome.solver, solver_version=outcome.solver_version,
                            termination=outcome.termination, objective=outcome.objective,
                            mip_gap=outcome.mip_gap, runtime_s=outcome.runtime_s, error=outcome.error,
                            issues=issues)
    if outcome.status == "infeasible":
        found = diagnose(inputs, overrides)
        result.diagnosis, result.binding = found.outcome, found.binding
        result.infeasibility_reason = infeasibility_reason(found)
        return result
    if outcome.status != "done":
        return result

    on_stage("checking")
    assignments = extract_assignments(built, inputs)
    violations = postcheck(inputs, overrides, assignments)
    summary, util = summarize(inputs, overrides, assignments, violations)
    result.assignments, result.violations = assignments, violations
    result.summary, result.seed_utilization = summary, util
    return result
