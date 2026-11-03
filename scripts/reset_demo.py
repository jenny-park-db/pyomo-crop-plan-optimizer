"""Put the demo back to its bootstrapped state between demos.

    make reset PROFILE=<p> [TARGET=dev] [ARGS=--yes]
    uv run python scripts/reset_demo.py --profile <p> [--target dev] [--yes]

Deletes, as the CLI profile's user (the deployer owns the tables):
  - every scenario made in the app or by the agent (scenarios.source 'app'/'agent'): its row, its input copies,
    its runs, and their outputs
  - every run of a seeded scenario that precompute didn't make (demo steps 1 and 4 re-run them), with its outputs
  - every run whose scenario no longer exists (left by integration tests), with its outputs
  - every stress test except the two precomputed N=500 ones (live runs from step 7)
Keeps the seeded scenarios, their precompute solves, and the stored N=500 stress tests, so the demo opens on the
numbers the runbook quotes. MLflow runs and the stress volume's hand-off files are left alone (harmless).
Without --yes it only prints what it would delete.
"""

from __future__ import annotations

import argparse
import sys

from cropplan_jobs.tables import INPUTS, OUTPUTS
from demo_env import PRECOMPUTED_STRESS, SEEDED, Sql, Target, in_list, load_target

SCENARIO_TABLES = [t for t, cols in {**INPUTS, **OUTPUTS}.items() if "scenario_id" in cols]
RUN_OUTPUTS = ["plan_assignments", "run_summary", "seed_utilization", "violations"]
STRESS_TABLES = ["stress_test_results", "stress_test_summary"]


def delete_scenario_statements(t: Target, scenario_ids: list[str]) -> list[str]:
    if not scenario_ids:
        return []
    if set(scenario_ids) & set(SEEDED):
        raise ValueError(f"refusing to delete seeded scenarios: {sorted(set(scenario_ids) & set(SEEDED))}")
    ids = in_list(scenario_ids)
    # scenarios last: Studio's clone writes it last, so a half-deleted scenario never looks complete.
    return [f"DELETE FROM {t.fq(tbl)} WHERE scenario_id IN {ids}" for tbl in SCENARIO_TABLES if tbl != "scenarios"] + [
        f"DELETE FROM {t.fq('scenarios')} WHERE scenario_id IN {ids}"]


def extra_run_ids_sql(t: Target) -> str:
    """Runs a reset removes: non-precompute runs of the seeded scenarios, and runs whose scenario is gone (tests)."""
    return (f"SELECT run_id FROM {t.fq('runs')} WHERE (scenario_id IN {in_list(SEEDED)} "
            f"AND coalesce(triggered_by, '') <> 'precompute') "
            f"OR scenario_id NOT IN (SELECT scenario_id FROM {t.fq('scenarios')})")


def extra_run_statements(t: Target) -> list[str]:
    extra = extra_run_ids_sql(t)
    return [f"DELETE FROM {t.fq(tbl)} WHERE run_id IN ({extra})" for tbl in RUN_OUTPUTS] + [
        f"DELETE FROM {t.fq('runs')} WHERE run_id IN ({extra})"]


def extra_stress_statements(t: Target) -> list[str]:
    return [f"DELETE FROM {t.fq(tbl)} WHERE stress_id NOT IN {in_list(PRECOMPUTED_STRESS)}" for tbl in STRESS_TABLES]


def delete_scenarios(sql: Sql, t: Target, scenario_ids: list[str]) -> None:
    for statement in delete_scenario_statements(t, scenario_ids):
        sql.rows(statement)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True)
    p.add_argument("--target", default="dev")
    p.add_argument("--yes", action="store_true", help="delete (default: only show what would be deleted)")
    args = p.parse_args(argv)

    t = load_target(args.profile, args.target)
    sql = Sql(args.profile, t.warehouse_id)
    made = [r["scenario_id"] for r in sql.rows(
        f"SELECT scenario_id FROM {t.fq('scenarios')} WHERE source IN ('app', 'agent') ORDER BY scenario_id")]
    [runs] = sql.rows(f"SELECT count(*) AS n FROM ({extra_run_ids_sql(t)})")
    stress = [r["stress_id"] for r in sql.rows(
        f"SELECT stress_id FROM {t.fq('stress_test_summary')} WHERE stress_id NOT IN {in_list(PRECOMPUTED_STRESS)}")]
    [active] = sql.rows(f"SELECT count(*) AS n FROM {t.fq('runs')} WHERE status IN ('queued', 'validating', 'solving', 'checking')")
    print(f"{len(made)} app/agent scenario(s): {', '.join(made) or '-'}")
    print(f"{runs['n']} extra run(s) (seeded scenarios' re-runs, orphaned test runs); {len(stress)} live stress test(s): {', '.join(stress) or '-'}")
    if int(active["n"]):
        print(f"Note: {active['n']} run(s) are still active; their jobs may write rows after the reset.")
    if not args.yes:
        print("Dry run. Re-run with --yes to delete.")
        return
    for statement in delete_scenario_statements(t, made) + extra_run_statements(t) + extra_stress_statements(t):
        sql.rows(statement)
    print("Reset done: seeded scenarios, their precompute solves, and the two N=500 stress tests remain.")


if __name__ == "__main__":
    main(sys.argv[1:])
