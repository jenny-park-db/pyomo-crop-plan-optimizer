"""scripts/demo_env.py: .env parsing, presenter lists, SQL ID lists, and reading a bundle summary."""
import pytest

import demo_env

SUMMARY = {
    "variables": {"catalog": {"value": "x_catalog"}, "schema": {"value": "crop_plan"},
                  "warehouse_id": {"value": "abcdef0123456789"}},
    "resources": {"schemas": {"crop_plan": {"name": "crop_plan", "id": "x_catalog.crop_plan"}},
                  "apps": {"crop_plan_studio": {"name": "crop-plan-studio"}},
                  "genie_spaces": {"crop_plan_results": {"id": "01ef0123456789abcdef0123456789ab"}},
                  "experiments": {"scenarios": {"id": "1234567890123456"}},
                  "jobs": {"solve_scenario": {"id": "111111111111111"}, "stress_test": {"id": "222222222222222"}}},
}


def test_dotenv_skips_comments_and_blank_lines_and_unquotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# comment\n\nA=1\nB = 'two words'\nC=\"x=y\"\nnot a pair\nD=\n")
    assert demo_env.read_dotenv(path) == {"A": "1", "B": "two words", "C": "x=y", "D": ""}
    assert demo_env.read_dotenv(tmp_path / "missing") == {}


def test_presenter_lists_are_trimmed_and_deduplicated():
    assert demo_env.split_list(" a@x.com, Planners ,,a@x.com,b@x.com ") == ["a@x.com", "Planners", "b@x.com"]
    assert demo_env.split_list("") == [] and demo_env.split_list(None) == []


def test_in_list_quotes_safe_ids_and_rejects_anything_else():
    assert demo_env.in_list(("baseline-2027", "st-1.n50")) == "('baseline-2027', 'st-1.n50')"
    with pytest.raises(ValueError):
        demo_env.in_list(["x' OR '1'='1"])


def test_target_from_summary_reads_what_the_scripts_use():
    t = demo_env.target_from_summary(SUMMARY, "p", "dev")
    assert (t.catalog, t.schema, t.warehouse_id, t.studio_app) == ("x_catalog", "crop_plan", "abcdef0123456789", "crop-plan-studio")
    assert t.space_id == "01ef0123456789abcdef0123456789ab" and t.experiment_id == "1234567890123456"
    assert t.jobs == {"solve_scenario": 111111111111111, "stress_test": 222222222222222}
    assert t.fq("runs") == "`x_catalog`.`crop_plan`.`runs`"


def test_a_target_before_its_first_full_deploy_has_no_space_id():
    partial = {"variables": SUMMARY["variables"],
               "resources": {"apps": {"crop_plan_studio": {"name": "crop-plan-studio"}}, "jobs": {"seed_data": {}}}}
    t = demo_env.target_from_summary(partial, "p", "dev")
    assert t.space_id is None and t.experiment_id is None and t.jobs == {} and t.schema == "crop_plan"
