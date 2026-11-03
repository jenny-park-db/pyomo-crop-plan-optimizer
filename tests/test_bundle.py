"""Static checks on the bundle that would otherwise only fail after a deploy and a job run."""

import os
import re
import stat
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from cropplan_jobs.cli import PARSERS, parse  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "bundle"


def _jobs() -> dict:
    jobs = {}
    for path in sorted((BUNDLE / "resources").glob("*.yml")):
        jobs.update((yaml.safe_load(path.read_text()) or {}).get("resources", {}).get("jobs", {}))
    return jobs


def _wheel_tasks():
    for job_key, job in _jobs().items():
        job_params = [p["name"] for p in job.get("parameters", [])]
        for task in job["tasks"]:
            if "python_wheel_task" in task:
                yield f"{job_key}.{task['task_key']}", task["python_wheel_task"], job_params


def test_bundle_defines_the_four_jobs():
    assert set(_jobs()) == {"seed_data", "solve_scenario", "stress_test", "precompute"}


@pytest.mark.parametrize("name, task, job_params", list(_wheel_tasks()))
def test_wheel_task_parameters_parse(name, task, job_params):
    """The SystemExit: 2 guard. Every YAML key is a declared flag, every declared flag is set in the YAML, and
    the job-level parameters that Jobs pushes down to every task (as extra --name=value) don't break parsing."""
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert task["package_name"] == "cropplan" and task["entry_point"] in scripts
    assert task["entry_point"] in PARSERS
    named = [f"--{k}=x" for k in task["named_parameters"]]
    assert set(vars(parse(task["entry_point"], named))) == set(task["named_parameters"])
    parse(task["entry_point"], named + [f"--{p}=x" for p in job_params])


def test_shell_entry_points_are_not_executable():
    """AI Runtime fails with 'Input/output error' when command_path has the executable bit."""
    scripts = list(BUNDLE.rglob("*.sh"))
    assert scripts
    for path in scripts:
        assert not os.stat(path).st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), path


def test_ai_runtime_experiment_matches_the_scenarios_experiment():
    stress = _jobs()["stress_test"]
    air = next(t["ai_runtime_task"] for t in stress["tasks"] if "ai_runtime_task" in t)
    assert air["experiment"] == "${var.experiment_leaf}"
    assert air["mlflow_experiment_directory"] == "/Workspace${var.experiment_dir}"
    data = yaml.safe_load((BUNDLE / "resources" / "data.yml").read_text())
    assert data["resources"]["experiments"]["scenarios"]["name"] == "${var.experiment_dir}/${var.experiment_leaf}"


def test_tasks_fail_once_instead_of_auto_retrying():
    """Serverless auto-optimization silently retried a failed solve (attempt 1 of the same run) in testing."""
    for job in _jobs().values():
        for task in job["tasks"]:
            if "run_job_task" in task:
                continue
            assert task.get("max_retries") == 0, task["task_key"]
            if "python_wheel_task" in task:
                assert task.get("disable_auto_optimization") is True, task["task_key"]


def _bundle() -> dict:
    return yaml.safe_load((BUNDLE / "databricks.yml").read_text())


def _app() -> dict:
    return yaml.safe_load((BUNDLE / "resources" / "app.yml").read_text())["resources"]["apps"]["crop_plan_studio"]


def test_sync_covers_the_app_and_the_stress_script_moves_under_bundle():
    """sync.paths widens the sync root to the repo; files then land under files/bundle/ (verified on a deployed workspace)."""
    assert _bundle()["sync"]["paths"] == [".", "../app"]
    air = next(t["ai_runtime_task"] for t in _jobs()["stress_test"]["tasks"] if "ai_runtime_task" in t)
    assert air["deployments"][0]["command_path"] == "${workspace.file_path}/bundle/stress/command.sh"
    assert (BUNDLE / "stress" / "command.sh").exists()


def test_genie_space_is_included_from_genie_dir():
    assert "../genie/*.yml" in _bundle()["include"]


def test_app_runs_sql_and_genie_as_the_user_and_jobs_as_its_service_principal():
    app = _app()
    assert app["source_code_path"] == "../../app"
    assert sorted(app["user_api_scopes"]) == ["dashboards.genie", "sql"]
    jobs = {r["name"]: r["job"] for r in app["resources"] if "job" in r}
    assert jobs == {"solve-job": {"id": "${resources.jobs.solve_scenario.id}", "permission": "CAN_MANAGE_RUN"},
                    "stress-job": {"id": "${resources.jobs.stress_test.id}", "permission": "CAN_MANAGE_RUN"}}
    assert not any("uc_securable" in r for r in app["resources"]), "the app SP runs no SQL, so it needs no UC grants"


def test_every_env_value_from_names_an_app_resource_and_the_server_reads_them():
    app = _app()
    names = {r["name"] for r in app["resources"]}
    env = {e["name"]: e for e in app["config"]["env"]}
    assert {e["value_from"] for e in env.values() if "value_from" in e} <= names
    config_ts = (ROOT / "app" / "server" / "studio" / "config.ts").read_text()
    for key in ("CROP_PLAN_CATALOG", "CROP_PLAN_SCHEMA", "CROP_PLAN_SOLVE_JOB_ID", "CROP_PLAN_STRESS_JOB_ID",
                "MLFLOW_EXPERIMENT_ID", "CROP_PLAN_MAP_MODE"):
        assert key in env and key in config_ts, key


def test_app_names_fit_the_apps_limit():
    names = [_bundle()["variables"]["app_name"]["default"], _bundle()["targets"]["prod"]["variables"]["app_name"]]
    for name in names:
        assert len(name) <= 26 and name == name.lower() and "_" not in name, name


def test_server_does_not_register_the_appkit_jobs_plugin():
    """jobs() mounts POST /api/jobs/:key/run, which would let a browser choose triggered_by."""
    server = (ROOT / "app" / "server" / "server.ts").read_text()
    plugins = re.search(r"plugins: \[([^\]]*)\]", server).group(1)
    assert "jobs(" not in plugins and "analytics()" in plugins and "genie()" in plugins
    assert "cache: { enabled: false }" in server




def test_the_agent_url_is_a_bundle_variable_the_app_reads():
    """The default is "none" until scripts/deploy_agent.py records the URL in the target's variable-overrides.json.

    Not "": the Apps API rejects an env var with an empty value ("Must specify environment variable source using
    either `value` or `valueFrom`"), which failed a fresh workspace's first deploy.
    """
    assert _bundle()["variables"]["agent_url"]["default"] == "none"
    env = {e["name"]: e for e in _app()["config"]["env"]}
    assert env["CROP_PLAN_AGENT_URL"] == {"name": "CROP_PLAN_AGENT_URL", "value": "${var.agent_url}"}
    assert "CROP_PLAN_AGENT_URL" in (ROOT / "app" / "server" / "studio" / "config.ts").read_text()


def test_the_agent_override_file_stays_out_of_git():
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".databricks/" in ignored and "build/" in ignored
