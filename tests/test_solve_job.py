import json
from datetime import datetime

import pandas as pd
import pytest

from cropplan.overrides import Overrides
from cropplan_jobs import solve_job
from cropplan_jobs.scenarios import ScenarioNotFound, write_scenario
from cropplan_jobs.solve_job import default_run_id, solve_scenario
from cropplan_jobs.store import MemoryStore, ensure_row
from conftest import RecordingTracker, tiny_inputs

O = Overrides(diversity_cap=1.0, corn_price_per_bu=1.0)
OVER_W1 = [(f"F{i}", "HA", "W1") for i in range(1, 5)]
NOW = datetime(2027, 1, 1)


class SpyStore(MemoryStore):
    """Records every runs.status the job writes, in order."""

    def __init__(self):
        super().__init__()
        self.statuses = []

    def update(self, table, values, **where):
        if table == "runs" and "status" in values:
            self.statuses.append(values["status"])
        super().update(table, values, **where)


def _setup(inputs=None, overrides=O):
    store, tracker = SpyStore(), RecordingTracker()
    write_scenario(store, "s1", "S1", inputs or tiny_inputs(), overrides, parent_scenario_id=None,
                   created_by="planner@example.com", source="app")
    return store, tracker


def _solve(store, tracker, run_id="r1", scenario_id="s1", triggered_by="planner@example.com"):
    return solve_scenario(store, tracker, scenario_id=scenario_id, run_id=run_id, job_run_id="900",
                          triggered_by=triggered_by, now=lambda: NOW)


def _run_row(store, run_id="r1"):
    return store.read("runs", run_id=run_id).iloc[0]


def test_done_walks_the_status_lifecycle_and_writes_everything():
    store, tracker = _setup()
    result = _solve(store, tracker)
    assert result.status == "done"
    assert store.statuses == ["validating", "solving", "checking", "done"]
    row = _run_row(store)
    assert (row["status"], row["termination"], row["job_run_id"], row["triggered_by"]) == (
        "done", "optimal", "900", "planner@example.com")
    assert row["objective"] == pytest.approx(5200.0) and row["mlflow_run_id"] == "mlflow-1"
    assert row["model_version"] == result.model_version and row["ended_at"] == NOW
    assert len(store.read("plan_assignments", run_id="r1")) == 5
    assert store.read("run_summary", run_id="r1").iloc[0]["gross_margin"] == pytest.approx(5200.0)
    assert len(store.read("seed_utilization", run_id="r1")) == 2
    run = tracker.runs[0]
    assert run.name == "s1" and tracker.ended == ["FINISHED"]
    assert {k: run.tags[k] for k in ("scenario_id", "run_id", "job_run_id", "triggered_by")} == {
        "scenario_id": "s1", "run_id": "r1", "job_run_id": "900", "triggered_by": "planner@example.com"}
    assert run.metrics["gross_margin"] == pytest.approx(5200.0) and "plan_assignments.parquet" in run.frames


def test_bad_overrides_payload_is_invalid_not_a_crash():
    store, tracker = _setup()
    store.update("scenarios", {"overrides": json.dumps({"diversity_cap": 9})}, scenario_id="s1")
    result = _solve(store, tracker)
    assert result.status == "invalid" and store.statuses == ["validating", "invalid"]
    assert "diversity_cap" in _run_row(store)["error"]


def test_validation_errors_are_invalid_and_listed_as_violation_rows():
    store, tracker = _setup(tiny_inputs(fixed=[("F1", "HB", None), ("F2", "HB", None), ("F3", "HB", None)]))
    assert _solve(store, tracker).status == "invalid"
    rows = store.read("violations", run_id="r1")
    assert "error" in set(rows["severity"]) and store.read("run_summary", run_id="r1").empty


def test_infeasible_records_reason_and_binding_rows():
    store, tracker = _setup(tiny_inputs(fixed=OVER_W1))
    assert _solve(store, tracker).status == "infeasible"
    row = _run_row(store)
    assert row["infeasibility_reason"] == "Infeasible: Planting capacity R1/W1 short by 100 acres"
    assert row["termination"] == "infeasible"
    v = store.read("violations", run_id="r1")
    assert v[v["severity"] == "binding"][["rule", "entity"]].values.tolist() == [["capacity", "R1/W1"]]
    assert "warning" in set(v["severity"])  # capacity_below_fixed from validation


def test_exception_marks_the_run_failed_and_reraises(monkeypatch):
    store, tracker = _setup()
    monkeypatch.setattr(solve_job, "run_pipeline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        _solve(store, tracker)
    row = _run_row(store)
    assert (row["status"], row["error"]) == ("failed", "RuntimeError: boom") and tracker.ended == ["FAILED"]


def test_missing_scenario_fails_with_a_readable_error():
    store, tracker = _setup()
    with pytest.raises(ScenarioNotFound):
        _solve(store, tracker, scenario_id="nope")
    assert _run_row(store)["error"] == "ScenarioNotFound: scenario 'nope' not found"


def test_row_written_by_the_app_keeps_its_triggered_by():
    store, tracker = _setup()
    ensure_row(store, "runs", {"run_id": "r1", "scenario_id": "s1", "status": "queued",
                               "triggered_by": "planner@example.com"}, run_id="r1")
    _solve(store, tracker, triggered_by="app-sp")
    assert _run_row(store)["triggered_by"] == "planner@example.com" and len(store.read("runs")) == 1


def test_run_id_of_another_scenario_is_rejected():
    store, tracker = _setup()
    ensure_row(store, "runs", {"run_id": "r1", "scenario_id": "other", "status": "queued"}, run_id="r1")
    with pytest.raises(ValueError, match="belongs to scenario"):
        _solve(store, tracker)


def test_retry_replaces_outputs_instead_of_duplicating():
    store, tracker = _setup()
    _solve(store, tracker)
    _solve(store, tracker)
    assert len(store.read("plan_assignments", run_id="r1")) == 5 and len(store.read("runs")) == 1


def test_default_run_id():
    assert default_run_id("", "123") == "run-123" and default_run_id("r9", "123") == "r9"


def test_infeasible_run_records_the_diagnosis_outcome():
    store, tracker = _setup(tiny_inputs(fixed=OVER_W1))
    _solve(store, tracker)
    assert _run_row(store)["diagnosis"] == "explained"


def test_done_run_has_no_diagnosis():
    store, tracker = _setup()
    _solve(store, tracker)
    assert pd.isna(_run_row(store)["diagnosis"])


def test_direct_job_run_stamps_submitted_at_but_keeps_the_apps():
    store, tracker = _setup()
    _solve(store, tracker, run_id="direct")
    assert _run_row(store, "direct")["submitted_at"] == NOW
    app_time = datetime(2026, 12, 31, 23, 59)
    ensure_row(store, "runs", {"run_id": "r1", "scenario_id": "s1", "status": "queued",
                               "triggered_by": "planner@example.com", "submitted_at": app_time}, run_id="r1")
    _solve(store, tracker)
    assert _run_row(store)["submitted_at"] == app_time
