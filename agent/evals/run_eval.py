"""Evaluate the deployed planning agent on evals/questions.yaml (spec §9). Not run in CI.

    cd agent && uv run python -m evals.run_eval --profile <profile> [--agent-app agent-bricks-crop-plan-agent] [--only q01,q06]

Each question is one fresh conversation sent to the agent's /api/invocations as you (what-ifs start real solves
through Crop Plan Studio; q11 starts one n=10 stress test). Pass bar (spec §9): correct first tool on >= 90% of
questions and no ungrounded numbers (the numbers_grounded check on every row). The groundedness LLM judge is a
second opinion: its "no" rows are printed for a human to read, but it doesn't gate (on 2026-11-02 it flagged a
correct off-topic refusal, and a stronger judge model passed replies with the agent's own arithmetic). Exit 0 = pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import mlflow
import yaml
from databricks.sdk import WorkspaceClient

from evals.scorers import correct_tool, groundedness_judge, numbers_grounded

QUESTIONS = Path(__file__).with_name("questions.yaml")
EXPERIMENT = "/Shared/pyomo_crop_plan_agent_evals"
TURN_TIMEOUT_S = 600
TOOL_ACCURACY_BAR = 0.9


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def to_outputs(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The agent's LangGraph message list -> what the scorers read."""
    calls = [{"name": c["name"], "args": c.get("args", {})} for m in messages if m.get("type") == "ai"
             for c in m.get("tool_calls") or []]
    results = [{"name": m.get("name"), "content": _text(m.get("content"))} for m in messages if m.get("type") == "tool"]
    replies = [_text(m.get("content")).strip() for m in messages if m.get("type") == "ai"]
    return {"reply": next((r for r in reversed(replies) if r), ""), "tool_calls": calls, "tool_results": results}


class AgentClient:
    def __init__(self, w: WorkspaceClient, app: str):
        self.w = w
        self.url = w.apps.get(app).url.rstrip("/")

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", **self.w.config.authenticate()}
        req = urllib.request.Request(self.url + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())

    def ask(self, question: str) -> dict[str, Any]:
        session = str(uuid.uuid4())
        started = self._call("POST", "/api/invocations", {"id": str(uuid.uuid4()), "session_id": session,
                                                          "background": True,
                                                          "input": {"messages": [{"role": "user", "content": question}]}})
        deadline = time.monotonic() + TURN_TIMEOUT_S
        while time.monotonic() < deadline:
            time.sleep(3)
            state = self._call("GET", f"/api/invocations/{started['id']}")
            if state["status"] == "completed":
                return to_outputs(state["output"]["output"])
            if state["status"] == "failed":
                return {"reply": "", "tool_calls": [], "tool_results": [], "error": str(state.get("error"))}
        return {"reply": "", "tool_calls": [], "tool_results": [], "error": f"no answer in {TURN_TIMEOUT_S} s"}


def dataset(only: set[str] | None) -> list[dict[str, Any]]:
    rows = yaml.safe_load(QUESTIONS.read_text())
    return [{"inputs": {"question": q["question"]}, "expectations": {"expected_tools": q["expected_tools"]},
             "tags": {"id": q["id"], "category": q["category"]}}
            for q in rows if not only or q["id"] in only]


def _yes(column) -> Any:
    return column.astype(str).str.lower().isin(["true", "yes"])


def verdict(df) -> tuple[bool, str]:
    """Pass bar from the eval_results table (one row per question, `<scorer>/value` columns)."""
    tool, code, judge = _yes(df["correct_tool/value"]), _yes(df["numbers_grounded/value"]), _yes(df["groundedness/value"])
    ok = bool(tool.mean() >= TOOL_ACCURACY_BAR and code.all())
    return ok, (f"correct tool {tool.sum()}/{len(df)} ({tool.mean():.0%}, bar {TOOL_ACCURACY_BAR:.0%}); "
                f"numbers grounded {code.sum()}/{len(df)} (bar: all); judge says grounded {judge.sum()}/{len(df)} "
                "(advisory: read its 'no' rows above)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True)
    p.add_argument("--agent-app", default="agent-bricks-crop-plan-agent")
    p.add_argument("--only", help="comma-separated question ids")
    args = p.parse_args(argv)

    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "4")  # 4 parallel conversations; the solve job queues
    w = WorkspaceClient(profile=args.profile)
    agent = AgentClient(w, args.agent_app)
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(EXPERIMENT)

    def predict_fn(question: str) -> dict[str, Any]:
        return agent.ask(question)

    data = dataset(set(args.only.split(",")) if args.only else None)
    with mlflow.start_run(run_name=f"agent-eval-{time.strftime('%Y%m%d-%H%M%S')}"):
        results = mlflow.genai.evaluate(data=data, predict_fn=predict_fn,
                                        scorers=[correct_tool, numbers_grounded, groundedness_judge])
    df = results.tables["eval_results"]
    for _, row in df.iterrows():
        print(f"{row['correct_tool/value']!s:5} {row['numbers_grounded/value']!s:5} {row['groundedness/value']!s:5} "
              f"{row['request']['question'] if isinstance(row['request'], dict) else row['request']}")
        for col in ("correct_tool/rationale", "numbers_grounded/rationale", "groundedness/rationale"):
            if col in df and row.get(col) and "acceptable" not in str(row[col]) and "every number" not in str(row[col]):
                print("      ", col.split("/")[0], ":", str(row[col])[:300])
    ok, summary = verdict(df)
    print(("PASS " if ok else "FAIL ") + summary)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
