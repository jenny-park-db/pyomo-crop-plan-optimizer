"""Give other presenters what the demo needs, least privilege.

    make grant PROFILE=<p> [TARGET=dev]
    uv run python scripts/grant_presenters.py --profile <p> [--target dev] [--presenters a@x.com,Planners] [--dry-run]

Presenters come from --presenters or CROP_PLAN_PRESENTERS in .env (comma-separated; an entry with "@" is a user,
anything else a group). Grants are additive PATCHes, so re-running is safe and never removes anyone. Unity Catalog
only knows users and account-level groups: a workspace-local group gets the workspace grants but fails the UC ones.

What Crop Plan Studio and the agent do as the signed-in user (OBO), and therefore what a presenter needs:
  apps         CAN_USE on Crop Plan Studio and on the agent app
  Genie space  CAN_RUN (the Ask data tab and the agent's genie_agent tool ask Genie as the user)
  warehouse    CAN_USE (every Studio query, and Genie, runs on it as the user)
  UC           USE CATALOG; USE SCHEMA + SELECT on the schema (reads, Genie); MODIFY on the eight tables a
               new scenario writes: scenarios, runs (MERGE/UPDATE) and the six input tables (INSERT the clone,
               DELETE to undo a failed clone). Output tables are written by the jobs, never by the user
  jobs         CAN_VIEW on solve_scenario / stress_test, so the Runs screen's job links open. Starting runs
               needs nothing: Studio's service principal starts them (`jobs` isn't an Apps user scope)
  experiment   CAN_READ on the scenarios experiment, so the MLflow run links open
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

import deploy_agent
from demo_env import Target, load_target, read_dotenv, split_list

# Tables Studio writes as the user (app/server/studio/sql.ts: copyInputs, deleteScenarioRows, insertScenario,
# openRun, setJobRunId, markFailed).
USER_WRITTEN_TABLES = ("scenarios", "runs", "fields", "hybrids", "seed_supply", "yield_forecast",
                       "planting_capacity", "fixed_requests")


@dataclass(frozen=True)
class Call:
    method: str
    path: str
    body: dict[str, Any]


def principal_key(principal: str) -> str:
    """Workspace ACL field for a principal: users by email, everything else as a group name."""
    return "user_name" if "@" in principal else "group_name"


def acl(principals: list[str], level: str) -> dict[str, Any]:
    return {"access_control_list": [{principal_key(p): p, "permission_level": level} for p in principals]}


def uc(principals: list[str], privileges: list[str]) -> dict[str, Any]:
    return {"changes": [{"principal": p, "add": privileges} for p in principals]}


def grant_plan(t: Target, agent_app: str, principals: list[str]) -> list[Call]:
    if not principals:
        raise SystemExit("No presenters: pass --presenters or set CROP_PLAN_PRESENTERS in .env")
    if not t.space_id:
        raise SystemExit("The bundle has no Genie space yet; run the bootstrap's deploy step first")
    schema = f"{t.catalog}.{t.schema}"
    calls = [
        Call("PATCH", f"/api/2.0/permissions/apps/{t.studio_app}", acl(principals, "CAN_USE")),
        Call("PATCH", f"/api/2.0/permissions/apps/{agent_app}", acl(principals, "CAN_USE")),
        Call("PATCH", f"/api/2.0/permissions/genie/{t.space_id}", acl(principals, "CAN_RUN")),
        Call("PATCH", f"/api/2.0/permissions/warehouses/{t.warehouse_id}", acl(principals, "CAN_USE")),
        Call("PATCH", f"/api/2.1/unity-catalog/permissions/catalog/{t.catalog}", uc(principals, ["USE_CATALOG"])),
        Call("PATCH", f"/api/2.1/unity-catalog/permissions/schema/{schema}", uc(principals, ["USE_SCHEMA", "SELECT"])),
        *(Call("PATCH", f"/api/2.1/unity-catalog/permissions/table/{schema}.{table}", uc(principals, ["MODIFY"]))
          for table in USER_WRITTEN_TABLES),
        *(Call("PATCH", f"/api/2.0/permissions/jobs/{t.jobs[job]}", acl(principals, "CAN_VIEW"))
          for job in ("solve_scenario", "stress_test")),
    ]
    if t.experiment_id:
        calls.append(Call("PATCH", f"/api/2.0/permissions/experiments/{t.experiment_id}", acl(principals, "CAN_READ")))
    return calls


UC_HINT = ("Unity Catalog grants need users or account-level groups; a workspace-local group (made in the "
           "workspace's admin settings) can't hold them. Use an account group or list the users.")


def apply(calls: list[Call], do: Callable[[str, str, dict[str, Any]], Any],
          out: Callable[[str], None] = print) -> list[str]:
    """Make every call (one failure doesn't stop the rest); return a line per failed call."""
    failures = []
    for c in calls:
        try:
            do(c.method, c.path, c.body)
            out(f"   granted {c.path}")
        except Exception as e:  # noqa: BLE001 - reported per call, then the script exits non-zero
            failures.append(f"{c.path}: {e}")
            out(f"   FAILED  {c.path}: {e}")
    return failures


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True)
    p.add_argument("--target", default="dev")
    p.add_argument("--presenters", help="comma-separated emails/groups (default: CROP_PLAN_PRESENTERS in .env)")
    p.add_argument("--agent-app", help="agent app name (default: agent-bricks-<CROP_PLAN_AGENT_NAME or crop-plan-agent>)")
    p.add_argument("--dry-run", action="store_true", help="print the calls without making them")
    args = p.parse_args(argv)

    env = read_dotenv()
    principals = split_list(args.presenters if args.presenters is not None else env.get("CROP_PLAN_PRESENTERS"))
    agent_app = args.agent_app or deploy_agent.agent_app_name(env.get("CROP_PLAN_AGENT_NAME") or deploy_agent.DEFAULT_AGENT_NAME)
    calls = grant_plan(load_target(args.profile, args.target), agent_app, principals)
    if args.dry_run:
        for c in calls:
            print(c.method, c.path, json.dumps(c.body))
        return

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    failures = apply(calls, lambda method, path, body: w.api_client.do(method, path, body=body))
    if failures:
        hint = f"\n{UC_HINT}" if any("unity-catalog" in f for f in failures) else ""
        raise SystemExit(f"{len(failures)} of {len(calls)} grants failed.{hint}")
    print(f"Granted {len(principals)} presenter(s): {', '.join(principals)}")


if __name__ == "__main__":
    main(sys.argv[1:])
