from agent.prompt import SYSTEM_PROMPT


def test_routes_each_question_type_to_its_tool():
    for phrase in ("solve_scenario", "genie_agent", "stress_test_plan", "get_stress_test"):
        assert phrase in SYSTEM_PROMPT


def test_documents_the_weather_mapping_and_asks_for_stated_assumptions():
    assert '{"IA": {"W1": 0.5}}' in SYSTEM_PROMPT
    assert "25% of that window's capacity" in SYSTEM_PROMPT
    assert "assumptions argument" in SYSTEM_PROMPT


def test_no_arithmetic_on_tool_numbers():
    flat = " ".join(SYSTEM_PROMPT.split())
    assert "Never state a number you computed yourself" in flat
    assert "ask Genie to compute it" in flat
    for field in ("delta_vs_base", "delta_pct_vs_base", "p90_minus_p10"):
        assert field in flat


def test_plain_text_replies_because_the_panel_shows_them_as_is():
    flat = " ".join(SYSTEM_PROMPT.split())
    assert "plain text without Markdown" in flat
    assert "don't repeat Genie's SQL" in flat


def test_citation_scope_and_length_rules():
    assert "Use only numbers that appear in tool results" in " ".join(SYSTEM_PROMPT.split())
    assert "under 300 words" in SYSTEM_PROMPT
    assert "out of scope" in SYSTEM_PROMPT


def test_the_prompt_itself_is_short_enough_to_leave_room_for_tool_results():
    assert len(SYSTEM_PROMPT.split()) < 400
