"""Scenario settings ("overrides") shared by the app form, the agent tool, and stress tests."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

SOLVERS = ("highs", "gurobi")
MAX_MULTIPLIER = 3.0


class OverridesError(ValueError):
    """Raised when an overrides payload is malformed."""


@dataclass(frozen=True)
class Overrides:
    supply_pct: dict[str, float] = field(default_factory=dict)
    capacity_pct: dict[str, dict[str, float]] = field(default_factory=dict)
    diversity_cap: float = 0.40
    unplanted_penalty_per_acre: float = 150.0
    corn_price_per_bu: float = 4.25
    fixed_requests_enabled: bool = True
    solver: str = "highs"
    time_limit_s: int = 60
    mip_rel_gap: float = 0.001
    threads: int | None = 1
    random_seed: int | None = 2027

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def supply_multiplier(self, hybrid_id: str) -> float:
        return self.supply_pct.get(hybrid_id, 1.0)

    def capacity_multiplier(self, region: str, window: str) -> float:
        return self.capacity_pct.get(region, {}).get(window, 1.0)


def _multiplier(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OverridesError(f"{path} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise OverridesError(f"{path} must be a finite number, got {value!r}")
    if not 0.0 <= float(value) <= MAX_MULTIPLIER:
        raise OverridesError(f"{path} must be between 0 and {MAX_MULTIPLIER}, got {value}")
    return float(value)


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OverridesError(f"{path} must be a finite number, got {value!r}")
    return float(value)


def _whole(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OverridesError(f"{path} must be a whole number, got {value!r}")
    return value


def parse_overrides(payload: dict[str, Any] | None) -> Overrides:
    """Validate the shape and ranges of an overrides payload.

    Names (hybrids, regions, windows) are checked against scenario inputs in
    ``cropplan.validate`` because they depend on the data.
    """
    payload = dict(payload or {})
    known = set(Overrides.__dataclass_fields__)
    unknown = sorted(set(payload) - known)
    if unknown:
        raise OverridesError(f"unknown override keys: {', '.join(unknown)}")

    supply = payload.get("supply_pct", {})
    if not isinstance(supply, dict):
        raise OverridesError("supply_pct must be an object of hybrid_id -> multiplier")
    supply_pct = {str(h): _multiplier(v, f"supply_pct.{h}") for h, v in supply.items()}

    capacity = payload.get("capacity_pct", {})
    if not isinstance(capacity, dict) or not all(isinstance(v, dict) for v in capacity.values()):
        raise OverridesError("capacity_pct must be an object of region -> {window -> multiplier}")
    capacity_pct = {
        str(r): {str(w): _multiplier(v, f"capacity_pct.{r}.{w}") for w, v in windows.items()}
        for r, windows in capacity.items()
    }

    defaults = Overrides()
    diversity_cap = _number(payload.get("diversity_cap", defaults.diversity_cap), "diversity_cap")
    if not 0.0 < diversity_cap <= 1.0:
        raise OverridesError(f"diversity_cap must be in (0, 1], got {diversity_cap}")
    penalty = _number(payload.get("unplanted_penalty_per_acre", defaults.unplanted_penalty_per_acre),
                      "unplanted_penalty_per_acre")
    if penalty < 0:
        raise OverridesError("unplanted_penalty_per_acre must be >= 0")
    price = _number(payload.get("corn_price_per_bu", defaults.corn_price_per_bu), "corn_price_per_bu")
    if price <= 0:
        raise OverridesError("corn_price_per_bu must be > 0")
    solver = payload.get("solver", defaults.solver)
    if solver not in SOLVERS:
        raise OverridesError(f"solver must be one of {SOLVERS}, got {solver!r}")
    time_limit = _whole(payload.get("time_limit_s", defaults.time_limit_s), "time_limit_s")
    if not 1 <= time_limit <= 3600:
        raise OverridesError("time_limit_s must be between 1 and 3600")
    gap = _number(payload.get("mip_rel_gap", defaults.mip_rel_gap), "mip_rel_gap")
    if not 0.0 <= gap <= 0.05:
        raise OverridesError("mip_rel_gap must be between 0 and 0.05")
    threads = payload.get("threads", defaults.threads)
    if threads is not None and _whole(threads, "threads") < 1:
        raise OverridesError(f"threads must be at least 1, got {threads}")
    seed = payload.get("random_seed", defaults.random_seed)
    if seed is not None:
        _whole(seed, "random_seed")
    enabled = payload.get("fixed_requests_enabled", defaults.fixed_requests_enabled)
    if not isinstance(enabled, bool):
        raise OverridesError(f"fixed_requests_enabled must be true or false, got {enabled!r}")

    return Overrides(
        supply_pct=supply_pct,
        capacity_pct=capacity_pct,
        diversity_cap=diversity_cap,
        unplanted_penalty_per_acre=penalty,
        corn_price_per_bu=price,
        fixed_requests_enabled=enabled,
        solver=solver,
        time_limit_s=time_limit,
        mip_rel_gap=gap,
        threads=threads,
        random_seed=seed,
    )
