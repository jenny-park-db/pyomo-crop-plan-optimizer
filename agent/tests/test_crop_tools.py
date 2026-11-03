import pytest
from agent.crop_tools import POLL_BUDGET_S, POLL_EVERY_S, build_crop_tools, new_run_id
from agent.studio import StudioError

BASE_KPIS = {"gross_margin": 18810000.0, "net_margin": 18708000.0, "unplanted_penalty_total": 102000.0,
             "acres_planted_pct": 0.973, "unplanted_fields": 4, "unplanted_acres": 680.0, "violations_count": 0}
NEW_KPIS = {"gross_margin": 18512345.5, "net_margin": 18290000.25, "unplanted_penalty_total": 222345.25,
            "acres_planted_pct": 0.951, "unplanted_fields": 9, "unplanted_acres": 1180.5, "violations_count": 0}


def report(status, kpis=None, **extra):
    return {"run_id": "agent-20261102101500-abcdef", "scenario_id": "ia-w1-half-abcdef", "scenario_name": "IA W1 half",
            "status": status, "final": status in ("done", "invalid", "infeasible", "failed"), "kpis": kpis,
            "hybrids_at_supply_limit": [], "violations": [], "infeasibility_reason": None, "diagnosis": None,
            "error": None, "overrides": {"capacity_pct": {"IA": {"W1": 0.5}}}, **extra}


class FakeStudio:
    def __init__(self, reports=(), submit_error=None, base=None):
        self.reports = list(reports)
        self.submit_error = submit_error
        self.base = base if base is not None else {"run_id": "run-base", "scenario_id": "baseline-2027", "kpis": BASE_KPIS}
        self.submitted = []
        self.stress = []

    def submit(self, body):
        if self.submit_error:
            raise self.submit_error
        self.submitted.append(body)
        return {"run_id": body["run_id"], "scenario_id": "ia-w1-half-abcdef", "status": "queued", "deduped": False}

    def run_report(self, run_id):
        return self.reports.pop(0) if len(self.reports) > 1 else self.reports[0]

    def scenario_report(self, scenario_id):
        if isinstance(self.base, Exception):
            raise self.base
        return self.base

    def start_stress(self, scenario_id, n):
        self.stress.append((scenario_id, n))
        if scenario_id == "busy-2027":
            raise StudioError(409, "A live stress test for busy-2027 is already running")
        return {"stress_id": f"st-x-n{n}-{scenario_id}", "job_run_id": "555", "n": n}

    def stress_result(self, stress_id):
        return {"stress_id": stress_id, "state": "running", "summary": None}


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def tools(studio, clock=None):
    clock = clock or Clock()
    built = build_crop_tools(lambda: studio, sleep=clock.sleep, clock=clock.now, run_id=lambda: "agent-20261102101500-abcdef")
    return {t.name: t for t in built}, clock


ARGS = {"base_scenario_id": "baseline-2027", "overrides": {"capacity_pct": {"IA": {"W1": 0.5}}},
        "name": "IA W1 half", "assumptions": "rain removes half of Iowa's W1 planting capacity"}


def test_tool_names_and_arguments_match_the_spec():
    t, _ = tools(FakeStudio([report("done", NEW_KPIS)]))
    assert set(t) == {"solve_scenario", "stress_test_plan", "get_stress_test"}
    assert set(t["solve_scenario"].args) == {"base_scenario_id", "overrides", "name", "assumptions"}
    assert set(t["stress_test_plan"].args) == {"scenario_id", "n"}
    assert set(t["get_stress_test"].args) == {"stress_id"}


def test_solve_submits_an_agent_scenario_through_studio_and_reports_kpis_with_deltas():
    studio = FakeStudio([report("queued"), report("solving"), report("done", NEW_KPIS, hybrids_at_supply_limit=["H-112"])])
    t, clock = tools(studio)
    out = t["solve_scenario"].invoke(ARGS)
    assert studio.submitted == [{"mode": "new", "source": "agent", "source_scenario_id": "baseline-2027",
                                 "run_id": "agent-20261102101500-abcdef", "name": "IA W1 half",
                                 "overrides": {"capacity_pct": {"IA": {"W1": 0.5}}}}]
    assert out["status"] == "done" and out["scenario_id"] == "ia-w1-half-abcdef"
    assert out["results_path"] == "/results/ia-w1-half-abcdef"
    assert out["assumptions"] == ARGS["assumptions"]
    assert out["kpis"] == NEW_KPIS and out["base"] == {"scenario_id": "baseline-2027", "run_id": "run-base", "kpis": BASE_KPIS}
    assert out["delta_vs_base"]["gross_margin"] == pytest.approx(18512345.5 - 18810000.0)
    assert out["delta_vs_base"]["unplanted_fields"] == 5
    assert out["delta_vs_base"]["unplanted_acres"] == 500.5
    # Percent changes are computed here, so a reply that says "-1.6%" cites a tool number, not its own arithmetic.
    assert out["delta_pct_vs_base"] == {"gross_margin": -1.58, "net_margin": -2.23}
    assert out["hybrids_at_supply_limit"] == ["H-112"]
    assert clock.sleeps == [POLL_EVERY_S, POLL_EVERY_S]


def test_an_infeasible_run_returns_its_reason_and_binding_constraint_without_deltas():
    binding = [{"rule": "capacity", "entity": "IA/W1", "severity": "binding", "detail": "short by 290 acres"}]
    studio = FakeStudio([report("infeasible", None, infeasibility_reason="Planting capacity IA/W1 short by 290 acres",
                                diagnosis="explained", violations=binding)])
    out = tools(studio)[0]["solve_scenario"].invoke(ARGS)
    assert (out["status"], out["kpis"], out["delta_vs_base"], out["delta_pct_vs_base"]) == ("infeasible", None, None, None)
    assert out["infeasibility_reason"] == "Planting capacity IA/W1 short by 290 acres"
    assert out["violations"] == binding


def test_after_240_s_the_tool_returns_the_run_id_and_current_status():
    studio = FakeStudio([report("solving")])
    out, clock = None, Clock()
    out = tools(studio, clock)[0]["solve_scenario"].invoke(ARGS)
    assert out["timed_out"] is True and out["status"] == "solving" and out["run_id"] == "agent-20261102101500-abcdef"
    assert "Runs" in out["message"]
    assert clock.t == POLL_BUDGET_S == 240


def test_a_rejected_submit_comes_back_as_data_the_agent_can_fix():
    studio = FakeStudio(submit_error=StudioError(400, "diversity_cap must be a finite number, got '0.4'", "diversity_cap"))
    out = tools(studio)[0]["solve_scenario"].invoke({**ARGS, "overrides": {"diversity_cap": "0.4"}})
    assert out == {"status": "rejected", "http_status": 400, "error": "diversity_cap must be a finite number, got '0.4'",
                   "path": "diversity_cap"}


def test_a_missing_base_report_still_returns_the_new_numbers():
    studio = FakeStudio([report("done", NEW_KPIS)], base=StudioError(404, "Scenario x has no finished run"))
    out = tools(studio)[0]["solve_scenario"].invoke(ARGS)
    assert out["kpis"] == NEW_KPIS and out["base"] is None and out["delta_vs_base"] is None


def test_stress_test_plan_defaults_to_50_and_reports_a_busy_scenario():
    studio = FakeStudio()
    t, _ = tools(studio)
    started = t["stress_test_plan"].invoke({"scenario_id": "revision-1-2027"})
    assert studio.stress == [("revision-1-2027", 50)]
    assert started["status"] == "started" and started["stress_id"] == "st-x-n50-revision-1-2027"
    assert "seed shortfall per hybrid" in started["message"]  # what the samples are, so the reply can say it
    busy = t["stress_test_plan"].invoke({"scenario_id": "busy-2027", "n": 20})
    assert busy["status"] == "rejected" and busy["http_status"] == 409


def test_get_stress_test_passes_a_running_result_through():
    assert tools(FakeStudio())[0]["get_stress_test"].invoke({"stress_id": "st-1"}) == {
        "stress_id": "st-1", "state": "running", "summary": None}


def test_a_finished_stress_test_also_carries_its_p10_to_p90_spread():
    studio = FakeStudio()
    studio.stress_result = lambda stress_id: {"stress_id": stress_id, "state": "done", "summary": {
        "n": 500, "p10_gross_margin": 17806807.975, "p50_gross_margin": 18590000.0, "p90_gross_margin": 18779418.75}}
    out = tools(studio)[0]["get_stress_test"].invoke({"stress_id": "stress-revision-1-2027-n500"})
    assert out["summary"]["p90_minus_p10"] == pytest.approx(972610.775)


def test_new_run_ids_are_valid_studio_ids():
    rid = new_run_id()
    assert rid.startswith("agent-") and len(rid) == len("agent-20261102101500-abcdef")


def test_a_studio_error_while_waiting_returns_the_run_id_instead_of_failing_the_turn():
    studio = FakeStudio([report("solving")])
    calls = {"n": 0}

    def flaky(run_id):
        calls["n"] += 1
        if calls["n"] == 2:
            raise StudioError(502, "Bad gateway")
        return report("solving")

    studio.run_report = flaky
    out = tools(studio)[0]["solve_scenario"].invoke(ARGS)
    assert out["status"] == "unknown" and out["run_id"] == "agent-20261102101500-abcdef"
    assert out["scenario_id"] == "ia-w1-half-abcdef" and "Runs" in out["message"]


def test_a_submit_that_gets_no_answer_says_it_may_have_started_instead_of_rejected():
    studio = FakeStudio(submit_error=StudioError(504, "Crop Plan Studio did not answer: timed out"))
    out = tools(studio)[0]["solve_scenario"].invoke(ARGS)
    assert out["status"] == "unknown" and out["run_id"] == "agent-20261102101500-abcdef"
    assert "may have started" in out["message"]


def test_a_status_field_in_studios_stress_reply_cannot_mask_that_the_test_started():
    class StatusEchoStudio(FakeStudio):
        def start_stress(self, scenario_id, n):
            return {"stress_id": "st-y", "job_run_id": "7", "n": n, "status": "queued", "scenario_id": "other"}
    started = tools(StatusEchoStudio())[0]["stress_test_plan"].invoke({"scenario_id": "revision-1-2027"})
    assert started["status"] == "started" and started["scenario_id"] == "revision-1-2027"
    assert started["stress_id"] == "st-y"
