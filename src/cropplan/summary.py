"""Post-solve business-rule checks and KPI summaries."""

from __future__ import annotations

import pandas as pd

from cropplan.data import ScenarioInputs
from cropplan.overrides import Overrides
from cropplan.validate import Issue

def tolerance(limit: float) -> float:
    """Slack allowed before a rule counts as broken: 1e-6 of the limit, but never below 1e-3."""
    return max(1e-3, 1e-6 * abs(limit))


def postcheck(inputs: ScenarioInputs, overrides: Overrides, assignments: pd.DataFrame) -> list[dict]:
    """Re-verify the solution. Hard rows should never appear; penalized rows list unplanted fields."""
    rows: list[dict] = []
    fields = inputs.fields.set_index("field_id")
    hybrids = inputs.hybrids.set_index("hybrid_id")
    planted = assignments.dropna(subset=["hybrid_id"]).merge(
        fields[["region", "grower_id"]], left_on="field_id", right_index=True)

    def hard(rule: str, entity: str, detail: str) -> None:
        rows.append({"rule": rule, "entity": entity, "severity": "hard", "detail": detail})

    supply = inputs.seed_supply.set_index("hybrid_id")["units_available"]
    for h, acres in planted.groupby("hybrid_id")["acres"].sum().items():
        used = acres * hybrids.at[h, "units_per_acre"]
        limit = float(supply.get(h, 0.0)) * overrides.supply_multiplier(h)
        if used > limit + tolerance(limit):
            hard("supply", h, f"uses {used:,.0f} of {limit:,.0f} units")
    capacity = inputs.planting_capacity.set_index(["region", "window"])["acres_capacity"]
    for (r, w), acres in planted.groupby(["region", "window"])["acres"].sum().items():
        limit = float(capacity.get((r, w), 0.0)) * overrides.capacity_multiplier(r, w)
        if acres > limit + tolerance(limit):
            hard("capacity", f"{r}/{w}", f"plants {acres:,.0f} of {limit:,.0f} acres")
    grower_acres = inputs.fields.groupby("grower_id")["acres"].sum()
    for (g, h), acres in planted.groupby(["grower_id", "hybrid_id"])["acres"].sum().items():
        limit = overrides.diversity_cap * grower_acres[g]
        if acres > limit + tolerance(limit):
            hard("diversity", f"{g}/{h}", f"{acres:,.0f} acres exceeds cap")
    for r in assignments.itertuples():
        if r.hybrid_id and not (fields.at[r.field_id, "rm_min"] <= hybrids.at[r.hybrid_id, "relative_maturity"]
                                <= fields.at[r.field_id, "rm_max"]):
            hard("eligibility", r.field_id, f"{r.hybrid_id} outside maturity range")
    if overrides.fixed_requests_enabled:
        chosen = assignments.set_index("field_id")
        for req in inputs.fixed_requests.itertuples():
            if req.field_id not in chosen.index:
                continue  # field dropped (e.g. lost acreage); nothing to honor
            got_h, got_w = chosen.at[req.field_id, "hybrid_id"], chosen.at[req.field_id, "window"]
            want_w = req.window if isinstance(req.window, str) else None
            if got_h != req.hybrid_id or (want_w is not None and got_w != want_w):
                want = f"{req.hybrid_id}/{want_w or 'any window'}"
                got = f"{got_h}/{got_w}" if isinstance(got_h, str) else "unplanted"
                hard("fixed_request", req.field_id, f"requested {want}, planned {got}")
    for r in assignments[assignments["hybrid_id"].isna()].itertuples():
        penalty = r.acres * overrides.unplanted_penalty_per_acre
        rows.append({"rule": "unplanted", "entity": r.field_id, "severity": "penalized",
                     "detail": f"{r.acres:,.0f} acres unplanted; penalty ${penalty:,.0f}"})
    return rows


def summarize(inputs: ScenarioInputs, overrides: Overrides, assignments: pd.DataFrame,
              violations: list[dict]) -> tuple[dict, pd.DataFrame]:
    """Return (run_summary row, seed_utilization frame)."""
    total_acres = float(inputs.fields["acres"].sum())
    unplanted = assignments[assignments["hybrid_id"].isna()]
    planted_acres = total_acres - float(unplanted["acres"].sum())
    gross = float(assignments["exp_margin"].sum())
    penalty = float(unplanted["acres"].sum()) * overrides.unplanted_penalty_per_acre
    summary = {
        "acres_planted_pct": planted_acres / total_acres if total_acres else 0.0,
        "gross_margin": gross,
        "unplanted_penalty_total": penalty,
        "net_margin": gross - penalty,
        "unplanted_fields": int(len(unplanted)),
        "violations_count": sum(1 for v in violations if v["severity"] == "hard"),
    }
    hybrids = inputs.hybrids.set_index("hybrid_id")
    used = assignments.dropna(subset=["hybrid_id"]).groupby("hybrid_id")["acres"].sum()
    util_rows = []
    for s in inputs.seed_supply.itertuples():
        units_used = float(used.get(s.hybrid_id, 0.0)) * float(hybrids.at[s.hybrid_id, "units_per_acre"])
        available = float(s.units_available) * overrides.supply_multiplier(s.hybrid_id)
        util_rows.append({"hybrid_id": s.hybrid_id, "units_used": units_used, "units_available": available,
                          "pct": units_used / available if available > 0 else None})
    return summary, pd.DataFrame(util_rows)


def issues_to_rows(issues: list[Issue]) -> list[dict]:
    return [{"rule": i.rule, "entity": i.entity, "severity": i.severity, "detail": i.detail} for i in issues]
