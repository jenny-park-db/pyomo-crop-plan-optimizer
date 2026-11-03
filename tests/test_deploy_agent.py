"""scripts/deploy_agent.py: the pure parts (staging, app.yaml env, the bundle override file, summary lookups)."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deploy_agent", ROOT / "scripts" / "deploy_agent.py")
deploy_agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_agent)


def test_staging_copies_source_but_never_local_state_or_secrets(tmp_path):
    src = tmp_path / "agent"
    for rel in ["agent.toml", "app.yaml", "pyproject.toml", "agent/agent.py", "runtime/main.py", ".env", "uv.lock",
                ".venv/bin/python", "agent/__pycache__/x.pyc", ".agentbricks/deploy.json", "evals/questions.yaml",
                ".agents/skills/x/SKILL.md"]:
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x")
    dst = tmp_path / "build" / "agent-deploy"
    (dst / "stale.txt").parent.mkdir(parents=True)
    (dst / "stale.txt").write_text("old")
    deploy_agent.stage_agent(src, dst)
    got = sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())
    assert got == ["agent.toml", "agent/agent.py", "app.yaml", "pyproject.toml", "runtime/main.py"]


def test_set_app_env_adds_or_replaces_one_variable_and_keeps_the_command():
    text = 'command: ["uv", "run", "start-server"]\n# comment\n'
    once = deploy_agent.set_app_env(text, "CROP_PLAN_STUDIO_URL", "https://a.aws.databricksapps.com")
    twice = deploy_agent.set_app_env(once, "CROP_PLAN_STUDIO_URL", "https://b.aws.databricksapps.com")
    doc = yaml.safe_load(twice)
    assert doc["command"] == ["uv", "run", "start-server"]
    assert doc["env"] == [{"name": "CROP_PLAN_STUDIO_URL", "value": "https://b.aws.databricksapps.com"}]


def test_override_file_merges_with_what_is_there(tmp_path):
    path = tmp_path / ".databricks" / "bundle" / "dev" / "variable-overrides.json"
    deploy_agent.write_override(path, "agent_url", "https://x.aws.databricksapps.com")
    path.write_text(json.dumps({**json.loads(path.read_text()), "other": 1}))
    deploy_agent.write_override(path, "agent_url", "https://y.aws.databricksapps.com")
    assert json.loads(path.read_text()) == {"agent_url": "https://y.aws.databricksapps.com", "other": 1}


def test_reads_the_space_and_app_from_the_bundle_summary():
    summary = {"resources": {"genie_spaces": {"crop_plan_results": {"id": "01ef0123456789abcdef0123456789ab"}},
                             "apps": {"crop_plan_studio": {"name": "crop-plan-studio"}}}}
    assert deploy_agent.genie_space_id(summary) == "01ef0123456789abcdef0123456789ab"
    assert deploy_agent.studio_app_name(summary) == "crop-plan-studio"
    with pytest.raises(SystemExit, match="Genie space"):
        deploy_agent.genie_space_id({"resources": {}})


def test_app_urls_must_be_https():
    assert deploy_agent.https_url({"url": "https://a.aws.databricksapps.com/"}, "x") == "https://a.aws.databricksapps.com"
    with pytest.raises(SystemExit, match="no URL"):
        deploy_agent.https_url({"name": "x"}, "x")


def test_the_repo_agent_project_is_deployable_as_staged():
    toml = (ROOT / "agent" / "agent.toml").read_text()
    assert 'deployment_name = "crop-plan-agent"' in toml and "required = true" in toml
    assert "genie_agent" not in toml  # bound at deploy time; the space ID is workspace-specific
    assert yaml.safe_load((ROOT / "agent" / "app.yaml").read_text())["command"] == ["uv", "run", "start-server"]
    assert deploy_agent.AGENT_APP == "agent-bricks-crop-plan-agent"


def test_the_stage_dir_is_outside_the_repo_so_databricks_sync_uploads_it():
    # `agentbricks deploy` uploads with `databricks sync`, which honours the enclosing repo's .gitignore:
    # a copy under the repo's ignored build/ uploads no files ("Error downloading source code ... no files found").
    first, second = deploy_agent.new_stage_dir("crop-plan-agent"), deploy_agent.new_stage_dir("crop-plan-agent")
    try:
        assert ROOT not in first.parents and first != second  # a fresh folder per run
        assert first.name.startswith("pyomo-crop-plan-agent-crop-plan-agent-") and not any(first.iterdir())
    finally:
        first.rmdir()
        second.rmdir()


def test_another_agent_name_renames_the_deployment_stores_and_traces_together():
    toml = (ROOT / "agent" / "agent.toml").read_text()
    renamed = deploy_agent.rename_agent(toml, "p5probe-agent")
    assert 'deployment_name = "p5probe-agent"' in renamed
    assert 'name = "p5probe-agent-memory"' in renamed and 'name = "p5probe-agent-sessions"' in renamed
    assert 'experiment_name = "/Shared/agentbricks_traces/p5probe-agent"' in renamed
    assert "crop-plan-agent" not in renamed
    assert deploy_agent.rename_agent(toml, deploy_agent.DEFAULT_AGENT_NAME) == toml


def test_agent_names_must_fit_the_30_character_app_name():
    assert deploy_agent.agent_app_name("crop-plan-agent") == deploy_agent.AGENT_APP
    assert deploy_agent.agent_app_name("a" * 17) == "agent-bricks-" + "a" * 17
    for bad in ["a" * 18, "Crop_Agent", ""]:
        with pytest.raises(SystemExit, match="at most 17"):
            deploy_agent.agent_app_name(bad)


def test_a_failing_cli_call_shows_its_error_output(capsys):
    import subprocess
    import sys
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('Error: not logged in to profile p'); sys.exit(1)"]
    with pytest.raises(subprocess.CalledProcessError):
        deploy_agent.run(cmd, capture=True)
    assert "not logged in to profile p" in capsys.readouterr().err
