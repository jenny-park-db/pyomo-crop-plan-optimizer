"""Stand the whole demo up in a workspace with one command (spec §11, success criterion 6).

    make bootstrap PROFILE=<cli-profile> [TARGET=dev]
    UV_HTTP_TIMEOUT=180 uv run python scripts/bootstrap.py --profile <p> [--target dev] [--catalog <c>]
        [--from <step>] [--only <step>] [--reseed] [--recompute]

Steps, in order. Each one is safe to re-run: finished work is detected and skipped, so a failed bootstrap is
resumed by running the same command again (or `--from <step>`).
  preflight   CLI login; the UC catalog (--catalog, CROP_PLAN_CATALOG in .env, or derived from the workspace
              host: some demo workspaces are named fevm-<name> and pre-create <name>_catalog); recorded as
              bundle variable `catalog`
  tables      the schema and all 15 tables, empty, through the warehouse (cropplan_jobs.tables.ddl), then
              the schema is bound to the bundle. The Genie space checks its tables exist when it is created,
              so on a fresh workspace they must exist before the first `bundle deploy`
  deploy      databricks bundle deploy (schema, volume, experiment, jobs, Genie space, Crop Plan Studio); then
              `bundle run crop_plan_studio` if Studio has no running deployment
  seed        seed_data job, unless the three seeded scenarios are there (--reseed forces it)
  precompute  precompute job (~15 min), unless every seeded scenario has a precompute solve and both
              N=500 stress tests are stored with all 500 samples solved (--recompute forces it); stops if a
              precompute run is still active (e.g. from a bootstrap whose machine slept)
  agent       scripts/deploy_agent.py: the agent app, Studio's agent_url, bundle redeploy
  grants      scripts/grant_presenters.py for CROP_PLAN_PRESENTERS in .env (skipped when empty)
  smoke       scripts/smoke_test.py: spec §10 at the API level
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from urllib.parse import urlparse

import deploy_agent
import grant_presenters
import smoke_test
from demo_env import BUNDLE_DIR, PRECOMPUTED_STRESS, SEEDED, Sql, Target, bundle_json, in_list, load_target, read_dotenv, run

STEPS = ("preflight", "tables", "deploy", "seed", "precompute", "agent", "grants", "smoke")
OVERRIDES = "variable-overrides.json"


def catalog_for_host(host: str) -> str:
    """Default catalog when none is given. Some demo workspaces are named `fevm-<name>` and pre-create
    `<name>_catalog` (https://fevm-my-demo.cloud... -> my_demo_catalog); otherwise `<host label>_catalog`."""
    label = (urlparse(host).hostname or host).split(".")[0]
    name = label.removeprefix("fevm-").replace("-", "_").lower()
    if not name:
        raise SystemExit(f"Can't derive a catalog from host {host!r}; pass --catalog")
    return f"{name}_catalog"


def steps_to_run(start: str | None, only: str | None) -> list[str]:
    for s in (start, only):
        if s is not None and s not in STEPS:
            raise SystemExit(f"Unknown step {s!r}; steps are {', '.join(STEPS)}")
    if only:
        return [only]
    return list(STEPS[STEPS.index(start):]) if start else list(STEPS)


def table_statements(catalog: str, schema: str) -> list[str]:
    from cropplan_jobs.tables import TABLES, ddl

    comment = "Pyomo crop plan demo inputs and outputs, keyed by scenario_id (synthetic data)."
    return [f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}` COMMENT '{comment}'",
            *(ddl(t, catalog, schema) for t in TABLES)]


def schema_bound(summary: dict) -> bool:
    """Whether the bundle already manages the schema (bound or created by an earlier deploy)."""
    return bool(summary.get("resources", {}).get("schemas", {}).get("crop_plan", {}).get("id"))


def app_needs_deploy(app: dict) -> bool:
    """True when Studio has no successful deployment or isn't running. A deploy that failed after creating the app
    leaves it with no deployment, and later `bundle deploy`s report it unchanged."""
    deployment = (app.get("active_deployment") or {}).get("status", {}).get("state")
    return deployment != "SUCCEEDED" or (app.get("app_status") or {}).get("state") != "RUNNING"


def is_seeded(counts: dict[str, int], scenario_rows: set[str]) -> bool:
    """counts = fields rows per seeded scenario_id; scenario_rows = seeded IDs with a `source = 'seed'` scenarios row.
    Seed writes 150 fields for each of the three, and each scenario's row last, so the row marks it complete."""
    return all(counts.get(s, 0) == 150 and s in scenario_rows for s in SEEDED)


def is_precomputed(final_runs: dict[str, str], stress: dict[str, tuple[int, int]]) -> bool:
    """final_runs = scenario_id -> status of its latest precompute run; stress = stress_id -> (n, n_solved)."""
    expected = {"baseline-2027": "done", "grower-commitments-2027": "infeasible", "revision-1-2027": "done"}
    return (all(final_runs.get(s) == st for s, st in expected.items())
            and all(stress.get(i) == (500, 500) for i in PRECOMPUTED_STRESS))


class Bootstrap:
    def __init__(self, profile: str, target: str, catalog: str | None, reseed: bool, env: dict[str, str],
                 recompute: bool = False) -> None:
        self.profile, self.target, self.catalog_arg, self.reseed, self.env = profile, target, catalog, reseed, env
        self.recompute = recompute
        self.override = BUNDLE_DIR / ".databricks" / "bundle" / target / OVERRIDES

    # -- helpers ---------------------------------------------------------------------------------------------
    def cli(self, *args: str, capture: bool = False) -> str:
        return run(["databricks", *args, "--profile", self.profile], cwd=BUNDLE_DIR, capture=capture)

    def validated(self) -> dict:
        return bundle_json("validate", self.profile, self.target)

    def sql(self, warehouse_id: str | None = None) -> Sql:
        return Sql(self.profile, warehouse_id or self.deployed().warehouse_id)

    def deployed(self) -> Target:
        return load_target(self.profile, self.target)

    def run_job(self, key: str, *params: str) -> None:
        t0 = time.time()
        self.cli("bundle", "run", "-t", self.target, key, *params)
        print(f"   {key} finished in {(time.time() - t0) / 60:.1f} min", flush=True)

    # -- steps -----------------------------------------------------------------------------------------------
    def preflight(self) -> None:
        me = json.loads(self.cli("current-user", "me", "-o", "json", capture=True))["userName"]
        host = json.loads(self.cli("auth", "describe", "-o", "json", capture=True))["details"]["host"]
        catalog = self.catalog_arg or self.env.get("CROP_PLAN_CATALOG") or catalog_for_host(host)
        try:
            self.cli("catalogs", "get", catalog, "-o", "json", capture=True)
        except subprocess.CalledProcessError:
            raise SystemExit(f"Catalog {catalog!r} isn't visible to {me}. The bootstrap doesn't CREATE CATALOG: "
                             "pass --catalog <an existing catalog> or set CROP_PLAN_CATALOG in .env.") from None
        deploy_agent.write_override(self.override, "catalog", catalog)
        print(f"   {me} on {host}; catalog {catalog} (recorded in {self.override.name})")

    def tables(self) -> None:
        v = self.validated()["variables"]
        catalog, schema = v["catalog"]["value"], v["schema"]["value"]
        sql = self.sql(v["warehouse_id"]["value"])
        for statement in table_statements(catalog, schema):
            sql.rows(statement)
        if not schema_bound(bundle_json("summary", self.profile, self.target)):
            self.cli("bundle", "deployment", "bind", "-t", self.target, "crop_plan", f"{catalog}.{schema}", "--auto-approve")
        print(f"   {catalog}.{schema}: schema and tables ready")

    def deploy(self) -> None:
        self.cli("bundle", "deploy", "-t", self.target)
        app = self.deployed().studio_app
        if app_needs_deploy(json.loads(self.cli("apps", "get", app, "-o", "json", capture=True))):
            print(f"   {app} has no running deployment; deploying and starting it")
            self.cli("bundle", "run", "-t", self.target, "crop_plan_studio")

    def seed(self) -> None:
        t = self.deployed()
        sql = self.sql(t.warehouse_id)
        rows = sql.rows(f"SELECT scenario_id, count(*) AS n FROM {t.fq('fields')} "
                        f"WHERE scenario_id IN {in_list(SEEDED)} GROUP BY scenario_id")
        made = sql.rows(f"SELECT scenario_id FROM {t.fq('scenarios')} WHERE scenario_id IN {in_list(SEEDED)} "
                        f"AND source = 'seed'")
        if is_seeded({r["scenario_id"]: int(r["n"]) for r in rows}, {r["scenario_id"] for r in made}) and not self.reseed:
            print("   seeded scenarios present; skipping (--reseed to rewrite them)")
            return
        self.run_job("seed_data", "--params", "triggered_by=bootstrap")

    def precompute(self) -> None:
        t = self.deployed()
        sql = self.sql(t.warehouse_id)
        runs = sql.rows(f"SELECT scenario_id, max_by(status, started_at) AS status FROM {t.fq('runs')} "
                        f"WHERE triggered_by = 'precompute' GROUP BY scenario_id")
        stress = sql.rows(f"SELECT stress_id, n, n_solved FROM {t.fq('stress_test_summary')} "
                          f"WHERE stress_id IN {in_list(PRECOMPUTED_STRESS)}")
        finished = is_precomputed({r["scenario_id"]: r["status"] for r in runs},
                                  {r["stress_id"]: (int(r["n"] or 0), int(r["n_solved"] or 0)) for r in stress})
        if finished and not self.recompute:
            print("   stored solves and N=500 stress tests present; skipping (--recompute to run it again)")
            return
        active = json.loads(self.cli("jobs", "list-runs", "--job-id", str(t.jobs["precompute"]), "--active-only",
                                     "-o", "json", capture=True) or "[]")
        if active:
            raise SystemExit(f"A precompute run is still active: {active[0].get('run_page_url') or active[0].get('run_id')}. "
                             "Wait for it to finish (or cancel it), then re-run the bootstrap.")
        self.run_job("precompute")

    def agent(self) -> None:
        name = self.env.get("CROP_PLAN_AGENT_NAME") or deploy_agent.DEFAULT_AGENT_NAME
        deploy_agent.main(["--profile", self.profile, "--target", self.target, "--agent-name", name])

    def grants(self) -> None:
        if not self.env.get("CROP_PLAN_PRESENTERS", "").strip():
            print("   CROP_PLAN_PRESENTERS is empty in .env; no presenter grants (run `make grant` later)")
            return
        grant_presenters.main(["--profile", self.profile, "--target", self.target])

    def smoke(self) -> None:
        smoke_test.main(["--profile", self.profile, "--target", self.target])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True)
    p.add_argument("--target", default="dev")
    p.add_argument("--catalog", help="UC catalog to use (default: CROP_PLAN_CATALOG in .env, else derived from the host)")
    p.add_argument("--from", dest="start", metavar="STEP", help=f"start at this step ({', '.join(STEPS)})")
    p.add_argument("--only", metavar="STEP", help="run just this step")
    p.add_argument("--reseed", action="store_true", help="re-run seed_data even when the seeded scenarios exist")
    p.add_argument("--recompute", action="store_true", help="re-run precompute even when its results look complete")
    args = p.parse_args(argv)

    b = Bootstrap(args.profile, args.target, args.catalog, args.reseed, read_dotenv(), recompute=args.recompute)
    t0 = time.time()
    for step in steps_to_run(args.start, args.only):
        print(f"== {step}", flush=True)
        s0 = time.time()
        getattr(b, step)()
        print(f"   ({step}: {time.time() - s0:.0f} s)", flush=True)
    print(f"Bootstrap finished in {(time.time() - t0) / 60:.1f} min.")


if __name__ == "__main__":
    main(sys.argv[1:])
