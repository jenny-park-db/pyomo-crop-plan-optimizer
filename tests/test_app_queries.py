"""Static checks on the app's SQL files (app/config/queries/*.obo.sql); tests/integration runs them against a workspace."""

import re
from pathlib import Path

import pytest

from cropplan_jobs.tables import TABLES

QUERIES = sorted((Path(__file__).resolve().parents[1] / "app" / "config" / "queries").glob("*.sql"))
TABLE_REF = re.compile(r"IDENTIFIER\(:catalog \|\| '\.' \|\| :schema \|\| '\.(\w+)'\)")


def test_the_app_has_its_queries():
    assert {q.name for q in QUERIES} == {
        "plan_rows.obo.sql", "run_summary.obo.sql", "runs.obo.sql", "scenario_inputs.obo.sql", "scenarios.obo.sql",
        "seed_utilization.obo.sql", "stress_margins.obo.sql", "stress_summaries.obo.sql", "violations.obo.sql"}


@pytest.mark.parametrize("path", QUERIES, ids=lambda p: p.name)
def test_query_runs_as_the_user_on_bundle_tables_and_takes_refresh(path):
    text = path.read_text()
    assert path.name.endswith(".obo.sql"), "every read runs as the signed-in user"
    for param in ("catalog STRING", "schema STRING", "refresh INT"):
        assert f"-- @param {param}" in text, param
    body = "\n".join(line for line in text.splitlines() if not line.startswith("--"))
    assert ":refresh" in body, "an unused parameter would not change the request, so refresh would not re-run it"
    assert "pyomo_crop_plan_demo_catalog" not in body and "crop_plan." not in body
    tables = set(TABLE_REF.findall(body))
    assert tables and tables <= set(TABLES), tables - set(TABLES)


@pytest.mark.parametrize("path", QUERIES, ids=lambda p: p.name)
def test_timestamps_are_read_as_epoch_millis(path):
    """The browser never parses a TIMESTAMP string, so the warehouse session time zone can't skew times."""
    body = "\n".join(line for line in path.read_text().splitlines() if not line.startswith("--"))
    selected = re.findall(r"unix_millis\([\w.]+\) AS (\w+)", body)
    assert all(name.endswith("_ms") for name in selected), selected
    select_list = body.split("FROM")[0]
    assert not re.search(r"\b\w+\.(created_at|started_at|ended_at|submitted_at)\s*(,|$)", select_list, re.M), select_list
