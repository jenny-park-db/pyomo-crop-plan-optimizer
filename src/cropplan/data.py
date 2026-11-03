"""Typed container for one scenario's input tables."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

WINDOWS = ("W1", "W2", "W3", "W4")

COLUMNS: dict[str, list[str]] = {
    "fields": ["field_id", "grower_id", "region", "acres", "lat", "lon", "soil_class", "rm_min", "rm_max"],
    "hybrids": ["hybrid_id", "relative_maturity", "seed_cost_per_unit", "units_per_acre", "disease_tolerance"],
    "seed_supply": ["season", "hybrid_id", "units_available"],
    "yield_forecast": [
        "region", "soil_class", "hybrid_id", "window", "exp_yield_bu_ac", "yield_sd", "source_model_version",
    ],
    "planting_capacity": ["region", "window", "acres_capacity"],
    "fixed_requests": ["field_id", "hybrid_id", "window"],
}


@dataclass(frozen=True)
class ScenarioInputs:
    season: int
    fields: pd.DataFrame
    hybrids: pd.DataFrame
    seed_supply: pd.DataFrame
    yield_forecast: pd.DataFrame
    planting_capacity: pd.DataFrame
    fixed_requests: pd.DataFrame

    def __post_init__(self) -> None:
        for name, cols in COLUMNS.items():
            frame = getattr(self, name)
            missing = [c for c in cols if c not in frame.columns]
            if missing:
                raise ValueError(f"{name} is missing columns: {missing}")

    def with_fixed_requests(self, fixed_requests: pd.DataFrame) -> "ScenarioInputs":
        return replace(self, fixed_requests=fixed_requests.reset_index(drop=True))

    def with_fields(self, fields: pd.DataFrame) -> "ScenarioInputs":
        kept = set(fields["field_id"])
        fixed = self.fixed_requests[self.fixed_requests["field_id"].isin(kept)]
        return replace(self, fields=fields.reset_index(drop=True), fixed_requests=fixed.reset_index(drop=True))

    def eligible_pairs(self) -> list[tuple[str, str]]:
        """(field_id, hybrid_id) pairs where the hybrid's maturity fits the field's range."""
        pairs = self.fields.merge(self.hybrids, how="cross")
        ok = pairs[(pairs["relative_maturity"] >= pairs["rm_min"]) & (pairs["relative_maturity"] <= pairs["rm_max"])]
        return list(zip(ok["field_id"], ok["hybrid_id"]))


def empty_fixed_requests() -> pd.DataFrame:
    return pd.DataFrame({"field_id": pd.Series(dtype=str), "hybrid_id": pd.Series(dtype=str),
                         "window": pd.Series(dtype=object)})
