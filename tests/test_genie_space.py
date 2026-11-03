"""Static checks on the Genie space definition. The create API rejects unsorted lists and bad ids outright,
and a wrong table or column name only shows up when a planner asks a question."""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from cropplan_jobs.tables import TABLES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPACE_FILE = ROOT / "genie" / "crop_plan_results.yml"
PREFIX = "${var.catalog}.${var.schema}."
SPACE_TABLES = ["fields", "hybrids", "plan_assignments", "run_summary", "runs", "scenarios", "seed_utilization",
                "stress_test_summary", "violations"]
TABLE_REF = re.compile(r"\$\{var\.catalog\}\.\$\{var\.schema\}\.(\w+)")
ALIASED = re.compile(r"\$\{var\.catalog\}\.\$\{var\.schema\}\.(\w+)\s+(?:AS\s+)?([a-z])\b", re.IGNORECASE)


def _resource() -> dict:
    return yaml.safe_load(SPACE_FILE.read_text())["resources"]["genie_spaces"]["crop_plan_results"]


def _space() -> dict:
    return _resource()["serialized_space"]


def _examples() -> list[dict]:
    return _space()["instructions"]["example_question_sqls"]


def test_space_covers_the_spec_tables_sorted_by_identifier():
    ids = [t["identifier"] for t in _space()["data_sources"]["tables"]]
    assert ids == sorted(ids) == [PREFIX + t for t in SPACE_TABLES]


def test_ids_are_unique_32_hex_and_sorted_within_each_list():
    space = _space()
    lists = {"sample_questions": space["config"]["sample_questions"],
             "text_instructions": space["instructions"]["text_instructions"],
             "example_question_sqls": space["instructions"]["example_question_sqls"]}
    seen = set()
    for name, items in lists.items():
        ids = [i["id"] for i in items]
        assert ids == sorted(ids), name
        for i in ids:
            assert re.fullmatch(r"[0-9a-f]{32}", i), i
            assert i not in seen, i
            seen.add(i)


def test_resource_is_parameterized_by_bundle_variables():
    r = _resource()
    assert r["warehouse_id"] == "${var.warehouse_id}" and r["title"] == "${var.genie_title}"
    assert "pyomo_crop_plan_demo_catalog" not in SPACE_FILE.read_text()


def test_instructions_define_every_kpi():
    text = " ".join(" ".join(t["content"]) for t in _space()["instructions"]["text_instructions"]).lower()
    for kpi in ("gross margin", "net margin", "planted %", "seed utilization"):
        assert kpi in text, kpi


def test_about_ten_example_queries_with_one_for_demo_step_6():
    assert 8 <= len(_examples()) <= 12
    questions = [e["question"][0] for e in _examples()]
    assert "Across today's scenarios, which hybrids always hit their supply limit?" in questions


@pytest.mark.parametrize("example", _examples(), ids=lambda e: e["question"][0][:40])
def test_example_sql_uses_only_space_tables_and_known_columns(example):
    sql = "".join(example["sql"])
    used = set(TABLE_REF.findall(sql))
    assert used and used <= set(SPACE_TABLES), used - set(SPACE_TABLES)
    for table, alias in ALIASED.findall(sql):
        for col in re.findall(rf"\b{alias}\.(\w+)", sql):
            assert col in TABLES[table], f"{alias}.{col} is not a column of {table}"
