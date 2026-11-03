"""Shared helpers for the scripts/*.py tools: .env, the deployed bundle target, and SQL through its warehouse.

The pure parts (dotenv parsing, reading a bundle summary) are unit-tested; `Sql` and `load_target` talk to the
workspace and import databricks-sdk only when called, so CI's unit tests don't need it.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deploy_agent import BUNDLE_DIR, ROOT, run

SEEDED = ("baseline-2027", "grower-commitments-2027", "revision-1-2027")
PRECOMPUTED_STRESS = ("stress-baseline-2027-n500", "stress-revision-1-2027-n500")


def in_list(ids: list[str] | tuple[str, ...]) -> str:
    """('a', 'b') for SQL. IDs are check_id-safe (letters, digits, . _ -), so quoting them is enough."""
    from cropplan_jobs.tables import check_id

    return "(" + ", ".join(f"'{check_id(i)}'" for i in ids) + ")"


def read_dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments skipped; optional surrounding quotes removed. Missing file = {}."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def split_list(value: str | None) -> list[str]:
    """'a@x.com, Planners ,,b@x.com' -> ['a@x.com', 'Planners', 'b@x.com'] (order kept, duplicates dropped)."""
    seen: dict[str, None] = {}
    for item in (value or "").split(","):
        if item.strip():
            seen.setdefault(item.strip(), None)
    return list(seen)


@dataclass(frozen=True)
class Target:
    """What the scripts need to know about one deployed bundle target, read from `databricks bundle summary`."""
    profile: str
    target: str
    catalog: str
    schema: str
    warehouse_id: str
    studio_app: str
    space_id: str | None
    experiment_id: str | None
    jobs: dict[str, int]

    def fq(self, table: str) -> str:
        return f"`{self.catalog}`.`{self.schema}`.`{table}`"


def target_from_summary(summary: dict[str, Any], profile: str, target: str) -> Target:
    res, var = summary.get("resources", {}), summary.get("variables", {})
    jobs = {k: int(v["id"]) for k, v in res.get("jobs", {}).items() if v.get("id")}
    return Target(
        profile=profile, target=target, catalog=var["catalog"]["value"],
        schema=res.get("schemas", {}).get("crop_plan", {}).get("name") or var["schema"]["value"],
        warehouse_id=var["warehouse_id"]["value"], studio_app=res["apps"]["crop_plan_studio"]["name"],
        space_id=res.get("genie_spaces", {}).get("crop_plan_results", {}).get("id"),
        experiment_id=res.get("experiments", {}).get("scenarios", {}).get("id"), jobs=jobs)


def bundle_json(command: str, profile: str, target: str) -> dict[str, Any]:
    """`databricks bundle summary|validate -o json` for a target (run in bundle/)."""
    return json.loads(run(["databricks", "bundle", command, "-t", target, "-o", "json", "--profile", profile],
                          cwd=BUNDLE_DIR, capture=True))


def load_target(profile: str, target: str) -> Target:
    return target_from_summary(bundle_json("summary", profile, target), profile, target)


class Sql:
    """Statements through the target's SQL warehouse as the CLI profile's user. Rows come back as dicts of strings."""

    def __init__(self, profile: str, warehouse_id: str) -> None:
        from databricks.sdk import WorkspaceClient

        self.w = WorkspaceClient(profile=profile)
        self.warehouse_id = warehouse_id

    def rows(self, statement: str, **params: object) -> list[dict[str, Any]]:
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        r = self.w.statement_execution.execute_statement(
            statement=statement, warehouse_id=self.warehouse_id, wait_timeout="50s",
            parameters=[StatementParameterListItem(name=k, value=str(v)) for k, v in params.items()])
        while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(3)
            r = self.w.statement_execution.get_statement(r.statement_id)
        if r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"SQL failed ({r.status.state.value}): {r.status.error and r.status.error.message}\n{statement}")
        if not r.manifest or not r.manifest.schema or not r.manifest.schema.columns:
            return []
        cols = [c.name for c in r.manifest.schema.columns]
        return [dict(zip(cols, row)) for row in (r.result.data_array or [])] if r.result else []
