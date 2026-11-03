"""Pyomo hybrid-to-field MIP."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pyomo.environ as pe

from cropplan.data import WINDOWS, ScenarioInputs
from cropplan.overrides import Overrides

# Constraint families that diagnosis may relax. Field assignment and fixed requests are never relaxed:
# fixed requests are the planner's givens, so diagnosis explains which resource they collide with.
RELAXABLE = ("supply", "capacity", "diversity")


@dataclass
class BuiltModel:
    model: pe.ConcreteModel
    fhw: list[tuple[str, str, str]]
    margin: dict[tuple[str, str, str], float]
    relaxed: bool
    fixed_fields: frozenset[str] = frozenset()  # fields whose fixed request is enforced in this model


def _margin_coefficients(inputs: ScenarioInputs, overrides: Overrides) -> dict[tuple[str, str, str], float]:
    fields = inputs.fields.set_index("field_id")
    hybrids = inputs.hybrids.set_index("hybrid_id")
    yld = inputs.yield_forecast.set_index(["region", "soil_class", "hybrid_id", "window"])["exp_yield_bu_ac"]
    coef = {}
    for f, h in inputs.eligible_pairs():
        fr, hr = fields.loc[f], hybrids.loc[h]
        seed_cost = hr["units_per_acre"] * hr["seed_cost_per_unit"]
        for w in WINDOWS:
            y = float(yld.loc[(fr["region"], fr["soil_class"], h, w)])
            coef[(f, h, w)] = float(fr["acres"]) * (y * overrides.corn_price_per_bu - seed_cost)
    return coef


def build_model(inputs: ScenarioInputs, overrides: Overrides, relax: bool = False) -> BuiltModel:
    """Build the MIP. With ``relax=True`` resource constraints get slack and the objective minimizes it."""
    fields = inputs.fields.set_index("field_id")
    hybrids = inputs.hybrids.set_index("hybrid_id")
    supply = inputs.seed_supply.set_index("hybrid_id")["units_available"]
    capacity = inputs.planting_capacity.set_index(["region", "window"])["acres_capacity"]
    grower_acres = inputs.fields.groupby("grower_id")["acres"].sum()

    margin = _margin_coefficients(inputs, overrides)
    fhw = sorted(margin)
    acres = fields["acres"].to_dict()
    upa = hybrids["units_per_acre"].to_dict()

    m = pe.ConcreteModel("crop_plan")
    m.FHW = pe.Set(initialize=fhw, dimen=3)
    m.F = pe.Set(initialize=list(fields.index))
    m.x = pe.Var(m.FHW, domain=pe.Binary)
    m.u = pe.Var(m.F, domain=pe.Binary)

    by_field: dict[str, list] = {f: [] for f in fields.index}
    by_hybrid: dict[str, list] = {h: [] for h in hybrids.index}
    by_region_window: dict[tuple[str, str], list] = {}
    by_grower_hybrid: dict[tuple[str, str], list] = {}
    for f, h, w in fhw:
        by_field[f].append((f, h, w))
        by_hybrid[h].append((f, h, w))
        by_region_window.setdefault((fields.at[f, "region"], w), []).append((f, h, w))
        by_grower_hybrid.setdefault((fields.at[f, "grower_id"], h), []).append((f, h, w))

    m.assign = pe.Constraint(m.F, rule=lambda m, f: sum(m.x[i] for i in by_field[f]) + m.u[f] == 1)

    hyb_keys = [h for h in hybrids.index if by_hybrid[h]]
    rw_keys = sorted(by_region_window)
    gh_keys = sorted(by_grower_hybrid)
    if relax:
        m.s_supply = pe.Var(hyb_keys, domain=pe.NonNegativeReals)
        m.s_capacity = pe.Var(rw_keys, domain=pe.NonNegativeReals)
        m.s_diversity = pe.Var(gh_keys, domain=pe.NonNegativeReals)

    def supply_rule(m, h):
        used = sum(acres[f] * upa[h] * m.x[(f, h, w)] for f, _, w in by_hybrid[h])
        limit = float(supply.get(h, 0.0)) * overrides.supply_multiplier(h)
        return used <= limit + (m.s_supply[h] if relax else 0)

    def capacity_rule(m, r, w):
        used = sum(acres[f] * m.x[i] for i in by_region_window[(r, w)] for f in [i[0]])
        limit = float(capacity.get((r, w), 0.0)) * overrides.capacity_multiplier(r, w)
        return used <= limit + (m.s_capacity[(r, w)] if relax else 0)

    def diversity_rule(m, g, h):
        used = sum(acres[i[0]] * m.x[i] for i in by_grower_hybrid[(g, h)])
        limit = overrides.diversity_cap * float(grower_acres[g])
        return used <= limit + (m.s_diversity[(g, h)] if relax else 0)

    m.supply = pe.Constraint(hyb_keys, rule=supply_rule)
    m.capacity = pe.Constraint(rw_keys, rule=capacity_rule)
    m.diversity = pe.Constraint(gh_keys, rule=diversity_rule)

    m.fixed = pe.ConstraintList()
    fixed_fields: set[str] = set()
    if overrides.fixed_requests_enabled:
        for req in inputs.fixed_requests.itertuples():
            window = req.window if isinstance(req.window, str) and req.window else None
            keys = [(req.field_id, req.hybrid_id, window)] if window else [
                (req.field_id, req.hybrid_id, w) for w in WINDOWS
            ]
            m.fixed.add(sum(m.x[k] for k in keys) == 1)
            fixed_fields.add(req.field_id)

    if relax:
        # Normalize so one seed unit, one capacity acre, and one diversity acre weigh the same.
        m.obj = pe.Objective(
            expr=sum(m.s_supply[h] / upa[h] for h in hyb_keys)
            + sum(m.s_capacity.values()) + sum(m.s_diversity.values()),
            sense=pe.minimize,
        )
    else:
        penalty = {f: acres[f] * overrides.unplanted_penalty_per_acre for f in fields.index}
        m.obj = pe.Objective(
            expr=sum(margin[i] * m.x[i] for i in fhw) - sum(penalty[f] * m.u[f] for f in fields.index),
            sense=pe.maximize,
        )
    return BuiltModel(model=m, fhw=fhw, margin=margin, relaxed=relax, fixed_fields=frozenset(fixed_fields))


def extract_assignments(built: BuiltModel, inputs: ScenarioInputs) -> pd.DataFrame:
    """One row per field: chosen hybrid/window (or None if unplanted)."""
    m = built.model
    chosen = {f: (h, w) for (f, h, w) in built.fhw if pe.value(m.x[(f, h, w)]) > 0.5}
    yld = inputs.yield_forecast.set_index(["region", "soil_class", "hybrid_id", "window"])["exp_yield_bu_ac"]
    rows = []
    for fr in inputs.fields.itertuples():
        h, w = chosen.get(fr.field_id, (None, None))
        rows.append({
            "field_id": fr.field_id,
            "hybrid_id": h,
            "window": w,
            "acres": float(fr.acres),
            "exp_yield": float(yld.loc[(fr.region, fr.soil_class, h, w)]) if h else 0.0,
            "exp_margin": built.margin[(fr.field_id, h, w)] if h else 0.0,
            "is_fixed": fr.field_id in built.fixed_fields,
        })
    return pd.DataFrame(rows)
