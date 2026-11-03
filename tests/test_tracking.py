import pandas as pd

from cropplan.overrides import Overrides
from cropplan.pipeline import PipelineResult
from cropplan_jobs.tracking import flatten_overrides, log_solve, solve_metrics, solve_tags
from conftest import RecordingRun


def test_flatten_overrides_makes_flat_params():
    flat = flatten_overrides(Overrides(supply_pct={"H-112": 1.1}, capacity_pct={"IA": {"W1": 0.5}}, threads=None))
    assert flat["supply_pct.H-112"] == 1.1 and flat["capacity_pct.IA.W1"] == 0.5
    assert flat["threads"] == "none" and flat["diversity_cap"] == 0.4
    assert "supply_pct" not in flat and "capacity_pct" not in flat


def test_metrics_and_tags_for_a_done_solve():
    r = PipelineResult(status="done", solver="highs", solver_version="1.15.1", termination="optimal",
                       objective=10.0, mip_gap=0.0005, runtime_s=2.0,
                       summary={"acres_planted_pct": 1.0, "gross_margin": 10.0, "unplanted_penalty_total": 0.0,
                                "net_margin": 10.0, "unplanted_fields": 0, "violations_count": 0})
    assert solve_metrics(r) == {"acres_planted_pct": 1.0, "gross_margin": 10.0, "unplanted_penalty_total": 0.0,
                                "net_margin": 10.0, "unplanted_fields": 0.0, "violations_count": 0.0,
                                "objective": 10.0, "mip_gap": 0.0005, "runtime_s": 2.0}
    assert solve_tags(r) == {"status": "done", "model_version": r.model_version, "solver": "highs",
                             "solver_version": "1.15.1", "termination": "optimal"}


def test_log_solve_logs_params_metrics_tags_and_plan_artifact():
    run = RecordingRun("m1")
    plan = pd.DataFrame({"field_id": ["F1"], "hybrid_id": ["HA"]})
    log_solve(run, Overrides(), PipelineResult(status="done", assignments=plan, summary={"gross_margin": 1.0}))
    assert run.params["random_seed"] == 2027 and run.metrics == {"gross_margin": 1.0}
    assert run.tags["status"] == "done" and list(run.frames) == ["plan_assignments.parquet"]


def test_log_solve_for_invalid_overrides_has_no_params_or_artifact():
    run = RecordingRun("m1")
    log_solve(run, None, PipelineResult(status="invalid", error="bad"))
    assert run.params == {} and run.frames == {} and run.tags["status"] == "invalid"
