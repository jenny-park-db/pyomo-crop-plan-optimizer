"""SparkStore's pure helpers; the Spark paths themselves run in the integration test (tests/integration)."""

import pytest

from cropplan_jobs import spark_store
from cropplan_jobs.spark_store import SparkStore, _retry
from cropplan_jobs.tables import TABLES


class ConcurrentAppendException(Exception):
    pass


def test_retry_rides_out_a_burst_of_write_conflicts(monkeypatch):
    sleeps = []
    monkeypatch.setattr(spark_store.time, "sleep", sleeps.append)
    calls = []

    def write():
        calls.append(1)
        if len(calls) <= 5:
            raise ConcurrentAppendException("conflict")
        return "ok"

    assert _retry(write) == "ok" and len(calls) == 6
    assert len(set(sleeps)) == len(sleeps)  # jittered, so colliding writers don't retry in lockstep
    assert 10 <= sum(sleeps) <= 60


def test_retry_reraises_other_errors_immediately(monkeypatch):
    monkeypatch.setattr(spark_store.time, "sleep", lambda s: None)
    calls = []

    def write():
        calls.append(1)
        raise ValueError("bad column")

    with pytest.raises(ValueError):
        _retry(write)
    assert len(calls) == 1


class FakeSpark:
    """Just enough of a SparkSession for create_tables: records SQL, reports each table's current columns."""

    def __init__(self, columns: dict[str, list[str]]):
        self.columns, self.statements = columns, []

    def sql(self, statement, args=None):
        self.statements.append(statement)

    def table(self, name):
        leaf = name.split(".")[-1].strip("`")
        return type("T", (), {"columns": self.columns.get(leaf, list(TABLES[leaf]))})()


def test_create_tables_adds_columns_an_existing_table_lacks():
    old_runs = [c for c in TABLES["runs"] if c not in ("diagnosis", "submitted_at")]
    spark = FakeSpark({"runs": old_runs})
    SparkStore(spark, "cat", "crop_plan").create_tables()
    alters = [s for s in spark.statements if s.startswith("ALTER TABLE")]
    assert alters == ["ALTER TABLE `cat`.`crop_plan`.`runs` ADD COLUMNS (`diagnosis` STRING, `submitted_at` TIMESTAMP)"]
    assert sum(s.startswith("CREATE TABLE IF NOT EXISTS") for s in spark.statements) == len(TABLES)
