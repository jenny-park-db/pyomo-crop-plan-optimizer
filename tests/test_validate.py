import pandas as pd
from dataclasses import replace

from cropplan.overrides import Overrides
from cropplan.validate import validate
from conftest import tiny_inputs

O = Overrides(diversity_cap=1.0)


def rules(report, severity):
    return {i.rule for i in report.issues if i.severity == severity}


def test_clean_inputs_pass(tiny):
    report = validate(tiny, O)
    assert report.ok and not report.issues


def test_unknown_override_names_are_errors(tiny):
    o = replace(O, supply_pct={"H112": 1.1}, capacity_pct={"ZZ": {"W1": 0.5}, "R1": {"W9": 0.5}})
    assert {"unknown_hybrid", "unknown_region", "unknown_window"} <= rules(validate(tiny, o), "error")


def test_fixed_requests_over_supply_are_invalid():
    inputs = tiny_inputs(fixed=[("F1", "HB", None), ("F2", "HB", None), ("F3", "HB", None)])  # 300 > 200
    report = validate(inputs, O)
    assert not report.ok
    assert "fixed_exceeds_supply" in rules(report, "error")


def test_fixed_requests_over_diversity_cap_are_invalid():
    inputs = tiny_inputs(fixed=[("F1", "HA", None), ("F2", "HA", None)])  # G1: 200 of 300 acres
    assert "fixed_exceeds_diversity" in rules(validate(inputs, replace(O, diversity_cap=0.5)), "error")


def test_fixed_over_capacity_is_only_a_warning():
    inputs = tiny_inputs(fixed=[(f"F{i}", "HA", "W1") for i in range(1, 5)])
    report = validate(inputs, O)
    assert report.ok
    assert rules(report, "warning") == {"capacity_below_fixed"}


def test_ineligible_unknown_and_duplicate_fixed_requests(tiny):
    fields = tiny.fields.copy()
    fields.loc[fields["field_id"] == "F5", ["rm_min", "rm_max"]] = [95, 102]  # HB (105) not allowed
    inputs = replace(tiny, fields=fields).with_fixed_requests(
        tiny_inputs(fixed=[("F5", "HB", None), ("F9", "HA", None), ("F1", "HA", "W1"), ("F1", "HA", "W2")]
                    ).fixed_requests)
    errors = rules(validate(inputs, O), "error")
    assert {"fixed_request_ineligible", "unknown_fixed_request", "duplicate_fixed_request"} <= errors


def test_missing_forecast_is_error(tiny):
    yf = tiny.yield_forecast[~((tiny.yield_forecast["hybrid_id"] == "HB") & (tiny.yield_forecast["window"] == "W3"))]
    assert "missing_forecast" in rules(validate(replace(tiny, yield_forecast=yf), O), "error")


def test_field_without_eligible_hybrid_is_warning(tiny):
    fields = tiny.fields.copy()
    fields.loc[fields["field_id"] == "F5", ["rm_min", "rm_max"]] = [120, 125]
    report = validate(replace(tiny, fields=fields), O)
    assert report.ok
    assert "no_eligible_hybrid" in rules(report, "warning")


def test_duplicate_supply_rows_are_invalid(tiny):
    extra = tiny.seed_supply.assign(season=2026)  # a second season's rows for the same hybrids
    supply = pd.concat([tiny.seed_supply, extra], ignore_index=True)
    report = validate(replace(tiny, seed_supply=supply), O)
    assert "duplicate_supply" in rules(report, "error")


def test_supply_for_unknown_hybrid_is_invalid(tiny):
    supply = pd.concat([tiny.seed_supply, pd.DataFrame([{"season": 2027, "hybrid_id": "H-999",
                                                          "units_available": 10.0}])], ignore_index=True)
    assert "unknown_supply_hybrid" in rules(validate(replace(tiny, seed_supply=supply), O), "error")


def test_supply_for_other_season_only_is_invalid(tiny):
    report = validate(replace(tiny, seed_supply=tiny.seed_supply.assign(season=2026)), O)
    assert "supply_season_mismatch" in rules(report, "error")


def test_hybrid_without_supply_is_a_warning(tiny):
    supply = tiny.seed_supply[tiny.seed_supply["hybrid_id"] != "HB"]
    report = validate(replace(tiny, seed_supply=supply), O)
    assert report.ok and "missing_supply" in rules(report, "warning")


def test_non_string_fixed_request_window_is_invalid(tiny):
    fixed = pd.DataFrame({"field_id": ["F1", "F2", "F3"], "hybrid_id": ["HA", "HA", "HA"],
                          "window": [1, None, float("nan")]}, dtype=object)
    report = validate(tiny.with_fixed_requests(fixed), O)
    bad = [i for i in report.errors if i.rule == "unknown_window"]
    assert [(i.entity, i.detail) for i in bad] == [("F1", "window must be one of W1, W2, W3, W4 or empty, got 1")]
