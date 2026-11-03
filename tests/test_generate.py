import pytest

from cropplan.generate import generate_inputs, seeded_scenarios
from cropplan.pipeline import run_pipeline
from cropplan.validate import validate


def test_generation_is_deterministic():
    a, b = generate_inputs(2027), generate_inputs(2027)
    assert a.fields.equals(b.fields) and a.seed_supply.equals(b.seed_supply)
    assert a.yield_forecast.equals(b.yield_forecast)


def test_shape_matches_spec():
    inputs = generate_inputs()
    assert len(inputs.fields) == 150
    assert inputs.fields["grower_id"].nunique() == 25
    assert set(inputs.fields["region"]) == {"IA", "IL", "NE"}
    assert len(inputs.hybrids) == 8
    assert sorted(inputs.planting_capacity["window"].unique()) == ["W1", "W2", "W3", "W4"]
    assert validate(inputs, seeded_scenarios()["baseline-2027"][1]).ok


@pytest.fixture(scope="module")
def baseline():
    inputs, o = seeded_scenarios()["baseline-2027"]
    return inputs, run_pipeline(inputs, o)


def test_baseline_has_demo_tension(baseline):
    inputs, r = baseline
    assert r.status == "done"
    unplanted = r.assignments[r.assignments["hybrid_id"].isna()].merge(inputs.fields[["field_id", "region"]])
    assert 3 <= len(unplanted) <= 6
    assert set(unplanted["region"]) == {"NE"}
    util = r.seed_utilization.set_index("hybrid_id")["pct"]
    assert util["H-112"] > 0.99  # the high-yield favorite is supply-limited
    assert (util < 0.6).sum() >= 4  # most hybrids have room


def test_grower_commitments_validate_but_are_infeasible_on_ia_w1():
    inputs, o = seeded_scenarios()["grower-commitments-2027"]
    report = validate(inputs, o)
    assert report.ok
    assert {i.rule for i in report.warnings} == {"capacity_below_fixed"}
    r = run_pipeline(inputs, o)
    assert r.status == "infeasible"
    assert [(b.constraint, b.entity) for b in r.binding] == [("capacity", "IA/W1")]
    assert r.binding[0].shortfall > 0
