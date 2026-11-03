"""Code scorers for the evaluation (run in CI; the live evaluation does not)."""
import json
from pathlib import Path

import pandas as pd
import yaml
from evals.run_eval import to_outputs, verdict
from evals.scorers import cited_numbers, evidence_numbers, first_tool, grounded, tool_family, ungrounded

SOLVE = {"kpis": {"gross_margin": 18570045.75, "acres_planted_pct": 0.9730906212900673, "unplanted_fields": 4},
         "delta_vs_base": {"gross_margin": -240954.25}, "delta_pct_vs_base": {"gross_margin": -1.28},
         "base": {"kpis": {"gross_margin": 18811000.0}}}


def outputs(reply, calls=(), results=()):
    return {"reply": reply, "tool_calls": list(calls), "tool_results": list(results)}


def test_tool_families_fold_the_genie_tools_and_skip_memory():
    assert tool_family("genie_agent_ask") == tool_family("genie_agent_query_result") == "genie"
    assert first_tool(outputs("", [{"name": "remember", "args": {}}, {"name": "solve_scenario", "args": {}}])) == "solve_scenario"
    assert first_tool(outputs("no tools")) == "none"


def test_cited_numbers_parse_money_suffixes_percent_and_skip_ids():
    got = cited_numbers("Gross margin $18.57M (down $241K, -1.28%); 97.3% planted; 4 fields; H-112 and W1 in baseline-2027.")
    assert [(round(v, 4), u) for v, u in got] == [(18570000.0, 10000.0), (241000.0, 1000.0), (-1.28, 0.01), (97.3, 0.1),
                                                   (4.0, 1.0)]


def test_rounded_citations_of_tool_numbers_are_grounded():
    ev = evidence_numbers("What if Iowa loses half its W1 capacity?", [{"name": "solve_scenario", "args": {}}],
                          [{"name": "solve_scenario", "content": json.dumps(SOLVE)}])
    assert ungrounded("$18.57M gross margin, $241K less (-1.28%), 97.3% planted, 4 unplanted fields.", ev) == []


def test_lowercase_suffixes_and_unicode_minus_are_read():
    ev = evidence_numbers("q", [], [{"name": "solve_scenario", "content": json.dumps({"delta_vs_base": {"gross_margin": -37986.5},
                                                                                       "delta_pct_vs_base": {"gross_margin": -0.2}})}])
    assert ungrounded("It costs about $38k (−0.2%).", ev) == []


def test_only_fractions_are_rescaled_to_percent():
    ev = evidence_numbers("q", [], [{"name": "genie_agent_query_result", "content": json.dumps({"rows": [["1170"]]})}])
    assert ungrounded("Revision 1 is higher by approximately $117,000.", ev) == ["$117,000"]


def test_an_invented_number_is_caught():
    ev = evidence_numbers("q", [], [{"name": "solve_scenario", "content": json.dumps(SOLVE)}])
    assert ungrounded("Gross margin falls about 3.5%, roughly $650K.", ev) == ["3.5%", "$650K"]


def test_numbers_in_the_question_and_tool_arguments_count_as_grounded():
    ev = evidence_numbers("What if corn drops to $3.90 a bushel?", [{"name": "solve_scenario",
                          "args": {"overrides": {"capacity_pct": {"NE": {"W2": 0.75}}}, "assumptions": "one week = 25%"}}], [])
    assert ungrounded("At $3.90 corn, with 25% of NE W2 capacity lost (0.75 of it left):", ev) == []


def test_numbers_inside_sql_or_genie_text_are_evidence():
    genie = {"attachments": [{"query": {"query": "SELECT ... HAVING MIN(pct) >= 0.99"}}],
             "rows": [["H-112", "3", "99.77"]]}
    ev = evidence_numbers("q", [], [{"name": "genie_agent_ask", "content": json.dumps(genie)}])
    assert ungrounded("H-112 runs at 99.77% in all 3 scenarios (threshold 99%).", ev) == []


def test_facts_from_the_system_prompt_count_as_evidence():
    ev = evidence_numbers("Write me a haiku about tractors.", [], [])
    assert ungrounded("I can only help with the 2027 hybrid-to-field plan.", ev) == []


def test_grounded_scorer_reports_the_offending_numbers():
    fb = grounded(inputs={"question": "q"}, outputs=outputs("It earns $99.99M.", results=[{"name": "solve_scenario", "content": json.dumps(SOLVE)}]))
    assert fb.value is False and "$99.99M" in fb.rationale


def test_the_question_set_covers_the_four_categories():
    qs = yaml.safe_load((Path(__file__).resolve().parents[1] / "evals" / "questions.yaml").read_text())
    assert len(qs) == 15 and len({q["id"] for q in qs}) == 15
    assert {q["category"] for q in qs} == {"what-if", "data", "robustness", "off-topic"}
    families = {"solve_scenario", "genie", "stress_test_plan", "get_stress_test", "none"}
    assert all(set(q["expected_tools"]) <= families for q in qs)


def test_pass_bar_is_tool_accuracy_and_every_number_grounded_with_the_judge_advisory():
    rows = lambda tool, code, judge: pd.DataFrame({"correct_tool/value": tool, "numbers_grounded/value": code,  # noqa: E731
                                                   "groundedness/value": judge})
    ten = [True] * 10
    assert verdict(rows(ten[:9] + [False], ten, ten[:8] + ["no", "no"]))[0] is True  # 90% tools, judge advisory
    assert verdict(rows(ten[:8] + [False, False], ten, ten))[0] is False  # 80% tools
    assert verdict(rows(ten, ten[:9] + [False], ten))[0] is False  # one ungrounded number


def test_outputs_come_from_the_agents_message_list():
    msgs = [{"type": "human", "content": "q"},
            {"type": "ai", "content": "", "tool_calls": [{"name": "solve_scenario", "args": {"name": "x"}, "id": "1"}]},
            {"type": "tool", "name": "solve_scenario", "content": '{"status": "done"}'},
            {"type": "ai", "content": [{"type": "text", "text": "Done."}], "tool_calls": []}]
    assert to_outputs(msgs) == {"reply": "Done.", "tool_calls": [{"name": "solve_scenario", "args": {"name": "x"}}],
                                "tool_results": [{"name": "solve_scenario", "content": '{"status": "done"}'}]}


def test_a_coarsely_rounded_self_computed_number_is_still_caught():
    # 1.64M of acres-weighted margin summed by the model, stated as "about $2M": half a unit of "2M" is 500K,
    # which used to cover it; the tolerance is now also capped at 1% of the cited value.
    ev = evidence_numbers("q", [], [{"name": "solve_scenario", "content": json.dumps({"delta_vs_base": {"gross_margin": 1640000}})}])
    assert ungrounded("Together they add about $2M.", ev) == ["$2M"]
    assert ungrounded("They add $1.64M.", ev) == []
