import pytest

from cropplan.overrides import Overrides, OverridesError, parse_overrides


def test_defaults_match_spec():
    o = parse_overrides({})
    assert o == Overrides()
    assert (o.diversity_cap, o.unplanted_penalty_per_acre, o.corn_price_per_bu) == (0.40, 150.0, 4.25)
    assert (o.solver, o.time_limit_s, o.mip_rel_gap, o.threads, o.random_seed) == ("highs", 60, 0.001, 1, 2027)


def test_parses_nested_multipliers():
    o = parse_overrides({"supply_pct": {"H-112": 1.1}, "capacity_pct": {"IA": {"W1": 0.5}}})
    assert o.supply_multiplier("H-112") == 1.1
    assert o.supply_multiplier("H-999") == 1.0
    assert o.capacity_multiplier("IA", "W1") == 0.5
    assert o.capacity_multiplier("IA", "W2") == 1.0


def test_round_trips_through_dict():
    o = parse_overrides({"supply_pct": {"H-112": 1.1}, "diversity_cap": 0.45})
    assert parse_overrides(o.to_dict()) == o


def test_zero_multiplier_is_allowed():
    assert parse_overrides({"supply_pct": {"H-204": 0}}).supply_multiplier("H-204") == 0.0


@pytest.mark.parametrize("payload, message", [
    ({"supply_pct": {"H-112": -0.1}}, "between 0 and 3"),
    ({"supply_pct": {"H-112": "lots"}}, "must be a number"),
    ({"supply_pct": {"H-112": True}}, "must be a number"),
    ({"capacity_pct": {"IA": 0.5}}, "region -> {window"),
    ({"diversity_cap": 0}, "diversity_cap"),
    ({"solver": "cplex"}, "solver must be one of"),
    ({"time_limit_s": 0}, "time_limit_s"),
    ({"mip_rel_gap": 0.2}, "mip_rel_gap"),
    ({"supply_pc": {}}, "unknown override keys: supply_pc"),
])
def test_rejects_bad_payloads(payload, message):
    with pytest.raises(OverridesError, match=message):
        parse_overrides(payload)


@pytest.mark.parametrize("payload, message", [
    ({"fixed_requests_enabled": "false"}, "fixed_requests_enabled must be true or false"),
    ({"corn_price_per_bu": float("nan")}, "corn_price_per_bu must be a finite number"),
    ({"unplanted_penalty_per_acre": float("inf")}, "unplanted_penalty_per_acre must be a finite number"),
    ({"supply_pct": {"H-112": float("nan")}}, "supply_pct.H-112 must be a finite number"),
    ({"threads": -3}, "threads must be at least 1"),
    ({"diversity_cap": [1]}, "diversity_cap must be a finite number"),
    ({"time_limit_s": "soon"}, "time_limit_s must be a whole number"),
])
def test_rejects_wrongly_typed_or_non_finite_values(payload, message):
    with pytest.raises(OverridesError, match=message):
        parse_overrides(payload)


def test_fixed_requests_enabled_accepts_real_booleans():
    assert parse_overrides({"fixed_requests_enabled": False}).fixed_requests_enabled is False
