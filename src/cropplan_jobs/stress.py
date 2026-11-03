"""Stress tests, split so the Ray solve (AI Runtime, no Spark) and the UC writes (serverless) share files.

prepare (serverless): scenario rows from UC → ``<volume_root>/<job_run_id>/`` inputs + manifest.json
solve   (AI Runtime): manifest + inputs → results.parquet + summary.json   (see ``stress_air``)
load    (serverless): results.parquet + summary.json → stress_test_results / stress_test_summary
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Callable, Iterable

import pandas as pd

from cropplan.data import ScenarioInputs
from cropplan.disrupt import apply_disruption, sample_disruptions, summarize_stress
from cropplan.overrides import Overrides, parse_overrides
from cropplan.pipeline import run_pipeline
from cropplan_jobs.scenarios import load_scenario, utcnow
from cropplan_jobs.store import TableStore
from cropplan_jobs.tables import INPUTS, check_id

SAMPLE_GAP = 0.01
SAMPLE_TIME_LIMIT_S = 30
MANIFEST, RESULTS, SUMMARY = "manifest.json", "results.parquet", "summary.json"


def stress_settings(overrides: Overrides) -> Overrides:
    """Per-sample solve settings: 1% gap and 30 s keep N=500 to a few minutes on 12 Ray CPUs."""
    return replace(overrides, mip_rel_gap=SAMPLE_GAP, time_limit_s=SAMPLE_TIME_LIMIT_S)


def run_dir(volume_root: str, job_run_id: str) -> str:
    return os.path.join(volume_root, check_id(job_run_id, "job_run_id"))


def prepare_stress(store: TableStore, volume_root: str, *, scenario_id: str, n: int, seed: int, stress_id: str,
                   job_run_id: str, triggered_by: str) -> dict:
    """Snapshot the scenario's inputs and settings for the AI Runtime task. Returns the manifest."""
    check_id(scenario_id, "scenario_id")
    check_id(stress_id or f"stress-{job_run_id}", "stress_id")
    if not 1 <= n <= 5000:
        raise ValueError(f"n must be between 1 and 5000, got {n}")
    _, inputs, payload = load_scenario(store, scenario_id)
    overrides = parse_overrides(payload)  # a scenario with bad overrides can't be stress-tested
    out = run_dir(volume_root, job_run_id)
    os.makedirs(out, exist_ok=True)
    for table in INPUTS:
        getattr(inputs, table).to_parquet(os.path.join(out, f"{table}.parquet"), index=False)
    manifest = {"stress_id": stress_id or f"stress-{job_run_id}", "scenario_id": scenario_id, "n": n, "seed": seed,
                "season": inputs.season, "overrides": overrides.to_dict(), "job_run_id": job_run_id,
                "triggered_by": triggered_by}
    with open(os.path.join(out, MANIFEST), "w") as f:
        json.dump(manifest, f, sort_keys=True)
    return manifest


def read_prepared(directory: str) -> tuple[dict, ScenarioInputs, Overrides]:
    with open(os.path.join(directory, MANIFEST)) as f:
        manifest = json.load(f)
    frames = {t: pd.read_parquet(os.path.join(directory, f"{t}.parquet")) for t in INPUTS}
    fixed = frames["fixed_requests"].astype({"window": object})
    frames["fixed_requests"] = fixed.where(fixed.notna(), None)
    inputs = ScenarioInputs(season=int(manifest["season"]), **frames)
    return manifest, inputs, stress_settings(parse_overrides(manifest["overrides"]))


def solve_sample(inputs: ScenarioInputs, overrides: Overrides, disruption: dict) -> dict:
    """One disrupted solve. Never raises: an exception becomes a ``failed`` sample so the stress run continues."""
    row = {"sample_id": disruption["sample_id"], "kind": disruption["kind"],
           "hybrid_id": disruption.get("hybrid_id"), "disruption": json.dumps(disruption, sort_keys=True),
           "status": "failed", "gross_margin": None, "acres_planted_pct": None, "unplanted_field_ids": [],
           "error": None}
    try:
        d_inputs, d_overrides = apply_disruption(inputs, overrides, disruption)
        result = run_pipeline(d_inputs, d_overrides)
    except Exception as exc:  # one bad sample must not sink the other N-1
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    row["status"], row["error"] = result.status, result.error
    if result.summary:
        row["gross_margin"] = result.summary["gross_margin"]
        row["acres_planted_pct"] = result.summary["acres_planted_pct"]
        a = result.assignments
        row["unplanted_field_ids"] = sorted(a.loc[a["hybrid_id"].isna(), "field_id"])
    return row


def base_unplanted(inputs: ScenarioInputs, overrides: Overrides) -> set[str]:
    result = run_pipeline(inputs, overrides)
    if result.assignments is None:
        return set()
    a = result.assignments
    return set(a.loc[a["hybrid_id"].isna(), "field_id"])


def run_stress(inputs: ScenarioInputs, overrides: Overrides, n: int, seed: int,
               map_fn: Callable[[Callable, Iterable[dict]], list[dict]] | None = None) -> tuple[pd.DataFrame, dict]:
    """Sample ``n`` disruptions, solve each (``map_fn`` fans out; Ray in AI Runtime), and summarize."""
    disruptions = sample_disruptions(inputs, n, seed=seed)
    one = lambda d: solve_sample(inputs, overrides, d)  # noqa: E731
    rows = map_fn(one, disruptions) if map_fn else [one(d) for d in disruptions]
    results = pd.DataFrame(rows).sort_values("sample_id").reset_index(drop=True)
    return results, summarize_stress(results, base_unplanted(inputs, overrides))


def write_results(directory: str, results: pd.DataFrame, summary: dict, mlflow_run_id: str | None) -> None:
    results.to_parquet(os.path.join(directory, RESULTS), index=False)
    with open(os.path.join(directory, SUMMARY), "w") as f:
        json.dump({**summary, "mlflow_run_id": mlflow_run_id}, f, sort_keys=True)


def load_stress(store: TableStore, directory: str) -> dict:
    """Write the AI Runtime task's files to UC. Replaces by stress_id, so a re-run load is idempotent."""
    with open(os.path.join(directory, MANIFEST)) as f:
        manifest = json.load(f)
    with open(os.path.join(directory, SUMMARY)) as f:
        summary = json.load(f)
    results = pd.read_parquet(os.path.join(directory, RESULTS))
    stress_id, scenario_id = manifest["stress_id"], manifest["scenario_id"]
    store.replace("stress_test_results", results.assign(stress_id=stress_id, scenario_id=scenario_id),
                  stress_id=stress_id)
    row = {**{k: summary.get(k) for k in ("n", "n_solved", "n_invalid", "n_infeasible", "n_failed",
                                          "p10_gross_margin", "p50_gross_margin", "p90_gross_margin",
                                          "mlflow_run_id")},
           "fragile_fields": list(summary.get("fragile_fields") or []),
           "fragile_hybrids": list(summary.get("fragile_hybrids") or []),
           "stress_id": stress_id, "scenario_id": scenario_id, "seed": manifest["seed"],
           "job_run_id": manifest["job_run_id"], "triggered_by": manifest["triggered_by"], "created_at": utcnow()}
    store.replace("stress_test_summary", pd.DataFrame([row]), stress_id=stress_id)
    return row
