import pandas as pd
import pytest

from cropplan_jobs.store import MemoryStore, ensure_row


def _run(run_id, status="queued"):
    return {"run_id": run_id, "scenario_id": "s1", "status": status}


def test_read_filters_by_columns():
    s = MemoryStore()
    ensure_row(s, "runs", _run("r1"), run_id="r1")
    ensure_row(s, "runs", _run("r2"), run_id="r2")
    assert list(s.read("runs", run_id="r2")["run_id"]) == ["r2"]
    assert len(s.read("runs")) == 2
    with pytest.raises(KeyError):
        s.read("runs", nope=1)


def test_ensure_row_inserts_once():
    s = MemoryStore()
    assert ensure_row(s, "runs", _run("r1"), run_id="r1") is True
    assert ensure_row(s, "runs", _run("r1", "done"), run_id="r1") is False
    assert s.read("runs")["status"].tolist() == ["queued"]


def test_replace_swaps_only_matching_rows():
    s = MemoryStore()
    rows = lambda run, n: pd.DataFrame([{"scenario_id": "s1", "run_id": run, "rule": f"r{i}", "entity": "e",
                                         "severity": "hard", "detail": ""} for i in range(n)])
    s.append("violations", rows("a", 2))
    s.append("violations", rows("b", 1))
    s.replace("violations", rows("a", 3), run_id="a")
    s.replace("violations", rows("a", 3), run_id="a")  # retried write: still 3, not 6
    assert s.read("violations", run_id="a").shape[0] == 3
    assert s.read("violations", run_id="b").shape[0] == 1


def test_update_sets_values_and_rejects_unknown_columns():
    s = MemoryStore()
    ensure_row(s, "runs", _run("r1"), run_id="r1")
    s.update("runs", {"status": "done", "objective": 5.0}, run_id="r1")
    row = s.read("runs", run_id="r1").iloc[0]
    assert (row["status"], row["objective"]) == ("done", 5.0)
    with pytest.raises(KeyError):
        s.update("runs", {"nope": 1}, run_id="r1")
