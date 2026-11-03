"""Seeded disruption sampling for stress tests, and percentile summaries of the results."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from cropplan.data import WINDOWS, ScenarioInputs
from cropplan.overrides import Overrides

KINDS = ("seed_shortfall", "lost_capacity", "lost_acreage")


def sample_disruptions(inputs: ScenarioInputs, n: int, seed: int = 2027) -> list[dict]:
    rng = np.random.default_rng(seed)
    hybrids = sorted(inputs.hybrids["hybrid_id"])
    regions = sorted(inputs.fields["region"].unique())
    out = []
    for i in range(n):
        kind = KINDS[int(rng.integers(len(KINDS)))]
        if kind == "seed_shortfall":
            d = {"kind": kind, "hybrid_id": hybrids[int(rng.integers(len(hybrids)))],
                 "multiplier": round(float(rng.uniform(0.6, 0.9)), 3)}
        elif kind == "lost_capacity":
            d = {"kind": kind, "region": regions[int(rng.integers(len(regions)))],
                 "window": WINDOWS[int(rng.integers(len(WINDOWS)))],
                 "multiplier": round(float(rng.uniform(0.3, 0.8)), 3)}
        else:
            d = {"kind": kind, "region": regions[int(rng.integers(len(regions)))],
                 "fraction": round(float(rng.uniform(0.05, 0.20)), 3), "seed": int(rng.integers(1_000_000))}
        out.append({"sample_id": i, **d})
    return out


def apply_disruption(inputs: ScenarioInputs, overrides: Overrides, d: dict) -> tuple[ScenarioInputs, Overrides]:
    """Return disrupted copies; multipliers compound with the scenario's own overrides."""
    if d["kind"] == "seed_shortfall":
        h = d["hybrid_id"]
        supply = {**overrides.supply_pct, h: overrides.supply_multiplier(h) * d["multiplier"]}
        return inputs, replace(overrides, supply_pct=supply)
    if d["kind"] == "lost_capacity":
        r, w = d["region"], d["window"]
        region = {**overrides.capacity_pct.get(r, {}), w: overrides.capacity_multiplier(r, w) * d["multiplier"]}
        return inputs, replace(overrides, capacity_pct={**overrides.capacity_pct, r: region})
    if d["kind"] == "lost_acreage":
        region_fields = inputs.fields[inputs.fields["region"] == d["region"]]
        n_lost = max(1, int(round(len(region_fields) * d["fraction"])))
        lost = region_fields.sample(n=n_lost, random_state=d["seed"])["field_id"]
        return inputs.with_fields(inputs.fields[~inputs.fields["field_id"].isin(lost)]), overrides
    raise ValueError(f"unknown disruption kind {d['kind']!r}")


def summarize_stress(results: pd.DataFrame, base_unplanted: set[str], top: int = 10) -> dict:
    """Percentiles over samples that solved; invalid/infeasible/failed samples are counted, not dropped silently.

    ``results`` columns: sample_id, kind, hybrid_id (nullable), status, gross_margin, unplanted_field_ids (list).
    Fragile fields: most often newly unplanted vs. the base plan. Fragile hybrids: largest median margin
    loss when that hybrid's seed falls short.
    """
    ok = results[results["status"] == "done"]
    margins = ok["gross_margin"].to_numpy()
    p10, p50, p90 = (np.percentile(margins, [10, 50, 90]).tolist() if len(margins) else (None, None, None))
    return {
        "n": int(len(results)),
        "n_solved": int(len(ok)),
        "n_invalid": int((results["status"] == "invalid").sum()),
        "n_infeasible": int((results["status"] == "infeasible").sum()),
        "n_failed": int((~results["status"].isin(["done", "invalid", "infeasible"])).sum()),
        "p10_gross_margin": p10,
        "p50_gross_margin": p50,
        "p90_gross_margin": p90,
        "fragile_fields": _fragile_fields(ok, base_unplanted, top),
        "fragile_hybrids": _fragile_hybrids(ok, top),
    }


def _fragile_fields(ok: pd.DataFrame, base_unplanted: set[str], top: int) -> list[str]:
    counts: dict[str, int] = {}
    for ids in ok["unplanted_field_ids"]:
        for f in set(ids) - base_unplanted:
            counts[f] = counts.get(f, 0) + 1
    return [f for f, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]


def _fragile_hybrids(ok: pd.DataFrame, top: int) -> list[str]:
    short = ok[ok["kind"] == "seed_shortfall"]
    if short.empty:
        return []
    median = short.groupby("hybrid_id")["gross_margin"].median().sort_values()
    return list(median.index[:top])
