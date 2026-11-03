"""Contracts between the Python solver package and the Crop Plan Studio app (app/).

The app's overrides parser and validation panel are TypeScript ports of cropplan.overrides and
cropplan.validate. This module writes the fixtures the app's vitest suite replays against the ports, and
fails when the checked-in fixtures are stale. Regenerate with:  UPDATE_PARITY=1 uv run pytest tests/test_app_parity.py
"""

import json
import math
import os
from pathlib import Path

import pandas as pd
import pytest

from cropplan.data import ScenarioInputs
from cropplan.generate import seeded_scenarios
from cropplan.overrides import OverridesError, parse_overrides
from cropplan.validate import validate
from cropplan_jobs.tables import INPUTS, OUTPUTS

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
PARITY = APP / "shared" / "studio" / "parity"

OVERRIDES_PAYLOADS = [
    None, {}, {"supply_pct": {"H-112": 1.1}, "diversity_cap": 0.45},
    {"capacity_pct": {"IA": {"W1": 0.5}}}, {"supply_pct": {"H-112": 0}}, {"supply_pct": {"H-112": 3}},
    {"supply_pct": {"H-112": 3.5}}, {"supply_pct": {"H-112": "1.1"}}, {"supply_pct": {"H-112": True}},
    {"supply_pct": [1.1]}, {"capacity_pct": {"IA": 0.5}}, {"capacity_pct": {"IA": {"W1": -0.1}}},
    {"diversity_cap": 0}, {"diversity_cap": 1}, {"diversity_cap": "0.4"}, {"diversity_cap": None},
    {"unplanted_penalty_per_acre": -1}, {"corn_price_per_bu": 0}, {"solver": "cplex"}, {"solver": "gurobi"},
    {"time_limit_s": 0}, {"time_limit_s": 30.5}, {"time_limit_s": 3600}, {"mip_rel_gap": 0.06},
    {"threads": None}, {"threads": 0}, {"random_seed": None}, {"random_seed": 1.5},
    {"fixed_requests_enabled": "yes"}, {"fixed_requests_enabled": False}, {"bogus": 1, "also": 2},
]


def _path(message: str) -> str:
    """The key path cropplan puts first in every OverridesError message ("supply_pct.H-112 must be ...")."""
    return message.split(" must")[0] if " must" in message else message.split(":")[0]


def overrides_cases() -> list[dict]:
    cases = []
    for payload in OVERRIDES_PAYLOADS:
        try:
            cases.append({"payload": payload, "ok": True, "overrides": parse_overrides(payload).to_dict()})
        except OverridesError as exc:
            cases.append({"payload": payload, "ok": False, "path": _path(str(exc)), "message": str(exc)})
    return cases


def _check_or_write(name: str, data) -> None:
    path = PARITY / name
    text = json.dumps(data, indent=1, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_PARITY") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert path.exists() and path.read_text() == text, (
        f"{path.relative_to(ROOT)} is stale: run UPDATE_PARITY=1 uv run pytest tests/test_app_parity.py")


def test_overrides_fixture_is_current():
    _check_or_write("overrides_cases.json", overrides_cases())


def table_contract() -> dict:
    """Column lists the app's SQL writes depend on (scenario clone copies every input column)."""
    return {"inputs": {t: [c for c in cols if c != "scenario_id"] for t, cols in INPUTS.items()},
            "scenarios": list(OUTPUTS["scenarios"]), "runs": list(OUTPUTS["runs"])}


def test_table_contract_is_current():
    _check_or_write("table_contract.json", table_contract())


def _records(frame: pd.DataFrame, cols: list[str]) -> list[dict]:
    out = []
    for row in frame[cols].to_dict("records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                v = None
            elif hasattr(v, "item"):
                v = v.item()
            clean[k] = v
        out.append(clean)
    return out


def inputs_json(inputs: ScenarioInputs) -> dict:
    return {
        "season": int(inputs.season),
        "fields": _records(inputs.fields, ["field_id", "grower_id", "region", "acres", "lat", "lon", "soil_class",
                                           "rm_min", "rm_max"]),
        "hybrids": _records(inputs.hybrids, ["hybrid_id", "relative_maturity", "units_per_acre"]),
        "seed_supply": _records(inputs.seed_supply, ["season", "hybrid_id", "units_available"]),
        "yield_forecast": _records(inputs.yield_forecast, ["region", "soil_class", "hybrid_id", "window"]),
        "planting_capacity": _records(inputs.planting_capacity, ["region", "window", "acres_capacity"]),
        "fixed_requests": _records(inputs.fixed_requests, ["field_id", "hybrid_id", "window"]),
    }


def _broken(base: ScenarioInputs) -> ScenarioInputs:
    """One input set that trips every data check cropplan.validate has."""
    fields = base.fields.copy()
    fields.loc[fields["field_id"] == "F-001", ["rm_min", "rm_max"]] = [80, 85]  # no eligible hybrid
    forecast = base.yield_forecast[~((base.yield_forecast["region"] == "IL") & (base.yield_forecast["window"] == "W4")
                                     & (base.yield_forecast["hybrid_id"] == "H-213"))]
    supply = pd.concat([base.seed_supply[base.seed_supply["hybrid_id"] != "H-101"],
                        pd.DataFrame([{"season": 2026, "hybrid_id": "H-104", "units_available": 10.0},
                                      {"season": 2027, "hybrid_id": "H-999", "units_available": 10.0}])],
                       ignore_index=True)
    ia = fields[fields["region"] == "IA"]["field_id"].tolist()
    ne = fields[fields["region"] == "NE"]["field_id"].tolist()
    fixed = pd.DataFrame([
        {"field_id": "F-999", "hybrid_id": "H-112", "window": "W1"},   # unknown field
        {"field_id": ia[1], "hybrid_id": "H-112", "window": "W1"},     # duplicate (with the next row)
        {"field_id": ia[1], "hybrid_id": "H-112", "window": "W2"},
        {"field_id": ne[0], "hybrid_id": "H-101", "window": None},     # ineligible: NE allows RM 110-114
        {"field_id": ia[2], "hybrid_id": "H-112", "window": "W9"},     # unknown window
    ])
    return ScenarioInputs(base.season, fields, base.hybrids, supply, forecast, base.planting_capacity, fixed)


def validation_cases() -> dict:
    seeded = seeded_scenarios()
    sets = {"baseline": seeded["baseline-2027"][0], "commitments": seeded["grower-commitments-2027"][0]}
    sets["broken"] = _broken(sets["baseline"])
    cases = [
        ("baseline", {}), ("baseline", {"supply_pct": {"H-112": 1.1}, "diversity_cap": 0.45}),
        ("commitments", {}), ("commitments", {"fixed_requests_enabled": False}),
        ("commitments", {"supply_pct": {"H-112": 0.5}}), ("commitments", {"diversity_cap": 0.1}),
        ("commitments", {"capacity_pct": {"IA": {"W1": 2.0}}}),
        ("baseline", {"supply_pct": {"H-999": 1.1}, "capacity_pct": {"XX": {"W1": 0.5}, "IA": {"W9": 1.0}}}),
        ("broken", {}),
    ]
    out = []
    for name, payload in cases:
        issues = validate(sets[name], parse_overrides(payload)).issues
        out.append({"inputs": name, "overrides": payload,
                    "issues": [{"severity": i.severity, "rule": i.rule, "entity": i.entity, "detail": i.detail}
                               for i in issues]})
    return {"inputs": {k: inputs_json(v) for k, v in sets.items()}, "cases": out}


def test_validation_fixture_is_current():
    _check_or_write("validation_cases.json", validation_cases())


def test_validation_fixture_exercises_every_rule():
    rules = {i["rule"] for c in validation_cases()["cases"] for i in c["issues"]}
    assert rules >= {"unknown_hybrid", "unknown_region", "unknown_window", "supply_season_mismatch",
                     "duplicate_supply", "unknown_supply_hybrid", "missing_supply", "missing_forecast",
                     "no_eligible_hybrid", "unknown_fixed_request", "duplicate_fixed_request",
                     "fixed_request_ineligible", "fixed_exceeds_supply", "fixed_exceeds_diversity",
                     "capacity_below_fixed"}
