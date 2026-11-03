"""Deterministic synthetic data for the demo and the three seeded scenarios."""

from __future__ import annotations

import numpy as np
import pandas as pd

from cropplan.data import WINDOWS, ScenarioInputs, empty_fixed_requests
from cropplan.overrides import Overrides

SEASON = 2027
FORECAST_MODEL_VERSION = "planting_window_model@v3"

# region -> (n_growers, lat range, lon range, base yield bu/ac, allowed RM range)
REGIONS = {
    "IA": (10, (41.0, 43.2), (-95.8, -91.2), 206.0, (98, 112)),
    "IL": (9, (39.0, 41.8), (-90.8, -88.0), 210.0, (104, 116)),
    "NE": (6, (40.2, 41.9), (-100.5, -96.2), 196.0, (110, 114)),
}
FIELDS_PER_GROWER = 6

# hybrid_id -> (relative maturity, seed cost per unit, disease tolerance, yield bonus bu/ac)
HYBRIDS = {
    "H-101": (98, 255.0, "medium", 0.0),
    "H-104": (102, 265.0, "high", 2.0),
    "H-108": (105, 280.0, "medium", 4.0),
    "H-112": (108, 310.0, "high", 14.0),
    "H-115": (110, 290.0, "medium", 5.0),
    "H-204": (112, 320.0, "high", 11.0),
    "H-209": (114, 295.0, "low", 6.0),
    "H-213": (116, 300.0, "medium", 3.0),
}
UNITS_PER_ACRE = 0.4
WINDOW_YIELD_FACTOR = {"W1": 1.00, "W2": 0.97, "W3": 0.90, "W4": 0.80}
WINDOW_CAPACITY_SHARE = {"W1": 0.25, "W2": 0.40, "W3": 0.35, "W4": 0.25}
SOIL_EFFECT = {"A": 10.0, "B": 0.0, "C": -12.0}
# Seed supply, as the share of all acres each hybrid could plant. Most hybrids are plentiful;
# H-112 (the high-yield favorite) is tight, and the NE-eligible hybrids H-115/H-204/H-209 together
# cover NE acres minus NE_SHORT_FIELDS average fields, so a few NE fields go unplanted.
PLENTIFUL_SHARE = 0.60
H112_SHARE = 0.12
NE_SHORT_FIELDS = 4
NE_SPLIT = {"H-115": 0.40, "H-204": 0.30, "H-209": 0.30}


def generate_inputs(seed: int = 2027) -> ScenarioInputs:
    rng = np.random.default_rng(seed)

    field_rows = []
    grower_no = 0
    for region, (n_growers, (lat0, lat1), (lon0, lon1), _, (rm_lo, rm_hi)) in REGIONS.items():
        for _ in range(n_growers):
            grower_no += 1
            g_lat, g_lon = rng.uniform(lat0, lat1), rng.uniform(lon0, lon1)
            for _ in range(FIELDS_PER_GROWER):
                field_rows.append({
                    "field_id": f"F-{len(field_rows) + 1:03d}",
                    "grower_id": f"G-{grower_no:02d}",
                    "region": region,
                    "acres": float(rng.integers(14, 21) * 10),  # 140-200 acres
                    "lat": round(float(np.clip(g_lat + rng.normal(0, 0.08), lat0, lat1)), 4),
                    "lon": round(float(np.clip(g_lon + rng.normal(0, 0.08), lon0, lon1)), 4),
                    "soil_class": str(rng.choice(["A", "B", "C"], p=[0.35, 0.45, 0.20])),
                    "rm_min": rm_lo,
                    "rm_max": rm_hi,
                })
    fields = pd.DataFrame(field_rows)

    hybrids = pd.DataFrame([
        {"hybrid_id": h, "relative_maturity": rm, "seed_cost_per_unit": cost,
         "units_per_acre": UNITS_PER_ACRE, "disease_tolerance": tol}
        for h, (rm, cost, tol, _) in HYBRIDS.items()
    ])

    total_acres = fields["acres"].sum()
    ne_acres = fields.loc[fields["region"] == "NE", "acres"]
    ne_supply_acres = ne_acres.sum() - NE_SHORT_FIELDS * ne_acres.mean()
    supply_acres = {h: PLENTIFUL_SHARE * total_acres for h in HYBRIDS}
    supply_acres["H-112"] = H112_SHARE * total_acres
    supply_acres.update({h: share * ne_supply_acres for h, share in NE_SPLIT.items()})
    seed_supply = pd.DataFrame([
        {"season": SEASON, "hybrid_id": h, "units_available": float(round(a * UNITS_PER_ACRE, -1))}
        for h, a in supply_acres.items()
    ])

    forecast_rows = []
    for region, (*_, base, _) in REGIONS.items():
        for soil, soil_fx in SOIL_EFFECT.items():
            for h, (rm, _, _, bonus) in HYBRIDS.items():
                for w in WINDOWS:
                    y = (base + soil_fx + bonus + 0.8 * (rm - 105)) * WINDOW_YIELD_FACTOR[w]
                    y = round(y * float(rng.uniform(0.98, 1.02)), 1)
                    forecast_rows.append({
                        "region": region, "soil_class": soil, "hybrid_id": h, "window": w,
                        "exp_yield_bu_ac": y, "yield_sd": round(0.08 * y, 1),
                        "source_model_version": FORECAST_MODEL_VERSION,
                    })
    yield_forecast = pd.DataFrame(forecast_rows)

    region_acres = fields.groupby("region")["acres"].sum()
    planting_capacity = pd.DataFrame([
        {"region": r, "window": w, "acres_capacity": float(round(region_acres[r] * share, -1))}
        for r in REGIONS for w, share in WINDOW_CAPACITY_SHARE.items()
    ])

    return ScenarioInputs(
        season=SEASON, fields=fields, hybrids=hybrids, seed_supply=seed_supply,
        yield_forecast=yield_forecast, planting_capacity=planting_capacity,
        fixed_requests=empty_fixed_requests(),
    )


def grower_commitments(inputs: ScenarioInputs) -> ScenarioInputs:
    """H-112 commitments pinned to IA/W1: within total H-112 supply, but over IA-W1 capacity.

    Up to two fields per IA grower, kept under 90% of each grower's diversity cap, so neither seed
    supply nor the diversity cap is what makes the plan infeasible.
    """
    defaults = Overrides()
    fields = inputs.fields
    grower_acres = fields.groupby("grower_id")["acres"].sum()
    cap = inputs.planting_capacity.query("region == 'IA' and window == 'W1'")["acres_capacity"].iloc[0]
    supply = inputs.seed_supply.query("hybrid_id == 'H-112'")["units_available"].iloc[0]
    max_acres_by_supply = 0.95 * supply / UNITS_PER_ACRE

    chosen, acres = [], 0.0
    for grower, group in fields[fields["region"] == "IA"].groupby("grower_id"):
        limit, used = 0.9 * defaults.diversity_cap * grower_acres[grower], 0.0
        for row in group.sort_values("acres").head(2).itertuples():
            if used + row.acres > limit or acres + row.acres > max_acres_by_supply:
                continue
            chosen.append(row.field_id)
            used += row.acres
            acres += row.acres
        if acres > cap * 1.10:
            break
    if acres <= cap:
        raise RuntimeError("generator could not build an over-capacity commitment set")
    fixed = pd.DataFrame({"field_id": chosen, "hybrid_id": "H-112", "window": "W1"})
    return inputs.with_fixed_requests(fixed)


SEEDED_SCENARIOS = {
    "baseline-2027": ("2027 Baseline", None),
    "grower-commitments-2027": ("2027 Grower Commitments", "baseline-2027"),
    "revision-1-2027": ("Revision 1", "baseline-2027"),
}


def seeded_scenarios(seed: int = 2027) -> dict[str, tuple[ScenarioInputs, Overrides]]:
    base = generate_inputs(seed)
    return {
        "baseline-2027": (base, Overrides()),
        "grower-commitments-2027": (grower_commitments(base), Overrides()),
        "revision-1-2027": (base, Overrides(supply_pct={"H-112": 1.10}, diversity_cap=0.45)),
    }
