import pandas as pd
import pytest

from cropplan.data import WINDOWS, ScenarioInputs, empty_fixed_requests


def tiny_inputs(fixed: list[tuple[str, str, str | None]] | None = None) -> ScenarioInputs:
    """5 fields x 100 acres, 2 hybrids, 1 region. Hand-checkable optimum (see test_model.py).

    HA: yield 10/9/8/7 by window, plentiful. HB: yield 12/11/10/9, only 200 units (2 fields).
    Seed cost 0, units_per_acre 1, price 1 -> margin = 100 * yield. W1 capacity 300 acres.
    """
    fields = pd.DataFrame({
        "field_id": [f"F{i}" for i in range(1, 6)],
        "grower_id": ["G1", "G1", "G1", "G2", "G2"],
        "region": "R1", "acres": 100.0, "lat": 41.0, "lon": -93.0, "soil_class": "A",
        "rm_min": 95, "rm_max": 110,
    })
    hybrids = pd.DataFrame({
        "hybrid_id": ["HA", "HB"], "relative_maturity": [100, 105], "seed_cost_per_unit": 0.0,
        "units_per_acre": 1.0, "disease_tolerance": "medium",
    })
    seed_supply = pd.DataFrame({"season": 2027, "hybrid_id": ["HA", "HB"], "units_available": [1000.0, 200.0]})
    yields = {"HA": [10, 9, 8, 7], "HB": [12, 11, 10, 9]}
    yield_forecast = pd.DataFrame([
        {"region": "R1", "soil_class": "A", "hybrid_id": h, "window": w, "exp_yield_bu_ac": float(y),
         "yield_sd": 1.0, "source_model_version": "test"}
        for h, ys in yields.items() for w, y in zip(WINDOWS, ys)
    ])
    planting_capacity = pd.DataFrame({"region": "R1", "window": list(WINDOWS),
                                      "acres_capacity": [300.0, 1000.0, 1000.0, 1000.0]})
    fixed_requests = (pd.DataFrame(fixed, columns=["field_id", "hybrid_id", "window"])
                      if fixed else empty_fixed_requests())
    return ScenarioInputs(2027, fields, hybrids, seed_supply, yield_forecast, planting_capacity, fixed_requests)


@pytest.fixture
def tiny():
    return tiny_inputs()


class RecordingRun:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.params: dict = {}
        self.metrics: dict = {}
        self.tags: dict = {}
        self.frames: dict = {}

    def log_params(self, params):
        self.params.update(params)

    def log_metrics(self, metrics):
        self.metrics.update(metrics)

    def set_tags(self, tags):
        self.tags.update(tags)

    def log_frame(self, name, frame):
        self.frames[name] = frame.copy()


class RecordingTracker:
    """Stands in for MlflowTracker in unit tests; records every run it opens."""

    def __init__(self) -> None:
        self.runs: list[RecordingRun] = []
        self.ended: list[str] = []

    def start_run(self, run_name, tags):
        from contextlib import contextmanager

        @contextmanager
        def cm():
            run = RecordingRun(f"mlflow-{len(self.runs) + 1}")
            run.name = run_name
            run.set_tags(tags)
            self.runs.append(run)
            try:
                yield run
            except Exception:
                self.ended.append("FAILED")
                raise
            self.ended.append("FINISHED")
        return cm()


# The scripts (scripts/*.py) import each other by module name, as `uv run python scripts/x.py` does.
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
