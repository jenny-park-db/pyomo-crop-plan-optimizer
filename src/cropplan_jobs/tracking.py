"""MLflow logging behind a small interface, so solve logic is unit-tested without MLflow installed."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from typing import Any, Iterator, Protocol

import pandas as pd

from cropplan.overrides import Overrides
from cropplan.pipeline import PipelineResult

KPI_KEYS = ("acres_planted_pct", "gross_margin", "unplanted_penalty_total", "net_margin", "unplanted_fields",
            "violations_count")


class TrackedRun(Protocol):
    run_id: str

    def log_params(self, params: dict[str, Any]) -> None: ...
    def log_metrics(self, metrics: dict[str, float]) -> None: ...
    def set_tags(self, tags: dict[str, str]) -> None: ...
    def log_frame(self, name: str, frame: pd.DataFrame) -> None: ...


class Tracker(Protocol):
    def start_run(self, run_name: str, tags: dict[str, str]):
        """Context manager yielding a TrackedRun; the run ends FAILED if the block raises."""


def flatten_overrides(overrides: Overrides) -> dict[str, Any]:
    """MLflow params are flat: supply_pct.H-112=1.1, capacity_pct.IA.W1=0.5, diversity_cap=0.4, ..."""
    flat: dict[str, Any] = {}
    for key, value in overrides.to_dict().items():
        if key == "supply_pct":
            flat.update({f"supply_pct.{h}": v for h, v in sorted(value.items())})
        elif key == "capacity_pct":
            flat.update({f"capacity_pct.{r}.{w}": v for r, ws in sorted(value.items()) for w, v in sorted(ws.items())})
        else:
            flat[key] = "none" if value is None else value
    return flat


def solve_metrics(result: PipelineResult) -> dict[str, float]:
    metrics = {k: float(result.summary[k]) for k in KPI_KEYS if result.summary and result.summary.get(k) is not None}
    for key in ("objective", "mip_gap", "runtime_s"):
        value = getattr(result, key)
        if value is not None:
            metrics[key] = float(value)
    return metrics


def solve_tags(result: PipelineResult) -> dict[str, str]:
    tags = {"status": result.status, "model_version": result.model_version}
    for key in ("solver", "solver_version", "termination"):
        value = getattr(result, key)
        if value:
            tags[key] = str(value)
    return tags


def log_solve(run: TrackedRun, overrides: Overrides | None, result: PipelineResult) -> None:
    """params = overrides, metrics = summary KPIs (+ objective/gap/runtime), artifact = plan_assignments.parquet."""
    if overrides is not None:
        run.log_params(flatten_overrides(overrides))
    run.log_metrics(solve_metrics(result))
    run.set_tags(solve_tags(result))
    if result.assignments is not None:
        run.log_frame("plan_assignments.parquet", result.assignments)


class _MlflowRun:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def log_params(self, params: dict[str, Any]) -> None:
        import mlflow
        mlflow.log_params(params)

    def log_metrics(self, metrics: dict[str, float]) -> None:
        import mlflow
        mlflow.log_metrics(metrics)

    def set_tags(self, tags: dict[str, str]) -> None:
        import mlflow
        mlflow.set_tags(tags)

    def log_frame(self, name: str, frame: pd.DataFrame) -> None:
        import mlflow
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, name)
            frame.to_parquet(path, index=False)
            mlflow.log_artifact(path)


class MlflowTracker:
    """Logs to a workspace experiment. ``run_id=`` resumes an existing run (the AI Runtime task's own run)."""

    def __init__(self, experiment: str | None) -> None:
        self.experiment = experiment

    @contextmanager
    def start_run(self, run_name: str | None, tags: dict[str, str], run_id: str | None = None) -> Iterator[_MlflowRun]:
        import mlflow
        mlflow.set_tracking_uri("databricks")
        if run_id is None:
            mlflow.set_experiment(self.experiment)
        with mlflow.start_run(run_id=run_id, run_name=run_name, tags=tags) as run:
            yield _MlflowRun(run.info.run_id)
