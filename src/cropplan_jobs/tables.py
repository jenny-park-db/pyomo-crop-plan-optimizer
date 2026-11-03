"""Names, column types, and sort keys for every Unity Catalog table the jobs read or write (spec §3)."""

from __future__ import annotations

import re

import pandas as pd

# Per-scenario input copies: scenario_id first, then cropplan.data.COLUMNS in order.
INPUTS: dict[str, dict[str, str]] = {
    "fields": {"scenario_id": "STRING", "field_id": "STRING", "grower_id": "STRING", "region": "STRING",
               "acres": "DOUBLE", "lat": "DOUBLE", "lon": "DOUBLE", "soil_class": "STRING",
               "rm_min": "INT", "rm_max": "INT"},
    "hybrids": {"scenario_id": "STRING", "hybrid_id": "STRING", "relative_maturity": "INT",
                "seed_cost_per_unit": "DOUBLE", "units_per_acre": "DOUBLE", "disease_tolerance": "STRING"},
    "seed_supply": {"scenario_id": "STRING", "season": "INT", "hybrid_id": "STRING", "units_available": "DOUBLE"},
    "yield_forecast": {"scenario_id": "STRING", "region": "STRING", "soil_class": "STRING", "hybrid_id": "STRING",
                       "window": "STRING", "exp_yield_bu_ac": "DOUBLE", "yield_sd": "DOUBLE",
                       "source_model_version": "STRING"},
    "planting_capacity": {"scenario_id": "STRING", "region": "STRING", "window": "STRING", "acres_capacity": "DOUBLE"},
    "fixed_requests": {"scenario_id": "STRING", "field_id": "STRING", "hybrid_id": "STRING", "window": "STRING"},
}

# Delta returns rows in no particular order. Inputs are sorted on load so a re-solve builds the identical model.
SORT_KEYS: dict[str, list[str]] = {
    "fields": ["field_id"],
    "hybrids": ["hybrid_id"],
    "seed_supply": ["season", "hybrid_id"],
    "yield_forecast": ["region", "soil_class", "hybrid_id", "window"],
    "planting_capacity": ["region", "window"],
    "fixed_requests": ["field_id", "hybrid_id"],
}

OUTPUTS: dict[str, dict[str, str]] = {
    "scenarios": {"scenario_id": "STRING", "name": "STRING", "parent_scenario_id": "STRING", "season": "INT",
                  "overrides": "STRING", "created_by": "STRING", "created_at": "TIMESTAMP", "source": "STRING",
                  "status": "STRING"},
    "runs": {"run_id": "STRING", "scenario_id": "STRING", "job_run_id": "STRING", "mlflow_run_id": "STRING",
             "triggered_by": "STRING", "status": "STRING", "solver": "STRING", "solver_version": "STRING",
             "model_version": "STRING", "started_at": "TIMESTAMP", "ended_at": "TIMESTAMP", "error": "STRING",
             "infeasibility_reason": "STRING", "mip_gap": "DOUBLE", "termination": "STRING",
             "objective": "DOUBLE", "runtime_s": "DOUBLE",
             # Added after the first release (appended, so ALTER TABLE ... ADD COLUMNS keeps the same order as a fresh CREATE).
             "diagnosis": "STRING", "submitted_at": "TIMESTAMP"},
    "plan_assignments": {"scenario_id": "STRING", "run_id": "STRING", "field_id": "STRING", "hybrid_id": "STRING",
                         "window": "STRING", "acres": "DOUBLE", "exp_yield": "DOUBLE", "exp_margin": "DOUBLE",
                         "is_fixed": "BOOLEAN"},
    "run_summary": {"scenario_id": "STRING", "run_id": "STRING", "acres_planted_pct": "DOUBLE",
                    "gross_margin": "DOUBLE", "unplanted_penalty_total": "DOUBLE", "net_margin": "DOUBLE",
                    "unplanted_fields": "INT", "violations_count": "INT"},
    "seed_utilization": {"scenario_id": "STRING", "run_id": "STRING", "hybrid_id": "STRING", "units_used": "DOUBLE",
                         "units_available": "DOUBLE", "pct": "DOUBLE"},
    "violations": {"scenario_id": "STRING", "run_id": "STRING", "rule": "STRING", "entity": "STRING",
                   "severity": "STRING", "detail": "STRING"},
    "stress_test_results": {"stress_id": "STRING", "scenario_id": "STRING", "sample_id": "INT",
                            "disruption": "STRING", "gross_margin": "DOUBLE", "acres_planted_pct": "DOUBLE",
                            "status": "STRING"},
    "stress_test_summary": {"stress_id": "STRING", "scenario_id": "STRING", "n": "INT", "n_solved": "INT",
                            "n_invalid": "INT", "n_infeasible": "INT", "n_failed": "INT",
                            "p10_gross_margin": "DOUBLE", "p50_gross_margin": "DOUBLE", "p90_gross_margin": "DOUBLE",
                            "fragile_fields": "ARRAY<STRING>", "fragile_hybrids": "ARRAY<STRING>", "seed": "INT",
                            "job_run_id": "STRING", "mlflow_run_id": "STRING", "triggered_by": "STRING",
                            "created_at": "TIMESTAMP"},
}

TABLES: dict[str, dict[str, str]] = {**INPUTS, **OUTPUTS}

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def check_id(value: str, what: str = "id") -> str:
    """IDs end up in SQL predicates and volume paths, so they are limited to a safe alphabet."""
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{what} must be 1-64 letters, digits, '.', '_' or '-', got {value!r}")
    return value


def ddl(table: str, catalog: str, schema: str) -> str:
    cols = ", ".join(f"`{c}` {t}" for c, t in TABLES[table].items())
    return f"CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`{table}` ({cols})"


def add_columns_ddl(table: str, catalog: str, schema: str, existing: set[str]) -> str | None:
    """ALTER TABLE for contract columns an older deployment's table lacks (None when it has them all).

    ``CREATE TABLE IF NOT EXISTS`` never changes an existing table, so columns added to a contract after the
    first deploy (``runs.diagnosis``, ``runs.submitted_at``) need this to reach a live workspace.
    """
    missing = [(c, t) for c, t in TABLES[table].items() if c not in existing]
    if not missing:
        return None
    cols = ", ".join(f"`{c}` {t}" for c, t in missing)
    return f"ALTER TABLE `{catalog}`.`{schema}`.`{table}` ADD COLUMNS ({cols})"


def conform(table: str, rows: pd.DataFrame) -> pd.DataFrame:
    """Columns in table order (extra columns dropped). A missing column is an error, never a silent null.

    Also drops ``DataFrame.attrs``: Spark Connect's ``toPandas()`` stores a ``PlanMetrics`` object there, and
    pandas then fails to write the frame to Parquet ("Object of type PlanMetrics is not JSON serializable").
    """
    cols = list(TABLES[table])
    missing = [c for c in cols if c not in rows.columns]
    if missing:
        raise ValueError(f"{table} rows are missing columns: {missing}")
    out = rows[cols].copy()
    for c, t in TABLES[table].items():
        if t == "INT":
            out[c] = out[c].astype("Int64")
    out.attrs = {}
    return out.reset_index(drop=True)
