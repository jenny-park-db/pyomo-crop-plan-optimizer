"""The solve_scenario job: runs row lifecycle, pipeline, outputs, and one MLflow run per solve."""

from __future__ import annotations

from typing import Callable

import pandas as pd

from cropplan.overrides import OverridesError, parse_overrides
from cropplan.pipeline import PipelineResult, run_pipeline
from cropplan_jobs.scenarios import load_scenario, utcnow
from cropplan_jobs.store import TableStore, ensure_row
from cropplan_jobs.tables import check_id
from cropplan_jobs.tracking import Tracker, log_solve

RESULT_TABLES = ("plan_assignments", "run_summary", "seed_utilization", "violations")


def default_run_id(run_id: str, job_run_id: str) -> str:
    """App and agent pass the run_id they already wrote; direct job runs get one derived from the job run."""
    return run_id or f"run-{job_run_id}"


def open_run(store: TableStore, *, run_id: str, scenario_id: str, job_run_id: str, triggered_by: str,
             now: Callable = utcnow) -> None:
    """Create the runs row if the caller didn't (status queued), then stamp the job run onto it."""
    ensure_row(store, "runs", {"run_id": run_id, "scenario_id": scenario_id, "triggered_by": triggered_by,
                               "status": "queued", "submitted_at": now()}, run_id=run_id)
    existing = store.read("runs", run_id=run_id).iloc[0]
    if existing["scenario_id"] != scenario_id:
        raise ValueError(f"run {run_id!r} belongs to scenario {existing['scenario_id']!r}, not {scenario_id!r}")
    values = {"job_run_id": job_run_id, "started_at": now()}
    if pd.isna(existing["triggered_by"]) or not existing["triggered_by"]:
        values["triggered_by"] = triggered_by
    store.update("runs", values, run_id=run_id)


def _violation_rows(result: PipelineResult) -> list[dict]:
    """Validation issues (error/warning), diagnosis (binding), and post-solve checks (hard/penalized)."""
    rows = [dict(i) for i in result.issues] + [dict(v) for v in result.violations]
    rows += [{"rule": b.constraint, "entity": b.entity, "severity": "binding", "detail": b.describe()}
             for b in result.binding]
    return rows


def write_outputs(store: TableStore, scenario_id: str, run_id: str, result: PipelineResult) -> None:
    """Replace this run's result rows, so a retried task never duplicates them."""
    key = {"scenario_id": scenario_id, "run_id": run_id}
    frames = {
        "plan_assignments": result.assignments if result.assignments is not None else pd.DataFrame(),
        "run_summary": pd.DataFrame([result.summary]) if result.summary else pd.DataFrame(),
        "seed_utilization": result.seed_utilization if result.seed_utilization is not None else pd.DataFrame(),
        "violations": pd.DataFrame(_violation_rows(result)),
    }
    for table in RESULT_TABLES:
        frame = frames[table]
        store.replace(table, frame.assign(**key) if not frame.empty else frame, run_id=run_id)


def _final_values(result: PipelineResult, now: Callable) -> dict:
    return {"status": result.status, "solver": result.solver, "solver_version": result.solver_version,
            "model_version": result.model_version, "ended_at": now(), "error": result.error,
            "infeasibility_reason": result.infeasibility_reason, "diagnosis": result.diagnosis,
            "mip_gap": result.mip_gap,
            "termination": result.termination, "objective": result.objective, "runtime_s": result.runtime_s}


def solve_scenario(store: TableStore, tracker: Tracker, *, scenario_id: str, run_id: str, job_run_id: str,
                   triggered_by: str, now: Callable = utcnow) -> PipelineResult:
    """validate → solve → diagnose → postcheck, with runs.status updated at each stage.

    A bad overrides payload ends as ``invalid``. Any exception marks the run ``failed`` with the error text and
    is re-raised, so the job run fails too and the Jobs API agrees with the runs table.
    """
    check_id(scenario_id, "scenario_id")
    check_id(run_id, "run_id")
    open_run(store, run_id=run_id, scenario_id=scenario_id, job_run_id=job_run_id, triggered_by=triggered_by,
             now=now)
    tags = {"scenario_id": scenario_id, "run_id": run_id, "job_run_id": job_run_id, "triggered_by": triggered_by}
    try:
        with tracker.start_run(scenario_id, tags) as tracked:
            def stage(status: str) -> None:
                store.update("runs", {"status": status, "mlflow_run_id": tracked.run_id}, run_id=run_id)

            _, inputs, payload = load_scenario(store, scenario_id)
            try:
                overrides = parse_overrides(payload)
            except OverridesError as exc:
                stage("validating")
                overrides, result = None, PipelineResult(status="invalid", error=f"overrides: {exc}")
            else:
                result = run_pipeline(inputs, overrides, on_stage=stage)
            write_outputs(store, scenario_id, run_id, result)
            log_solve(tracked, overrides, result)
            store.update("runs", _final_values(result, now), run_id=run_id)
            return result
    except Exception as exc:
        store.update("runs", {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "ended_at": now()},
                     run_id=run_id)
        raise
