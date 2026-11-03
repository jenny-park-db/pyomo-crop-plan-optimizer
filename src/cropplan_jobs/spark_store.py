"""TableStore over Unity Catalog Delta tables. Runs only where a Spark session exists (serverless job tasks)."""

from __future__ import annotations

import random
import time
from typing import Any

import pandas as pd

from cropplan_jobs.tables import TABLES, add_columns_ddl, check_id, conform, ddl

RETRIES = 6  # ~30 s of jittered backoff: enough for a burst of queued solves committing at once


def _spark_type(sql_type: str):
    from pyspark.sql import types as T
    if sql_type == "ARRAY<STRING>":
        return T.ArrayType(T.StringType())
    return {"STRING": T.StringType(), "DOUBLE": T.DoubleType(), "INT": T.IntegerType(),
            "BOOLEAN": T.BooleanType(), "TIMESTAMP": T.TimestampType()}[sql_type]


def spark_schema(table: str):
    from pyspark.sql import types as T
    return T.StructType([T.StructField(c, _spark_type(t), True) for c, t in TABLES[table].items()])


def _retry(fn):
    """Retry Delta write conflicts (two jobs committing to one table at once); re-raise anything else."""
    for attempt in range(RETRIES):
        try:
            return fn()
        except Exception as exc:  # pyspark raises several conflict classes; match on the name
            conflict = "Concurrent" in type(exc).__name__ or "CONCURRENT" in str(exc)
            if not conflict or attempt == RETRIES - 1:
                raise
            time.sleep(min(2 ** attempt, 8) * random.uniform(0.75, 1.5))


def _literal_predicate(where: dict[str, Any]) -> str:
    """replaceWhere takes a SQL string, not parameters, so only check_id-safe string values are allowed."""
    if not where:
        raise ValueError("replace needs at least one key column")
    return " AND ".join(f"`{c}` = '{check_id(v, c)}'" for c, v in where.items())


def _params(where: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not where:
        return "TRUE", {}
    return " AND ".join(f"`{c}` = :w_{c}" for c in where), {f"w_{c}": v for c, v in where.items()}


class SparkStore:
    def __init__(self, spark, catalog: str, schema: str) -> None:
        self.spark, self.catalog, self.schema = spark, catalog, schema

    def name(self, table: str) -> str:
        if table not in TABLES:
            raise KeyError(f"unknown table {table!r}")
        return f"`{self.catalog}`.`{self.schema}`.`{table}`"

    def create_tables(self) -> None:
        """Create missing tables and add contract columns that existing tables lack. Safe to re-run."""
        for table in TABLES:
            self.spark.sql(ddl(table, self.catalog, self.schema))
            alter = add_columns_ddl(table, self.catalog, self.schema, set(self.spark.table(self.name(table)).columns))
            if alter:
                self.spark.sql(alter)

    def read(self, table: str, **where: Any) -> pd.DataFrame:
        clause, args = _params(where)
        cols = ", ".join(f"`{c}`" for c in TABLES[table])
        pdf = self.spark.sql(f"SELECT {cols} FROM {self.name(table)} WHERE {clause}", args=args).toPandas()
        return conform(table, pdf)

    def _frame(self, table: str, rows: pd.DataFrame):
        pdf = conform(table, rows)
        pdf = pdf.astype(object).where(pdf.notna(), None)
        return self.spark.createDataFrame(pdf, schema=spark_schema(table))

    def append(self, table: str, rows: pd.DataFrame) -> None:
        if rows.empty:
            return
        df = self._frame(table, rows)
        _retry(lambda: df.write.mode("append").saveAsTable(self.name(table)))

    def replace(self, table: str, rows: pd.DataFrame, **where: Any) -> None:
        predicate = _literal_predicate(where)
        if rows.empty:
            _retry(lambda: self.spark.sql(f"DELETE FROM {self.name(table)} WHERE {predicate}"))
            return
        df = self._frame(table, rows)
        _retry(lambda: df.write.mode("overwrite").option("replaceWhere", predicate).saveAsTable(self.name(table)))

    def update(self, table: str, values: dict[str, Any], **where: Any) -> None:
        unknown = [c for c in values if c not in TABLES[table]]
        if unknown:
            raise KeyError(f"{table} has no columns {unknown}")
        clause, args = _params(where)
        sets = []
        for c, v in values.items():
            if v is None:
                sets.append(f"`{c}` = NULL")
            else:
                sets.append(f"`{c}` = CAST(:v_{c} AS {TABLES[table][c]})")
                args[f"v_{c}"] = v
        sql = f"UPDATE {self.name(table)} SET {', '.join(sets)} WHERE {clause}"
        _retry(lambda: self.spark.sql(sql, args=args))
