import json

import pandas as pd
import pytest

from cropplan.overrides import Overrides
from cropplan_jobs import stress
from cropplan_jobs.scenarios import write_scenario
from cropplan_jobs.store import MemoryStore
from cropplan_jobs.stress import (load_stress, prepare_stress, read_prepared, run_dir, run_stress, solve_sample,
                                  stress_settings, write_results)
from conftest import tiny_inputs

O = Overrides(diversity_cap=1.0, corn_price_per_bu=1.0)


def _store():
    store = MemoryStore()
    write_scenario(store, "s1", "S1", tiny_inputs(fixed=[("F5", "HA", None)]), O, parent_scenario_id=None,
                   created_by="planner@example.com", source="app")
    return store


def test_stress_settings_loosen_gap_and_time_only():
    s = stress_settings(O)
    assert (s.mip_rel_gap, s.time_limit_s) == (0.01, 30)
    assert (s.diversity_cap, s.threads, s.random_seed) == (O.diversity_cap, O.threads, O.random_seed)


def test_prepare_then_read_round_trips_through_the_volume(tmp_path):
    m = prepare_stress(_store(), str(tmp_path), scenario_id="s1", n=6, seed=7, stress_id="", job_run_id="42",
                       triggered_by="planner@example.com")
    assert m["stress_id"] == "stress-42" and (m["n"], m["seed"]) == (6, 7)
    manifest, inputs, overrides = read_prepared(run_dir(str(tmp_path), "42"))
    assert manifest == m and len(inputs.fields) == 5 and overrides.mip_rel_gap == 0.01
    assert inputs.fixed_requests["window"].tolist() == [None]


@pytest.mark.parametrize("n", [0, 5001])
def test_prepare_rejects_out_of_range_n(tmp_path, n):
    with pytest.raises(ValueError, match="n must be"):
        prepare_stress(_store(), str(tmp_path), scenario_id="s1", n=n, seed=1, stress_id="x", job_run_id="1",
                       triggered_by="")


def test_a_crashing_sample_is_failed_not_fatal(monkeypatch):
    monkeypatch.setattr(stress, "run_pipeline", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("bad")))
    row = solve_sample(tiny_inputs(), O, {"sample_id": 3, "kind": "seed_shortfall", "hybrid_id": "HA",
                                          "multiplier": 0.5})
    assert (row["sample_id"], row["status"], row["error"]) == (3, "failed", "RuntimeError: bad")


def test_run_stress_is_seeded_and_summarized():
    inputs = tiny_inputs()
    results, summary = run_stress(inputs, stress_settings(O), n=6, seed=11)
    again, _ = run_stress(inputs, stress_settings(O), n=6, seed=11)
    assert results["sample_id"].tolist() == list(range(6)) and summary["n"] == 6
    assert results["disruption"].tolist() == again["disruption"].tolist()
    assert summary["n_solved"] + summary["n_invalid"] + summary["n_infeasible"] + summary["n_failed"] == 6


def test_load_writes_results_and_one_summary_row_idempotently(tmp_path):
    store = _store()
    prepare_stress(store, str(tmp_path), scenario_id="s1", n=4, seed=5, stress_id="st-1", job_run_id="42",
                   triggered_by="planner@example.com")
    directory = run_dir(str(tmp_path), "42")
    manifest, inputs, overrides = read_prepared(directory)
    results, summary = run_stress(inputs, overrides, manifest["n"], manifest["seed"])
    write_results(directory, results, summary, mlflow_run_id="m-7")
    for _ in range(2):
        row = load_stress(store, directory)
    assert len(store.read("stress_test_results", stress_id="st-1")) == 4
    s = store.read("stress_test_summary", stress_id="st-1")
    assert len(s) == 1 and s.iloc[0]["mlflow_run_id"] == "m-7" and s.iloc[0]["triggered_by"] == "planner@example.com"
    assert row["n"] == 4 and json.loads(store.read("stress_test_results").iloc[0]["disruption"])["sample_id"] == 0
