"""Walk the spec §10 demo at the API level against a deployed target (the bootstrap's last step).

    make smoke PROFILE=<p> [TARGET=dev]
    uv run python scripts/smoke_test.py --profile <p> [--target dev] [--skip-agent] [--keep-scenario]

Checks, as the CLI profile's user:
  1-2  seeded scenarios present (150 fields each); the precompute baseline solve is done with an MLflow run,
       the expected gross margin, and 4 unplanted fields
  3    revision-1-2027 is done and beats the baseline on gross margin
  4    grower-commitments-2027 is infeasible, with the binding IA/W1 capacity shortfall named
  7    both stored N=500 stress tests are there, and revision 1's P10 gross margin is higher
       Crop Plan Studio answers (/api/studio/whoami, /config with the agent URL, /results/baseline-2027)
  6    the agent answers "which hybrids always hit their supply limit?" through Genie, with SQL
  5    the agent's "Iowa loses half its W1 capacity" what-if creates and solves an agent scenario
       (then deleted again, so the demo's Genie answer isn't changed by it; --keep-scenario keeps it)
Exit status 1 if any check fails. Takes ~5 minutes with the agent turns (~20 s with --skip-agent).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import reset_demo
from demo_env import PRECOMPUTED_STRESS, SEEDED, Sql, Target, in_list, load_target

# Spec §11: deterministic data and single-thread HiGHS, so a rebuild reproduces these.
BASELINE_GROSS = 18_811_018.0
REVISION_GROSS = 18_839_272.0
GENIE_QUESTION = "Across today's scenarios, which hybrids always hit their supply limit?"
WHAT_IF = "What if Iowa loses half its W1 planting capacity to rain?"
TURN_TIMEOUT_S = 600


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def close(a: float, b: float, rel: float = 1e-6) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1.0)


def check_seeded(counts: dict[str, int]) -> Check:
    ok = all(counts.get(s) == 150 for s in SEEDED)
    return Check("seeded scenarios", ok, ", ".join(f"{s}={counts.get(s, 0)} fields" for s in SEEDED))


def check_baseline(row: dict[str, Any] | None) -> Check:
    if not row:
        return Check("baseline solve", False, "no precompute run for baseline-2027")
    gross = float(row["gross_margin"] or "nan")
    ok = (row["status"] == "done" and row["mlflow_run_id"] is not None and int(row["unplanted_fields"] or -1) == 4
          and close(gross, BASELINE_GROSS))
    return Check("baseline solve", ok, f"status={row['status']} gross={gross:,.0f} (expected {BASELINE_GROSS:,.0f}) "
                                       f"unplanted={row['unplanted_fields']} mlflow_run={row['mlflow_run_id']}")


def check_revision(row: dict[str, Any] | None) -> Check:
    if not row:
        return Check("revision 1 solve", False, "no precompute run for revision-1-2027")
    gross = float(row["gross_margin"] or "nan")
    ok = row["status"] == "done" and close(gross, REVISION_GROSS) and gross > BASELINE_GROSS
    return Check("revision 1 solve", ok, f"status={row['status']} gross={gross:,.0f} (expected {REVISION_GROSS:,.0f})")


def check_infeasible(row: dict[str, Any] | None, binding: list[dict[str, Any]]) -> Check:
    if not row:
        return Check("commitments infeasible", False, "no precompute run for grower-commitments-2027")
    named = [b["detail"] for b in binding if b["entity"] == "IA/W1" and b["rule"] == "capacity"]
    ok = row["status"] == "infeasible" and bool(named)
    return Check("commitments infeasible", ok, f"status={row['status']} binding={named or binding}")


def check_stress(rows: list[dict[str, Any]]) -> Check:
    by_id = {r["stress_id"]: r for r in rows}
    missing = [i for i in PRECOMPUTED_STRESS if i not in by_id]
    if missing:
        return Check("stored stress tests", False, f"missing {missing}")
    base, rev = (by_id[i] for i in PRECOMPUTED_STRESS)
    p10b, p10r = float(base["p10_gross_margin"]), float(rev["p10_gross_margin"])
    ok = all(int(r["n"]) == 500 and int(r["n_solved"]) == 500 for r in (base, rev)) and p10r > p10b
    return Check("stored stress tests", ok, f"P10 baseline={p10b:,.0f} revision-1={p10r:,.0f} "
                                            f"solved={base['n_solved']}/{rev['n_solved']} of 500")


def tool_results(state: dict[str, Any], name: str) -> list[dict[str, Any]]:
    out = []
    for m in state.get("messages") or []:
        if m.get("type") == "tool" and m.get("name") == name:
            try:
                out.append(json.loads(m["content"]))
            except (TypeError, ValueError):
                out.append({"raw": m.get("content")})
    return out


def check_genie_turn(state: dict[str, Any]) -> Check:
    if state.get("status") != "completed":
        return Check("agent -> Genie (step 6)", False, f"turn {state.get('status')}: {state.get('error')}")
    sqls = [a["query"]["query"] for r in tool_results(state, "genie_agent_ask") for a in r.get("attachments") or []
            if (a.get("query") or {}).get("query")]
    ok = any("seed_utilization" in q for q in sqls)
    return Check("agent -> Genie (step 6)", ok, f"{len(sqls)} SQL attachment(s)" + ("" if ok else f": {sqls}"))


def check_what_if_turn(state: dict[str, Any]) -> tuple[Check, str | None]:
    if state.get("status") != "completed":
        return Check("agent what-if (step 5)", False, f"turn {state.get('status')}: {state.get('error')}"), None
    solves = tool_results(state, "solve_scenario")
    if not solves:
        return Check("agent what-if (step 5)", False, "the agent didn't call solve_scenario"), None
    s = solves[-1]
    ok = (s.get("status") == "done" and (s.get("overrides") or {}).get("capacity_pct") == {"IA": {"W1": 0.5}}
          and (s.get("delta_vs_base") or {}).get("gross_margin", 0) < 0)
    return Check("agent what-if (step 5)", ok, f"scenario={s.get('scenario_id')} status={s.get('status')} "
                                               f"delta_gross={(s.get('delta_vs_base') or {}).get('gross_margin')}"), s.get("scenario_id")


class Studio:
    """Crop Plan Studio as the CLI user (Apps accept the workspace OAuth token as a bearer token)."""

    def __init__(self, w: Any, url: str) -> None:
        self.w, self.url = w, url.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        headers = {"Content-Type": "application/json", **self.w.config.authenticate()}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                raw = res.read()
                return res.status, json.loads(raw) if res.headers.get_content_type() == "application/json" else raw
        except urllib.error.HTTPError as e:
            return e.code, e.read()[:300]

    def turn(self, message: str) -> dict[str, Any]:
        status, started = self.call("POST", "/api/studio/agent/turns", {"session_id": str(uuid.uuid4()), "message": message})
        if status != 200:
            return {"status": "failed", "error": f"start: HTTP {status} {started}"}
        deadline = time.time() + TURN_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(3)
            status, state = self.call("GET", f"/api/studio/agent/turns/{started['id']}")
            if status == 200 and state.get("status") in ("completed", "failed"):
                return state
        return {"status": "failed", "error": f"no answer in {TURN_TIMEOUT_S} s"}


def latest_precompute_runs(sql: Sql, t: Target) -> dict[str, dict[str, Any]]:
    rows = sql.rows(
        f"SELECT r.scenario_id, r.status, r.mlflow_run_id, m.gross_margin, m.unplanted_fields, r.run_id "
        f"FROM {t.fq('runs')} r LEFT JOIN {t.fq('run_summary')} m ON m.run_id = r.run_id "
        f"WHERE r.triggered_by = 'precompute' QUALIFY row_number() OVER (PARTITION BY r.scenario_id ORDER BY r.started_at DESC) = 1")
    return {r["scenario_id"]: r for r in rows}


def data_checks(sql: Sql, t: Target) -> list[Check]:
    counts = {r["scenario_id"]: int(r["n"]) for r in sql.rows(
        f"SELECT scenario_id, count(*) AS n FROM {t.fq('fields')} WHERE scenario_id IN {in_list(SEEDED)} GROUP BY scenario_id")}
    runs = latest_precompute_runs(sql, t)
    commitments = runs.get("grower-commitments-2027")
    binding = sql.rows(f"SELECT rule, entity, detail FROM {t.fq('violations')} WHERE run_id = :r AND severity = 'binding'",
                       r=commitments["run_id"]) if commitments else []
    stress = sql.rows(f"SELECT stress_id, n, n_solved, p10_gross_margin FROM {t.fq('stress_test_summary')} "
                      f"WHERE stress_id IN {in_list(PRECOMPUTED_STRESS)}")
    return [check_seeded(counts), check_baseline(runs.get("baseline-2027")), check_revision(runs.get("revision-1-2027")),
            check_infeasible(commitments, binding), check_stress(stress)]


def studio_checks(studio: Studio) -> list[Check]:
    s1, who = studio.call("GET", "/api/studio/whoami")
    s2, cfg = studio.call("GET", "/api/studio/config")
    s3, _ = studio.call("GET", "/results/baseline-2027")
    agent_url = cfg.get("agentUrl") if isinstance(cfg, dict) else None
    return [Check("Studio answers", s1 == 200 and s2 == 200 and s3 == 200,
                  f"whoami={s1} {who if s1 == 200 else ''} config={s2} results page={s3}"),
            Check("Studio knows the agent", bool(agent_url), f"agentUrl={agent_url!r}")]


def agent_checks(studio: Any, delete_scenario: Callable[[str], None], keep_scenario: bool = False) -> list[Check]:
    """Demo steps 6 then 5 through Studio's agent proxy. Genie goes first, and the what-if's scenario is deleted
    afterwards: an "Iowa loses W1" scenario frees H-112, which changes step 6's answer."""
    checks = [check_genie_turn(studio.turn(GENIE_QUESTION))]
    what_if, scenario_id = check_what_if_turn(studio.turn(WHAT_IF))
    checks.append(what_if)
    if scenario_id and not keep_scenario:
        delete_scenario(scenario_id)
    return checks


def report(checks: list[Check], out: Callable[[str], None] = print) -> bool:
    for c in checks:
        out(f"   {'PASS' if c.ok else 'FAIL'}  {c.name}: {c.detail}")
    passed = sum(c.ok for c in checks)
    out(f"Smoke test: {passed}/{len(checks)} checks passed.")
    return passed == len(checks)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True)
    p.add_argument("--target", default="dev")
    p.add_argument("--skip-agent", action="store_true", help="skip the two agent turns (~4 min)")
    p.add_argument("--keep-scenario", action="store_true", help="keep the scenario the what-if creates")
    args = p.parse_args(argv)

    t = load_target(args.profile, args.target)
    sql = Sql(args.profile, t.warehouse_id)
    studio = Studio(sql.w, sql.w.apps.get(t.studio_app).url)
    checks = data_checks(sql, t) + studio_checks(studio)
    if not args.skip_agent:
        checks += agent_checks(studio, lambda sid: reset_demo.delete_scenarios(sql, t, [sid]), args.keep_scenario)
    if not report(checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
