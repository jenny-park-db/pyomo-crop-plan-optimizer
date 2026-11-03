"""AI Runtime entry point for the stress test's solve task: ``python -m cropplan_jobs.stress_air``.

AI Runtime tasks get no job parameters and no Spark session. The task finds its job run through the MLflow run
AI Runtime opens for it (tag ``mlflow.databricks.jobRunID``), reads the ``volume_root`` job parameter through
the Jobs API, and then works only with files that the prepare task wrote under ``<volume_root>/<job_run_id>/``.
"""

from __future__ import annotations

import os
import time

from cropplan.pipeline import MODEL_VERSION
from cropplan_jobs.stress import SAMPLE_GAP, SAMPLE_TIME_LIMIT_S, read_prepared, run_dir, run_stress, write_results
from cropplan_jobs.tracking import MlflowTracker

SUMMARY_METRICS = ("n", "n_solved", "n_invalid", "n_infeasible", "n_failed",
                   "p10_gross_margin", "p50_gross_margin", "p90_gross_margin")


def job_context() -> tuple[str, str, str]:
    """(mlflow_run_id, job_run_id, volume_root) for the current AI Runtime task."""
    import mlflow
    from databricks.sdk import WorkspaceClient
    mlflow_run_id = os.environ["MLFLOW_RUN_ID"]
    mlflow.set_tracking_uri("databricks")
    job_run_id = mlflow.get_run(mlflow_run_id).data.tags["mlflow.databricks.jobRunID"]
    params = {p.name: (p.value if p.value is not None else p.default)
              for p in WorkspaceClient().jobs.get_run(int(job_run_id)).job_parameters or []}
    return mlflow_run_id, job_run_id, params["volume_root"]


def main() -> None:
    import ray
    from databricks.air import ray_init

    mlflow_run_id, job_run_id, volume_root = job_context()
    directory = run_dir(volume_root, job_run_id)
    manifest, inputs, overrides = read_prepared(directory)
    ray_init()
    print(f"STRESS_START n={manifest['n']} cpus={ray.cluster_resources().get('CPU')}", flush=True)

    shared = ray.put((inputs, overrides))

    @ray.remote(num_cpus=1)
    def solve_remote(payload, disruption):
        from cropplan_jobs.stress import solve_sample
        i, o = payload
        return solve_sample(i, o, disruption)

    started = time.monotonic()
    ray_map = lambda _fn, ds: ray.get([solve_remote.remote(shared, d) for d in ds])  # noqa: E731
    results, summary = run_stress(inputs, overrides, manifest["n"], manifest["seed"], map_fn=ray_map)
    wall = time.monotonic() - started

    tags = {"scenario_id": manifest["scenario_id"], "stress_id": manifest["stress_id"], "job_run_id": job_run_id,
            "triggered_by": manifest["triggered_by"], "model_version": MODEL_VERSION, "solver": overrides.solver,
            "kind": "stress_test"}
    with MlflowTracker(None).start_run(None, tags, run_id=mlflow_run_id) as run:
        run.log_params({"scenario_id": manifest["scenario_id"], "n": manifest["n"], "seed": manifest["seed"],
                        "sample_mip_rel_gap": SAMPLE_GAP, "sample_time_limit_s": SAMPLE_TIME_LIMIT_S})
        run.log_metrics({**{k: float(summary[k]) for k in SUMMARY_METRICS if summary.get(k) is not None},
                         "wall_s": wall})
        run.log_frame("stress_test_results.parquet", results.drop(columns=["unplanted_field_ids"]))
    write_results(directory, results, summary, mlflow_run_id)
    print(f"STRESS_DONE n={len(results)} statuses={results['status'].value_counts().to_dict()} wall={wall:.1f}s",
          flush=True)


if __name__ == "__main__":
    main()
