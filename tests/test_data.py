import pandas as pd
import pytest

from cropplan.data import ScenarioInputs


def test_eligible_pairs_respect_maturity_range(tiny):
    assert len(tiny.eligible_pairs()) == 10  # 5 fields x 2 hybrids, all in range
    fields = tiny.fields.copy()
    fields.loc[fields["field_id"] == "F1", "rm_max"] = 102
    pairs = ScenarioInputs(tiny.season, fields, tiny.hybrids, tiny.seed_supply, tiny.yield_forecast,
                           tiny.planting_capacity, tiny.fixed_requests).eligible_pairs()
    assert ("F1", "HB") not in pairs and ("F1", "HA") in pairs


def test_missing_columns_rejected(tiny):
    with pytest.raises(ValueError, match="fields is missing columns"):
        ScenarioInputs(tiny.season, tiny.fields.drop(columns=["acres"]), tiny.hybrids, tiny.seed_supply,
                       tiny.yield_forecast, tiny.planting_capacity, tiny.fixed_requests)


def test_with_fields_drops_orphan_fixed_requests():
    from conftest import tiny_inputs
    inputs = tiny_inputs(fixed=[("F1", "HA", None), ("F2", "HA", None)])
    out = inputs.with_fields(inputs.fields[inputs.fields["field_id"] != "F1"])
    assert list(out.fixed_requests["field_id"]) == ["F2"]
