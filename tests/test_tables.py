import pandas as pd
import pytest

from cropplan.data import COLUMNS
from cropplan_jobs.tables import INPUTS, SORT_KEYS, TABLES, add_columns_ddl, check_id, conform, ddl


def test_input_tables_match_the_solver_contract():
    for table, cols in COLUMNS.items():
        assert list(INPUTS[table]) == ["scenario_id", *cols]
        assert set(SORT_KEYS[table]) <= set(cols)


@pytest.mark.parametrize("value", ["baseline-2027", "run-123", "a.b_c"])
def test_check_id_accepts_safe_ids(value):
    assert check_id(value) == value


@pytest.mark.parametrize("value", ["", "x' OR '1'='1", "a b", "-lead", "../up", "x" * 65, None, 7, "abc\n"])
def test_check_id_rejects_unsafe_ids(value):
    with pytest.raises(ValueError):
        check_id(value, "scenario_id")


def test_conform_orders_columns_drops_extras_and_rejects_missing():
    rows = pd.DataFrame([{"rule": "r", "entity": "e", "severity": "hard", "detail": "d",
                          "run_id": "r1", "scenario_id": "s1", "extra": 1}])
    assert list(conform("violations", rows).columns) == list(TABLES["violations"])
    with pytest.raises(ValueError, match="missing columns"):
        conform("violations", rows.drop(columns="detail"))


def test_ddl_quotes_names():
    assert ddl("runs", "cat", "crop_plan").startswith("CREATE TABLE IF NOT EXISTS `cat`.`crop_plan`.`runs` (`run_id` STRING")


def test_conform_drops_attrs_so_spark_frames_can_be_written_to_parquet(tmp_path):
    rows = pd.DataFrame([{"scenario_id": "s1", "region": "IA", "window": "W1", "acres_capacity": 1.0}])
    rows.attrs["metrics"] = object()  # what Spark Connect's toPandas() leaves behind
    out = conform("planting_capacity", rows)
    assert out.attrs == {}
    out.to_parquet(tmp_path / "x.parquet")


def test_runs_contract_has_the_plan_3_columns_last():
    assert list(TABLES["runs"])[-2:] == ["diagnosis", "submitted_at"]
    assert TABLES["runs"]["submitted_at"] == "TIMESTAMP"


def test_add_columns_ddl_adds_only_what_an_old_table_lacks():
    old = set(TABLES["runs"]) - {"diagnosis", "submitted_at"}
    assert add_columns_ddl("runs", "cat", "crop_plan", old) == (
        "ALTER TABLE `cat`.`crop_plan`.`runs` ADD COLUMNS (`diagnosis` STRING, `submitted_at` TIMESTAMP)")
    assert add_columns_ddl("runs", "cat", "crop_plan", set(TABLES["runs"])) is None
