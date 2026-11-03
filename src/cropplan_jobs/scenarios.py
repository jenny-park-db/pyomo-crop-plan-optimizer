"""Scenario rows and their per-scenario input copies."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from cropplan.data import ScenarioInputs
from cropplan.generate import SEEDED_SCENARIOS, seeded_scenarios
from cropplan.overrides import Overrides, parse_overrides
from cropplan_jobs.store import TableStore
from cropplan_jobs.tables import INPUTS, SORT_KEYS, check_id


def utcnow() -> datetime:
    """Naive UTC, which is what Spark TIMESTAMP columns hold on a UTC session."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ScenarioNotFound(LookupError):
    pass


def write_scenario(store: TableStore, scenario_id: str, name: str, inputs: ScenarioInputs, overrides: Overrides,
                   *, parent_scenario_id: str | None, created_by: str, source: str) -> None:
    """Write (or rewrite) one scenario row and all of its input rows."""
    check_id(scenario_id, "scenario_id")
    for table in INPUTS:
        store.replace(table, getattr(inputs, table).assign(scenario_id=scenario_id), scenario_id=scenario_id)
    row = {"scenario_id": scenario_id, "name": name, "parent_scenario_id": parent_scenario_id,
           "season": inputs.season, "overrides": json.dumps(overrides.to_dict(), sort_keys=True),
           "created_by": created_by, "created_at": utcnow(), "source": source, "status": "active"}
    store.replace("scenarios", pd.DataFrame([row]), scenario_id=scenario_id)


def _null_windows(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.astype({"window": object})
    frame["window"] = frame["window"].where(frame["window"].notna(), None)
    return frame


def load_scenario(store: TableStore, scenario_id: str) -> tuple[dict, ScenarioInputs, dict]:
    """Return (scenario row, inputs, raw overrides payload).

    Overrides come back unparsed so the caller can report a bad payload as ``invalid`` instead of crashing.
    Input rows are sorted by their keys, so the same stored scenario always builds the same model.
    """
    found = store.read("scenarios", scenario_id=scenario_id)
    if found.empty:
        raise ScenarioNotFound(f"scenario {scenario_id!r} not found")
    row = found.iloc[0].to_dict()
    frames = {}
    for table in INPUTS:
        frame = store.read(table, scenario_id=scenario_id).drop(columns="scenario_id")
        frames[table] = frame.sort_values(SORT_KEYS[table], kind="stable").reset_index(drop=True)
    frames["fixed_requests"] = _null_windows(frames["fixed_requests"])
    inputs = ScenarioInputs(season=int(row["season"]), **frames)
    payload = json.loads(row["overrides"]) if isinstance(row["overrides"], str) and row["overrides"] else {}
    return row, inputs, payload


def clone_scenario(store: TableStore, parent_id: str, new_id: str, name: str, overrides: dict | None,
                   *, created_by: str, source: str) -> Overrides:
    """Copy the parent's input rows under ``new_id`` with new overrides.

    Raises OverridesError on a bad payload and ValueError if ``new_id`` exists, before writing anything.
    """
    check_id(new_id, "scenario_id")
    parsed = parse_overrides(overrides)
    if not store.read("scenarios", scenario_id=new_id).empty:
        raise ValueError(f"scenario {new_id!r} already exists")
    _, inputs, _ = load_scenario(store, parent_id)
    write_scenario(store, new_id, name, inputs, parsed, parent_scenario_id=parent_id,
                   created_by=created_by, source=source)
    return parsed


def seed_scenarios(store: TableStore, created_by: str, seed: int = 2027) -> list[str]:
    """Write the three seeded scenarios (fixed IDs) with source 'seed'. Safe to re-run."""
    written = []
    for scenario_id, (inputs, overrides) in seeded_scenarios(seed).items():
        name, parent = SEEDED_SCENARIOS[scenario_id]
        write_scenario(store, scenario_id, name, inputs, overrides, parent_scenario_id=parent,
                       created_by=created_by, source="seed")
        written.append(scenario_id)
    return written
