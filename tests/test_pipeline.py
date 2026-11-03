from dataclasses import replace

import pytest

from cropplan.overrides import Overrides
from cropplan.pipeline import MODEL_VERSION, run_pipeline
from conftest import tiny_inputs

O = Overrides(diversity_cap=1.0, corn_price_per_bu=1.0)


def test_done_reports_stages_kpis_and_versions(tiny):
    stages = []
    r = run_pipeline(tiny, O, on_stage=stages.append)
    assert stages == ["validating", "solving", "checking"]
    assert r.status == "done" and r.model_version == MODEL_VERSION
    assert r.solver == "highs" and r.solver_version
    assert r.summary["gross_margin"] == pytest.approx(5200.0)
    assert r.summary["net_margin"] == pytest.approx(5200.0)
    assert r.summary["acres_planted_pct"] == pytest.approx(1.0)
    assert r.summary["violations_count"] == 0
    util = r.seed_utilization.set_index("hybrid_id")
    assert util.at["HB", "pct"] == pytest.approx(1.0)


def test_invalid_stops_before_solving():
    inputs = tiny_inputs(fixed=[("F1", "HB", None), ("F2", "HB", None), ("F3", "HB", None)])
    stages = []
    r = run_pipeline(inputs, O, on_stage=stages.append)
    assert r.status == "invalid" and stages == ["validating"]
    assert "fixed requests need 300 units of HB" in r.error
    assert r.summary is None


def test_infeasible_is_diagnosed_with_binding_constraint():
    inputs = tiny_inputs(fixed=[(f"F{i}", "HA", "W1") for i in range(1, 5)])
    r = run_pipeline(inputs, O)
    assert r.status == "infeasible"
    assert [(b.constraint, b.entity, b.shortfall) for b in r.binding] == [("capacity", "R1/W1", 100.0)]
    assert r.infeasibility_reason == "Infeasible: Planting capacity R1/W1 short by 100 acres"
    assert any(i["rule"] == "capacity_below_fixed" for i in r.issues)


def test_unplanted_fields_are_penalized_violations(tiny):
    r = run_pipeline(tiny, replace(O, supply_pct={"HA": 0.1}))
    penalized = [v for v in r.violations if v["severity"] == "penalized"]
    assert len(penalized) == 2 and r.summary["unplanted_fields"] == 2
    assert r.summary["unplanted_penalty_total"] == pytest.approx(2 * 100 * 150)
    assert r.summary["net_margin"] == pytest.approx(r.summary["gross_margin"] - 30000)


def test_nothing_plantable_gives_zero_kpis_without_crashing(tiny):
    o = replace(O, capacity_pct={"R1": {w: 0.0 for w in ("W1", "W2", "W3", "W4")}},
                supply_pct={"HA": 0.0, "HB": 0.0})
    r = run_pipeline(tiny, o)
    assert r.status == "done"
    assert r.summary["acres_planted_pct"] == 0.0 and r.summary["gross_margin"] == 0.0
    util = r.seed_utilization.set_index("hybrid_id")
    assert util.at["HA", "pct"] is None  # 0 units available -> no division by zero


def test_done_carries_solver_termination_and_objective(tiny):
    r = run_pipeline(tiny, O)
    assert r.termination == "optimal"
    assert r.objective == pytest.approx(5200.0)


def test_infeasible_carries_termination_and_no_objective():
    r = run_pipeline(tiny_inputs(fixed=[(f"F{i}", "HA", "W1") for i in range(1, 5)]), O)
    assert r.termination == "infeasible" and r.objective is None


def test_infeasible_carries_the_diagnosis_outcome():
    r = run_pipeline(tiny_inputs(fixed=[(f"F{i}", "HA", "W1") for i in range(1, 5)]), O)
    assert r.diagnosis == "explained"
