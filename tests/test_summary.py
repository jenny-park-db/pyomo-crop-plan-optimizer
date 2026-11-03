import pandas as pd
import pytest

from cropplan.overrides import Overrides
from cropplan.summary import postcheck
from conftest import tiny_inputs

O = Overrides(diversity_cap=0.34)


def assignments(rows):
    """Hand-built plan: (field_id, hybrid_id, window) per field; acres 100 each like the tiny instance."""
    return pd.DataFrame([{"field_id": f, "hybrid_id": h, "window": w, "acres": 100.0, "exp_yield": 0.0,
                          "exp_margin": 0.0, "is_fixed": False} for f, h, w in rows])


def test_postcheck_flags_each_broken_rule_as_hard():
    inputs = tiny_inputs()
    fields = inputs.fields.copy()
    fields.loc[fields["field_id"] == "F5", "rm_max"] = 102  # HB (RM 105) not allowed on F5
    inputs = inputs.with_fields(fields)
    plan = assignments([
        ("F1", "HB", "W1"), ("F2", "HB", "W1"), ("F3", "HB", "W1"),  # 300 HB units > 200; G1 all on HB
        ("F4", "HA", "W1"), ("F5", "HB", "W2"),                      # 4 fields in W1 = 400 acres > 300
    ])
    hard = {(v["rule"], v["entity"]) for v in postcheck(inputs, O, plan) if v["severity"] == "hard"}
    assert ("supply", "HB") in hard
    assert ("capacity", "R1/W1") in hard
    assert ("diversity", "G1/HB") in hard
    assert ("eligibility", "F5") in hard


def test_postcheck_valid_plan_has_no_hard_rows():
    plan = assignments([("F1", "HB", "W1"), ("F2", "HA", "W1"), ("F3", "HA", "W2"),
                        ("F4", "HB", "W1"), ("F5", "HA", "W2")])
    rows = postcheck(tiny_inputs(), Overrides(diversity_cap=1.0), plan)
    assert [v for v in rows if v["severity"] == "hard"] == []


def test_postcheck_tolerance_is_relative_with_a_floor():
    from cropplan.summary import tolerance
    assert tolerance(300.0) == 1e-3  # floor
    assert tolerance(5e6) == pytest.approx(5.0)  # 1e-6 of a large limit


def test_postcheck_ignores_solver_noise_but_flags_real_overuse():
    inputs = tiny_inputs()
    noisy = assignments([("F1", "HB", "W1"), ("F2", "HB", "W2"), ("F3", "HA", "W2"),
                         ("F4", "HA", "W2"), ("F5", "HA", "W2")])
    noisy.loc[noisy["field_id"] == "F2", "acres"] = 100.0004  # HB uses 200.0004 of 200 units
    hard = [v for v in postcheck(inputs, Overrides(diversity_cap=1.0), noisy) if v["severity"] == "hard"]
    assert hard == []
    noisy.loc[noisy["field_id"] == "F2", "acres"] = 100.01
    hard = [v for v in postcheck(inputs, Overrides(diversity_cap=1.0), noisy) if v["severity"] == "hard"]
    assert [(v["rule"], v["entity"]) for v in hard] == [("supply", "HB")]


def test_postcheck_flags_fixed_requests_that_were_not_honored():
    inputs = tiny_inputs(fixed=[("F1", "HB", "W1"), ("F2", "HA", None), ("F3", "HA", "W2")])
    plan = assignments([("F1", "HB", "W2"), ("F2", "HA", "W4"), ("F3", None, None),
                        ("F4", "HA", "W1"), ("F5", "HA", "W1")])
    rows = postcheck(inputs, Overrides(diversity_cap=1.0), plan)
    fixed = {v["entity"]: v["detail"] for v in rows if v["rule"] == "fixed_request"}
    assert fixed == {"F1": "requested HB/W1, planned HB/W2", "F3": "requested HA/W2, planned unplanted"}


def test_postcheck_skips_fixed_requests_when_disabled():
    inputs = tiny_inputs(fixed=[("F1", "HB", "W1")])
    plan = assignments([("F1", "HA", "W2"), ("F2", "HA", "W2"), ("F3", "HA", "W2"),
                        ("F4", "HA", "W2"), ("F5", "HA", "W2")])
    rows = postcheck(inputs, Overrides(diversity_cap=1.0, fixed_requests_enabled=False), plan)
    assert not [v for v in rows if v["rule"] == "fixed_request"]
