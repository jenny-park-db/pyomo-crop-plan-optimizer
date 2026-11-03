"""The planning agent's solver tools (spec §7). Each one calls Crop Plan Studio as the calling user.

``studio_for`` returns a StudioClient bound to the current request's user, so these tools are built
per request inside ``create_agent_graph`` and never live in ``agent/tools/``.
"""

from __future__ import annotations

import random
import string
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from langchain_core.tools import BaseTool, tool

from agent.studio import StudioClient, StudioError

POLL_BUDGET_S = 240  # spec §7: allows for a serverless cold start on one solve
POLL_EVERY_S = 10
STRESS_DEFAULT_N = 50  # Studio's live-run default; Studio rejects n outside 1..100

_KPI_KEYS = ("gross_margin", "net_margin", "unplanted_penalty_total", "acres_planted_pct", "unplanted_fields",
             "unplanted_acres", "violations_count")


def new_run_id() -> str:
    """Same shape as the app's run IDs (app-<UTC stamp>-<6 chars>), prefixed agent-."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"agent-{stamp}-{tail}"


def _rejected(e: StudioError) -> dict[str, Any]:
    return {"status": "rejected", "http_status": e.status, "error": str(e), "path": e.path}


def _delta(new: dict[str, Any] | None, base: dict[str, Any] | None) -> dict[str, Any] | None:
    if not new or not base:
        return None
    return {k: new[k] - base[k] for k in _KPI_KEYS if new.get(k) is not None and base.get(k) is not None}


def _delta_pct(new: dict[str, Any] | None, base: dict[str, Any] | None) -> dict[str, float] | None:
    """Percent change of the two margins, rounded to 0.01 pt: the agent quotes these instead of dividing itself."""
    if not new or not base:
        return None
    return {k: round((new[k] - base[k]) / abs(base[k]) * 100, 2) for k in ("gross_margin", "net_margin")
            if new.get(k) is not None and base.get(k)}


def build_crop_tools(studio_for: Callable[[], StudioClient], *, sleep: Callable[[float], None] = time.sleep,
                     clock: Callable[[], float] = time.monotonic,
                     run_id: Callable[[], str] = new_run_id) -> list[BaseTool]:
    @tool
    def solve_scenario(base_scenario_id: str, overrides: dict[str, Any], name: str, assumptions: str = "") -> dict[str, Any]:
        """Run a what-if: copy base_scenario_id as a new scenario called `name`, apply `overrides`, and solve it.

        Use for any plan change (seed supply, planting capacity or weather, diversity cap, prices, penalties).
        overrides keys (all optional): supply_pct {hybrid_id: multiplier}, capacity_pct {region: {window: multiplier}}
        with regions IA/IL/NE and windows W1-W4, diversity_cap (0-1], unplanted_penalty_per_acre, corn_price_per_bu,
        fixed_requests_enabled (bool). Multipliers are fractions of the base value (0.5 = half). Put any assumption
        you made translating the request (e.g. "one week delay = 25% of W2 capacity lost") in `assumptions`.
        Waits up to 4 minutes; returns KPIs, the change versus the base scenario (absolute and percent), hybrids at their supply limit,
        violations or the infeasibility reason, and the new scenario_id. On timeout returns the run_id and status.
        """
        studio = studio_for()
        rid = run_id()
        try:
            submitted = studio.submit({"mode": "new", "source": "agent", "source_scenario_id": base_scenario_id,
                                       "run_id": rid, "name": name, "overrides": overrides})
        except StudioError as e:
            if e.status < 500:
                return _rejected(e)
            # No answer (or a 5xx) after sending: the scenario and run may exist; a retry would duplicate them.
            return {"run_id": rid, "status": "unknown", "error": str(e),
                    "message": f"Crop Plan Studio did not confirm the submit; the run may have started. Check the Runs "
                               f"screen for run {rid} before trying again."}
        deadline = clock() + POLL_BUDGET_S
        try:
            rep = studio.run_report(rid)
            while not rep.get("final") and clock() < deadline:
                sleep(min(POLL_EVERY_S, max(0.0, deadline - clock())))
                rep = studio.run_report(rid)
        except StudioError as e:
            # The run was submitted; a failed status read must not lose its ID (the job keeps going).
            scenario_id = submitted.get("scenario_id")
            return {"run_id": rid, "scenario_id": scenario_id, "results_path": f"/results/{scenario_id}",
                    "assumptions": assumptions, "status": "unknown", "error": str(e),
                    "message": f"Submitted, but reading its status failed ({e}); the planner can follow run {rid} "
                               "on the Runs screen."}
        scenario_id = rep.get("scenario_id") or submitted.get("scenario_id")
        common = {"run_id": rid, "scenario_id": scenario_id, "scenario_name": rep.get("scenario_name") or name,
                  "results_path": f"/results/{scenario_id}", "assumptions": assumptions}
        if not rep.get("final"):
            return {**common, "status": rep.get("status"), "timed_out": True,
                    "message": f"Still {rep.get('status')} after {POLL_BUDGET_S} s; the planner can follow it on the Runs screen."}
        try:
            base = studio.scenario_report(base_scenario_id)
            base_view = {"scenario_id": base.get("scenario_id"), "run_id": base.get("run_id"), "kpis": base.get("kpis")}
        except StudioError:
            base_view = None
        kpis = rep.get("kpis")
        return {**common, "status": rep.get("status"), "overrides": rep.get("overrides"), "kpis": kpis,
                "base": base_view, "delta_vs_base": _delta(kpis, base_view and base_view["kpis"]),
                "delta_pct_vs_base": _delta_pct(kpis, base_view and base_view["kpis"]),
                "hybrids_at_supply_limit": rep.get("hybrids_at_supply_limit", []), "violations": rep.get("violations", []),
                "infeasibility_reason": rep.get("infeasibility_reason"), "diagnosis": rep.get("diagnosis"),
                "error": rep.get("error"), "termination": rep.get("termination"), "mip_gap": rep.get("mip_gap")}

    @tool
    def stress_test_plan(scenario_id: str, n: int = STRESS_DEFAULT_N) -> dict[str, Any]:
        """Start a stress test of a solved scenario: n random disruptions (seed shortfalls, lost capacity and acres).

        Use for robustness questions ("how fragile is this plan?"). n is 1-100 (default 50); it takes several
        minutes, so return the stress_id to the planner and check it later with get_stress_test.
        """
        try:
            started = studio_for().start_stress(scenario_id, n)
        except StudioError as e:
            return _rejected(e)
        # Studio's reply goes first, so a status or scenario_id field in it can't mask that the test started.
        return {**started, "status": "started", "scenario_id": scenario_id,
                "message": (f"Started {started.get('n', n)} disruption samples (seed shortfall per hybrid, lost planting "
                            "capacity per region and window, lost acres per region), each re-solved; this takes about "
                            "3-8 minutes. Call get_stress_test with this stress_id for the results.")}

    @tool
    def get_stress_test(stress_id: str) -> dict[str, Any]:
        """Get a stress test by stress_id: state running/failed/done and, when done, the P10/P50/P90 gross margin,
        sample counts by outcome, the fragile fields and hybrids, and p90_minus_p10 (the spread)."""
        try:
            out = studio_for().stress_result(stress_id)
        except StudioError as e:
            return _rejected(e)
        summary = out.get("summary") or {}
        if summary.get("p10_gross_margin") is not None and summary.get("p90_gross_margin") is not None:
            summary["p90_minus_p10"] = summary["p90_gross_margin"] - summary["p10_gross_margin"]
        return out

    return [solve_scenario, stress_test_plan, get_stress_test]
