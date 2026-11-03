import pandas as pd
import pytest

from cropplan.disrupt import KINDS, apply_disruption, sample_disruptions, summarize_stress
from cropplan.overrides import Overrides


def test_sampling_is_seeded_and_bounded(tiny):
    a = sample_disruptions(tiny, 200, seed=1)
    assert a == sample_disruptions(tiny, 200, seed=1)
    assert a != sample_disruptions(tiny, 200, seed=2)
    assert {d["kind"] for d in a} == set(KINDS)
    for d in a:
        if d["kind"] == "seed_shortfall":
            assert 0.6 <= d["multiplier"] <= 0.9
        elif d["kind"] == "lost_capacity":
            assert 0.3 <= d["multiplier"] <= 0.8
        else:
            assert 0.05 <= d["fraction"] <= 0.20


def test_multipliers_compound_with_scenario_overrides(tiny):
    o = Overrides(supply_pct={"HB": 1.1}, capacity_pct={"R1": {"W1": 0.5}})
    _, o2 = apply_disruption(tiny, o, {"kind": "seed_shortfall", "hybrid_id": "HB", "multiplier": 0.5})
    assert o2.supply_multiplier("HB") == pytest.approx(0.55)
    _, o3 = apply_disruption(tiny, o, {"kind": "lost_capacity", "region": "R1", "window": "W1", "multiplier": 0.5})
    assert o3.capacity_multiplier("R1", "W1") == pytest.approx(0.25)
    assert o.supply_multiplier("HB") == 1.1  # original untouched


def test_lost_acreage_drops_fields_and_their_fixed_requests(tiny):
    from conftest import tiny_inputs
    inputs = tiny_inputs(fixed=[(f"F{i}", "HA", None) for i in range(1, 6)])
    out, _ = apply_disruption(inputs, Overrides(), {"kind": "lost_acreage", "region": "R1", "fraction": 0.2, "seed": 3})
    assert len(out.fields) == 4
    assert set(out.fixed_requests["field_id"]) == set(out.fields["field_id"])


def test_summary_counts_infeasible_samples_and_excludes_them_from_percentiles():
    results = pd.DataFrame([
        {"sample_id": 0, "kind": "seed_shortfall", "hybrid_id": "HB", "status": "done", "gross_margin": 100.0,
         "unplanted_field_ids": ["F1"]},
        {"sample_id": 1, "kind": "seed_shortfall", "hybrid_id": "HA", "status": "done", "gross_margin": 200.0,
         "unplanted_field_ids": ["F1", "F2"]},
        {"sample_id": 2, "kind": "lost_capacity", "hybrid_id": None, "status": "infeasible", "gross_margin": None,
         "unplanted_field_ids": []},
        {"sample_id": 3, "kind": "lost_capacity", "hybrid_id": None, "status": "failed", "gross_margin": None,
         "unplanted_field_ids": []},
    ])
    s = summarize_stress(results, base_unplanted={"F2"})
    assert (s["n"], s["n_solved"], s["n_infeasible"], s["n_failed"]) == (4, 2, 1, 1)
    assert s["p50_gross_margin"] == pytest.approx(150.0)
    assert s["fragile_fields"] == ["F1"]
    assert s["fragile_hybrids"] == ["HB", "HA"]


def test_summary_with_no_solved_samples():
    results = pd.DataFrame([{"sample_id": 0, "kind": "lost_capacity", "hybrid_id": None, "status": "infeasible",
                             "gross_margin": None, "unplanted_field_ids": []}])
    s = summarize_stress(results, base_unplanted=set())
    assert s["p10_gross_margin"] is None and s["fragile_fields"] == [] and s["fragile_hybrids"] == []


def test_invalid_samples_are_counted_separately_from_failures():
    results = pd.DataFrame([
        {"sample_id": 0, "kind": "seed_shortfall", "hybrid_id": "HB", "status": "done", "gross_margin": 100.0,
         "unplanted_field_ids": []},
        {"sample_id": 1, "kind": "seed_shortfall", "hybrid_id": "HB", "status": "invalid", "gross_margin": None,
         "unplanted_field_ids": []},
    ])
    s = summarize_stress(results, base_unplanted=set())
    assert (s["n_invalid"], s["n_failed"], s["n_solved"]) == (1, 0, 1)
