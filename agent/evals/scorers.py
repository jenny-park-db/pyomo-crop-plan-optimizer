"""Scorers for the planning agent's evaluation (spec §9: correct tool >= 90%, no ungrounded numbers).

An agent output here is {"reply": str, "tool_calls": [{name, args}], "tool_results": [{name, content}]},
built by run_eval.py from the deployed agent's message list (the Apps runtime does not upload trace spans,
so scorers read outputs, not traces).
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.prompt import SYSTEM_PROMPT
from mlflow.entities import Feedback
from mlflow.genai.judges import make_judge
from mlflow.genai.scorers import scorer

MEMORY_TOOLS = {"remember", "recall", "forget", "list_memories"}
JUDGE_MODEL = "databricks:/databricks-gpt-5-mini"

# Identifiers that contain digits but are not quantities: H-112, F-115, baseline-2027, st-…-n50, W1, run IDs.
_IDS = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+\b|\bW[1-4]\b|\bN=\d+\b", re.I)
_LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.M)
_CITED = re.compile(
    r"(?<![\w.])([-−]?)\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s?(million|thousand|billion)\b|([KkMmBb])\b|(%))?")
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}
_EVIDENCE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def tool_family(name: str) -> str:
    return "genie" if name.startswith("genie_agent") else name


def first_tool(outputs: dict[str, Any]) -> str:
    for call in outputs.get("tool_calls", []):
        if call["name"] not in MEMORY_TOOLS:
            return tool_family(call["name"])
    return "none"


def _strip(text: str) -> str:
    return _LIST_MARKER.sub(" ", _IDS.sub(" ", text))


def _cited(text: str) -> list[tuple[str, float, float]]:
    """(token, value, resolution) for every quantity a reply states; resolution = one unit of the last digit."""
    out = []
    for m in _CITED.finditer(_strip(text)):
        sign, whole, frac, word, letter, pct = m.groups()
        value = float(whole.replace(",", "") + (frac or ""))
        unit = 10 ** -(len(frac) - 1) if frac else 1.0
        scale = _SCALE.get((word or letter or "").lower(), 1.0)
        out.append((m.group(0).strip(), (-1 if sign else 1) * value * scale, unit * scale))
    return out


def cited_numbers(text: str) -> list[tuple[float, float]]:
    return [(v, u) for _, v, u in _cited(text)]


def evidence_numbers(question: str, tool_calls: list[dict[str, Any]], tool_results: list[dict[str, Any]]) -> set[float]:
    """Every number in the agent's instructions, the question, the tool arguments (stated assumptions), and the
    tool results."""
    texts = [SYSTEM_PROMPT, question, *(json.dumps(c.get("args", {})) for c in tool_calls),
             *(r["content"] if isinstance(r["content"], str) else json.dumps(r["content"]) for r in tool_results)]
    found: set[float] = set()
    for text in texts:
        for token in _EVIDENCE.findall(text):
            v = abs(float(token))
            found.add(v)
            if v <= 1.5:
                found.add(v * 100)  # a fraction (0.973) may be cited as a percent (97.3%)
    return found


def ungrounded(reply: str, evidence: set[float]) -> list[str]:
    bad = []
    for token, value, unit in _cited(reply):
        v = abs(value)
        # Within the displayed rounding, but never more than 1% of the value: "$2M" must not cover a $1.64M sum.
        tolerance = min(unit / 2, 0.01 * v)
        if not any(abs(v - e) <= tolerance + 1e-9 * max(1.0, e) for e in evidence):
            bad.append(token)
    return bad


def grounded(inputs: dict[str, Any], outputs: dict[str, Any]) -> Feedback:
    evidence = evidence_numbers(inputs["question"], outputs.get("tool_calls", []), outputs.get("tool_results", []))
    bad = ungrounded(outputs.get("reply", ""), evidence)
    return Feedback(value=not bad, rationale="every number is in a tool result, tool argument, or the question"
                    if not bad else f"not found in any tool result, argument, or the question: {', '.join(bad)}")


@scorer(name="correct_tool")
def correct_tool(inputs: dict[str, Any], outputs: dict[str, Any], expectations: dict[str, Any]) -> Feedback:
    got = first_tool(outputs)
    want = expectations["expected_tools"]
    return Feedback(value=got in want, rationale=f"first tool {got}; acceptable {want}")


@scorer(name="numbers_grounded")
def numbers_grounded(inputs: dict[str, Any], outputs: dict[str, Any]) -> Feedback:
    return grounded(inputs, outputs)


groundedness_judge = make_judge(
    name="groundedness",
    instructions=(
        "You check a crop-planning assistant's reply for invented facts. The request is {{ inputs }}. The output "
        "{{ outputs }} has the final reply plus every tool call (arguments) and tool result the assistant saw.\n"
        "Answer 'yes' if every number and factual claim about scenarios, margins, seed supply, capacity, fields, or "
        "stress tests in the reply is supported by a tool result, a tool argument (including stated assumptions), "
        "or the request itself, or the assistant's own scope (it plans the 2027 hybrid-to-field crop plan for regions "
        "IA, IL, and NE and planting windows W1-W4); rounding and unit changes ($18,570,045 -> $18.57M, 0.973 -> 97.3%) are fine, and so "
        "are plain-language explanations that add no new numbers. Answer 'yes' for a reply that declines an "
        "off-topic request. Answer 'no' if the reply states any number or specific fact that none of those support."
    ),
    feedback_value_type=bool,
    model=JUDGE_MODEL,
)
