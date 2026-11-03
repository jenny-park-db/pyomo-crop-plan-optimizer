"""Console entry points for the bundle's python_wheel_task tasks.

Jobs pass ``named_parameters`` as ``--<key>=<value>``, keys verbatim, **and also push every job-level
parameter down to every wheel task** as ``--<name>=<value>``. So each flag here uses the YAML's snake_case
spelling (``tests/test_bundle.py`` checks they stay in sync), and flags a task doesn't declare are ignored
rather than fatal. Ignoring them strictly (argparse's default) is what caused the probe's ``SystemExit: 2``.
"""

from __future__ import annotations

import argparse
import sys


def _parser(prog: str, *flags: str, optional: tuple[str, ...] = ()) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog)
    for flag in ("catalog", "schema", *flags):
        p.add_argument(f"--{flag}", required=True)
    for flag in optional:
        p.add_argument(f"--{flag}", default="")
    return p


PARSERS = {
    "cropplan-seed": lambda: _parser("cropplan-seed", optional=("triggered_by",)),
    "cropplan-solve": lambda: _parser("cropplan-solve", "experiment", "scenario_id", "job_run_id",
                                      optional=("run_id", "triggered_by")),
    "cropplan-stress-prepare": lambda: _parser("cropplan-stress-prepare", "volume_root", "scenario_id", "n", "seed",
                                               "job_run_id", optional=("stress_id", "triggered_by")),
    "cropplan-stress-load": lambda: _parser("cropplan-stress-load", "volume_root", "job_run_id"),
}


def parse(entry_point: str, argv: list[str] | None = None) -> argparse.Namespace:
    """Required flags are enforced; extra pushed-down job parameters are printed and ignored."""
    args, extra = PARSERS[entry_point]().parse_known_args(sys.argv[1:] if argv is None else argv)
    if extra:
        print("IGNORED_JOB_PARAMETERS", extra)
    return args


def check_volume_root(volume_root: str, catalog: str, schema: str) -> str:
    """The job runs as the deployer but is triggered by app/agent service principals, so a caller-supplied
    ``volume_root`` must be the bundle's own stress volume, not an arbitrary path the deployer can write."""
    expected = f"/Volumes/{catalog}/{schema}/stress"
    if volume_root != expected:
        raise ValueError(f"volume_root must be {expected!r}, got {volume_root!r}")
    return volume_root


def _store(args: argparse.Namespace):
    from pyspark.sql import SparkSession
    from cropplan_jobs.spark_store import SparkStore
    spark = SparkSession.builder.getOrCreate()
    return spark, SparkStore(spark, args.catalog, args.schema)


def _who(spark, triggered_by: str) -> str:
    """The caller's identity if passed (app/agent pass the signed-in user), else the job's run-as identity."""
    return triggered_by or spark.sql("SELECT current_user() AS u").first()["u"]


def seed() -> None:
    from cropplan_jobs.scenarios import seed_scenarios
    args = parse("cropplan-seed")
    spark, store = _store(args)
    store.create_tables()
    print("SEEDED", seed_scenarios(store, created_by=_who(spark, args.triggered_by)))


def solve() -> None:
    from cropplan_jobs.solve_job import default_run_id, solve_scenario
    from cropplan_jobs.tracking import MlflowTracker
    args = parse("cropplan-solve")
    spark, store = _store(args)
    run_id = default_run_id(args.run_id, args.job_run_id)
    result = solve_scenario(store, MlflowTracker(args.experiment), scenario_id=args.scenario_id, run_id=run_id,
                            job_run_id=args.job_run_id, triggered_by=_who(spark, args.triggered_by))
    print("SOLVED", run_id, result.status, result.termination, result.objective, result.infeasibility_reason)


def stress_prepare() -> None:
    from cropplan_jobs.stress import prepare_stress
    args = parse("cropplan-stress-prepare")
    check_volume_root(args.volume_root, args.catalog, args.schema)
    spark, store = _store(args)
    manifest = prepare_stress(store, args.volume_root, scenario_id=args.scenario_id, n=int(args.n),
                              seed=int(args.seed), stress_id=args.stress_id, job_run_id=args.job_run_id,
                              triggered_by=_who(spark, args.triggered_by))
    print("PREPARED", manifest["stress_id"], manifest["scenario_id"], manifest["n"])


def stress_load() -> None:
    from cropplan_jobs.stress import load_stress, run_dir
    args = parse("cropplan-stress-load")
    check_volume_root(args.volume_root, args.catalog, args.schema)
    _, store = _store(args)
    row = load_stress(store, run_dir(args.volume_root, args.job_run_id))
    print("LOADED", row["stress_id"], row["n"], row["n_solved"], row["p50_gross_margin"])
