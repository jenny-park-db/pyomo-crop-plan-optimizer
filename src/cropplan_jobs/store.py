"""The narrow storage interface the jobs use, plus a pandas implementation for unit tests."""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from cropplan_jobs.tables import TABLES, conform


class TableStore(Protocol):
    def read(self, table: str, **where: Any) -> pd.DataFrame:
        """Rows where every ``column == value`` in ``where`` (all rows if empty), in table column order."""

    def append(self, table: str, rows: pd.DataFrame) -> None:
        """Add rows. Columns are conformed to the table contract first."""

    def replace(self, table: str, rows: pd.DataFrame, **where: Any) -> None:
        """Swap the rows matching ``where`` for ``rows``. Makes a retried write idempotent."""

    def update(self, table: str, values: dict[str, Any], **where: Any) -> None:
        """Set ``values`` on the rows matching ``where``."""


def ensure_row(store: TableStore, table: str, row: dict[str, Any], **key: Any) -> bool:
    """Insert ``row`` unless a row matching ``key`` exists. Returns True when it inserted."""
    if not store.read(table, **key).empty:
        return False
    store.append(table, pd.DataFrame([{c: row.get(c) for c in TABLES[table]}]))
    return True


class MemoryStore:
    """pandas-backed TableStore with the same column contracts as the UC tables."""

    def __init__(self) -> None:
        self.frames: dict[str, pd.DataFrame] = {
            t: conform(t, pd.DataFrame({c: pd.Series(dtype=object) for c in cols})) for t, cols in TABLES.items()
        }

    def _mask(self, table: str, where: dict[str, Any]) -> pd.Series:
        frame = self.frames[table]
        mask = pd.Series(True, index=frame.index)
        for col, value in where.items():
            if col not in TABLES[table]:
                raise KeyError(f"{table} has no column {col!r}")
            mask &= frame[col] == value
        return mask

    def read(self, table: str, **where: Any) -> pd.DataFrame:
        return self.frames[table][self._mask(table, where)].reset_index(drop=True).copy()

    def append(self, table: str, rows: pd.DataFrame) -> None:
        if rows.empty:
            return
        new = conform(table, rows)
        frame = self.frames[table]
        self.frames[table] = new if frame.empty else pd.concat([frame, new], ignore_index=True)

    def replace(self, table: str, rows: pd.DataFrame, **where: Any) -> None:
        self.frames[table] = self.frames[table][~self._mask(table, where)].reset_index(drop=True)
        self.append(table, rows)

    def update(self, table: str, values: dict[str, Any], **where: Any) -> None:
        unknown = [c for c in values if c not in TABLES[table]]
        if unknown:
            raise KeyError(f"{table} has no columns {unknown}")
        mask = self._mask(table, where)
        frame = self.frames[table].astype(object)
        for col, value in values.items():
            frame.loc[mask, col] = value
        self.frames[table] = conform(table, frame)
