"""Cheap pre-solve checks. Errors block the solve; warnings don't."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from cropplan.data import WINDOWS, ScenarioInputs
from cropplan.overrides import Overrides


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    rule: str
    entity: str
    detail: str


@dataclass(frozen=True)
class ValidationReport:
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _override_names(inputs: ScenarioInputs, overrides: Overrides) -> list[Issue]:
    issues = []
    hybrids = set(inputs.hybrids["hybrid_id"])
    regions = set(inputs.fields["region"])
    for h in overrides.supply_pct:
        if h not in hybrids:
            issues.append(Issue("error", "unknown_hybrid", h, f"supply_pct names unknown hybrid {h!r}"))
    for r, windows in overrides.capacity_pct.items():
        if r not in regions:
            issues.append(Issue("error", "unknown_region", r, f"capacity_pct names unknown region {r!r}"))
        for w in windows:
            if w not in WINDOWS:
                issues.append(Issue("error", "unknown_window", f"{r}/{w}", f"capacity_pct names unknown window {w!r}"))
    return issues


def _seed_supply(inputs: ScenarioInputs) -> list[Issue]:
    """One supply row per hybrid, for this scenario's season, naming only known hybrids."""
    issues = []
    supply = inputs.seed_supply
    hybrids = set(inputs.hybrids["hybrid_id"])
    other = supply[supply["season"] != inputs.season]
    if not other.empty:
        seasons = ", ".join(str(x) for x in sorted(other["season"].unique()))
        issues.append(Issue("error", "supply_season_mismatch", seasons,
                            f"seed_supply has rows for season(s) {seasons}; scenario season is {inputs.season}"))
    for h, n in supply["hybrid_id"].value_counts().items():
        if n > 1:
            issues.append(Issue("error", "duplicate_supply", h, f"seed_supply has {n} rows for {h}; expected 1"))
    for h in sorted(set(supply["hybrid_id"]) - hybrids):
        issues.append(Issue("error", "unknown_supply_hybrid", h, f"seed_supply names unknown hybrid {h!r}"))
    for h in sorted(hybrids - set(supply["hybrid_id"])):
        issues.append(Issue("warning", "missing_supply", h, f"no seed_supply row for {h}; treated as 0 units"))
    return issues


def _forecast_coverage(inputs: ScenarioInputs) -> list[Issue]:
    have = set(zip(inputs.yield_forecast["region"], inputs.yield_forecast["soil_class"],
                   inputs.yield_forecast["hybrid_id"], inputs.yield_forecast["window"]))
    fields = inputs.fields.set_index("field_id")
    missing = set()
    for f, h in inputs.eligible_pairs():
        r, s = fields.at[f, "region"], fields.at[f, "soil_class"]
        missing.update((r, s, h, w) for w in WINDOWS if (r, s, h, w) not in have)
    return [Issue("error", "missing_forecast", "/".join(k), f"no yield forecast for {'/'.join(k)}")
            for k in sorted(missing)]


def _eligibility(inputs: ScenarioInputs) -> list[Issue]:
    eligible_fields = {f for f, _ in inputs.eligible_pairs()}
    return [Issue("warning", "no_eligible_hybrid", f, "no hybrid matches this field's maturity range; it will be unplanted")
            for f in inputs.fields["field_id"] if f not in eligible_fields]


def _is_null(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NA


def _fixed_requests(inputs: ScenarioInputs, overrides: Overrides) -> list[Issue]:
    req = inputs.fixed_requests
    if not overrides.fixed_requests_enabled or req.empty:
        return []
    issues = []
    fields = inputs.fields.set_index("field_id")
    hybrids = inputs.hybrids.set_index("hybrid_id")
    pairs = set(inputs.eligible_pairs())

    known = req[req["field_id"].isin(fields.index) & req["hybrid_id"].isin(hybrids.index)]
    for r in req.drop(known.index).itertuples():
        issues.append(Issue("error", "unknown_fixed_request", r.field_id,
                            f"fixed request references unknown field or hybrid ({r.field_id}, {r.hybrid_id})"))
    for f, n in known["field_id"].value_counts().items():
        if n > 1:
            issues.append(Issue("error", "duplicate_fixed_request", f, f"{n} fixed requests for one field"))
    for r in known.itertuples():
        if (r.field_id, r.hybrid_id) not in pairs:
            issues.append(Issue("error", "fixed_request_ineligible", r.field_id,
                                f"{r.hybrid_id} maturity is outside {r.field_id}'s allowed range"))
        if isinstance(r.window, str):
            if r.window not in WINDOWS:
                issues.append(Issue("error", "unknown_window", r.field_id, f"unknown window {r.window!r}"))
        elif not _is_null(r.window):
            issues.append(Issue("error", "unknown_window", r.field_id,
                                f"window must be one of {', '.join(WINDOWS)} or empty, got {r.window!r}"))

    k = known.merge(fields[["acres", "region", "grower_id"]], left_on="field_id", right_index=True)
    k = k.merge(hybrids[["units_per_acre"]], left_on="hybrid_id", right_index=True)
    supply = inputs.seed_supply.set_index("hybrid_id")["units_available"]
    for h, units in (k["acres"] * k["units_per_acre"]).groupby(k["hybrid_id"]).sum().items():
        limit = float(supply.get(h, 0.0)) * overrides.supply_multiplier(h)
        if units > limit + 1e-6:
            issues.append(Issue("error", "fixed_exceeds_supply", h,
                                f"fixed requests need {units:,.0f} units of {h}; {limit:,.0f} available"))

    grower_acres = inputs.fields.groupby("grower_id")["acres"].sum()
    for (g, h), acres in k.groupby(["grower_id", "hybrid_id"])["acres"].sum().items():
        limit = overrides.diversity_cap * grower_acres[g]
        if acres > limit + 1e-6:
            issues.append(Issue("error", "fixed_exceeds_diversity", f"{g}/{h}",
                                f"fixed {h} acres for {g} ({acres:,.0f}) exceed the diversity cap ({limit:,.0f})"))

    capacity = inputs.planting_capacity.set_index(["region", "window"])["acres_capacity"]
    windowed = k[k["window"].isin(WINDOWS)]
    for (r, w), acres in windowed.groupby(["region", "window"])["acres"].sum().items():
        limit = float(capacity.get((r, w), 0.0)) * overrides.capacity_multiplier(r, w)
        if acres > limit + 1e-6:
            issues.append(Issue("warning", "capacity_below_fixed", f"{r}/{w}",
                                f"fixed acres in {r}/{w} ({acres:,.0f}) exceed planting capacity ({limit:,.0f})"))
    return issues


def validate(inputs: ScenarioInputs, overrides: Overrides) -> ValidationReport:
    issues = (_override_names(inputs, overrides) + _seed_supply(inputs) + _forecast_coverage(inputs)
              + _eligibility(inputs) + _fixed_requests(inputs, overrides))
    return ValidationReport(issues)
