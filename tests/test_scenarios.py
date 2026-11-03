import json

import pandas as pd
import pytest

from cropplan.overrides import Overrides, OverridesError
from cropplan_jobs.scenarios import ScenarioNotFound, clone_scenario, load_scenario, seed_scenarios, write_scenario
from cropplan_jobs.store import MemoryStore
from conftest import tiny_inputs


def _store_with(inputs, overrides=Overrides(), scenario_id="s1"):
    store = MemoryStore()
    write_scenario(store, scenario_id, "S1", inputs, overrides, parent_scenario_id=None,
                   created_by="planner@example.com", source="app")
    return store


def test_round_trip_keeps_inputs_and_raw_overrides():
    inputs = tiny_inputs(fixed=[("F1", "HA", "W1"), ("F2", "HB", None)])
    store = _store_with(inputs, Overrides(diversity_cap=0.5, supply_pct={"HA": 1.1}))
    row, loaded, payload = load_scenario(store, "s1")
    assert row["created_by"] == "planner@example.com" and row["source"] == "app" and row["season"] == 2027
    assert payload["diversity_cap"] == 0.5 and payload["supply_pct"] == {"HA": 1.1}
    pd.testing.assert_frame_equal(loaded.fields, inputs.fields, check_dtype=False)
    assert loaded.fixed_requests["window"].tolist() == ["W1", None]


def test_load_sorts_rows_so_storage_order_does_not_matter():
    store = _store_with(tiny_inputs())
    shuffled = store.frames["fields"].sample(frac=1.0, random_state=3).reset_index(drop=True)
    store.frames["fields"] = shuffled
    _, loaded, _ = load_scenario(store, "s1")
    assert loaded.fields["field_id"].tolist() == ["F1", "F2", "F3", "F4", "F5"]


def test_missing_scenario_raises():
    with pytest.raises(ScenarioNotFound):
        load_scenario(MemoryStore(), "nope")


def test_clone_copies_inputs_under_the_new_id():
    store = _store_with(tiny_inputs())
    parsed = clone_scenario(store, "s1", "s2", "S2", {"diversity_cap": 0.45}, created_by="agent@example.com",
                            source="agent")
    assert parsed.diversity_cap == 0.45
    assert len(store.read("fields", scenario_id="s2")) == 5 and len(store.read("fields", scenario_id="s1")) == 5
    row = store.read("scenarios", scenario_id="s2").iloc[0]
    assert (row["parent_scenario_id"], row["source"]) == ("s1", "agent")
    assert json.loads(row["overrides"])["diversity_cap"] == 0.45


def test_clone_with_bad_overrides_or_existing_id_writes_nothing():
    store = _store_with(tiny_inputs())
    with pytest.raises(OverridesError):
        clone_scenario(store, "s1", "s2", "S2", {"diversity_cap": 7}, created_by="x", source="app")
    with pytest.raises(ValueError, match="already exists"):
        clone_scenario(store, "s1", "s1", "S1 again", {}, created_by="x", source="app")
    assert store.read("scenarios", scenario_id="s2").empty and store.read("fields", scenario_id="s2").empty


def test_seed_writes_the_three_fixed_scenarios_and_is_rerunnable():
    store = MemoryStore()
    for _ in range(2):
        ids = seed_scenarios(store, created_by="seed@example.com")
    assert ids == ["baseline-2027", "grower-commitments-2027", "revision-1-2027"]
    scenarios = store.read("scenarios").set_index("scenario_id")
    assert len(scenarios) == 3 and set(scenarios["source"]) == {"seed"}
    assert scenarios.at["revision-1-2027", "parent_scenario_id"] == "baseline-2027"
    assert len(store.read("fields")) == 3 * 150
    assert len(store.read("fixed_requests", scenario_id="grower-commitments-2027")) > 0
