"""Deploy the planning agent and point Crop Plan Studio at it (scripts/bootstrap.py calls this).

    uv run python scripts/deploy_agent.py --profile <profile> [--target dev] [--agent-name crop-plan-agent]
        [--skip-bundle-deploy]

1. Read the bundle summary for the Genie space ID and Studio app, and Studio's URL from the Apps API.
2. Copy agent/ to a fresh <tmp>/pyomo-crop-plan-agent-<name>-*/ (`agentbricks deploy` rewrites app.yaml in its
   source dir; the copy lives outside the repo because the upload, `databricks sync`, skips anything the repo's
   .gitignore covers, so a copy under build/ would upload no files).
3. Bind the Genie space there (`agentbricks tools add genie-agent`) and set CROP_PLAN_STUDIO_URL in app.yaml.
4. `agentbricks deploy` → app agent-bricks-crop-plan-agent (first deploy ~3-4 min).
5. Record its URL as bundle variable agent_url (.databricks/bundle/<target>/variable-overrides.json, gitignored)
   and `databricks bundle deploy`, so Studio's CROP_PLAN_AGENT_URL points at the agent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent"
BUNDLE_DIR = ROOT / "bundle"
DEFAULT_AGENT_NAME = "crop-plan-agent"
AGENT_APP = "agent-bricks-crop-plan-agent"  # agentbricks names the app agent-bricks-<deployment_name>
_SKIP = shutil.ignore_patterns(".venv", ".env", "uv.lock", "__pycache__", ".pytest_cache", ".agentbricks", ".agent",
                               ".agents", ".claude", "evals", "tests", "*.pyc")


def new_stage_dir(name: str) -> Path:
    """A new, empty folder outside the repo (see step 2 above), unique per run so two deploys never share one."""
    return Path(tempfile.mkdtemp(prefix=f"pyomo-crop-plan-agent-{name}-"))


def stage_agent(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=_SKIP)


def set_app_env(app_yaml: str, name: str, value: str) -> str:
    doc = yaml.safe_load(app_yaml) or {}
    env = [e for e in doc.get("env") or [] if e.get("name") != name]
    doc["env"] = [*env, {"name": name, "value": value}]
    return yaml.safe_dump(doc, sort_keys=False)


def agent_app_name(name: str) -> str:
    """agentbricks deploys `name` as app agent-bricks-<name>; app names are at most 30 characters."""
    app = f"agent-bricks-{name}"
    if not re.fullmatch(r"[a-z0-9-]+", name) or len(app) > 30:
        raise SystemExit(f"Agent name {name!r}: lowercase letters, digits, and '-', at most 17 characters")
    return app


def rename_agent(agent_toml: str, name: str) -> str:
    """Point agent.toml's deployment, stores, and trace experiment at `name` (they all embed the default name)."""
    agent_app_name(name)
    return agent_toml.replace(f'"{DEFAULT_AGENT_NAME}', f'"{name}').replace(
        f"agentbricks_traces/{DEFAULT_AGENT_NAME}", f"agentbricks_traces/{name}")


def write_override(path: Path, key: str, value: str) -> None:
    current = json.loads(path.read_text()) if path.exists() else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**current, key: value}, indent=2) + "\n")


def genie_space_id(summary: dict[str, Any]) -> str:
    space = summary.get("resources", {}).get("genie_spaces", {}).get("crop_plan_results", {})
    if not space.get("id"):
        raise SystemExit("The bundle has no deployed Genie space; run `databricks bundle deploy` first.")
    return space["id"]


def studio_app_name(summary: dict[str, Any]) -> str:
    return summary["resources"]["apps"]["crop_plan_studio"]["name"]


def https_url(app: dict[str, Any], name: str) -> str:
    url = (app.get("url") or "").rstrip("/")
    if not url.startswith("https://"):
        raise SystemExit(f"App {name} has no URL yet; check `databricks apps get {name}`.")
    return url


def run(cmd: list[str], cwd: Path = ROOT, capture: bool = False) -> str:
    print("+", " ".join(cmd), flush=True)
    try:
        out = subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=capture,
                             env={**os.environ, "AGENTBRICKS_DISABLE_AGENT_HINT": "1"})
    except subprocess.CalledProcessError as e:
        if e.stderr:  # captured: show the CLI's own error (not logged in, wrong profile, network access, ...)
            print(e.stderr.rstrip(), file=sys.stderr, flush=True)
        raise
    return out.stdout if capture else ""


def app_url(name: str, profile: str) -> str:
    return https_url(json.loads(run(["databricks", "apps", "get", name, "-o", "json", "--profile", profile], capture=True)), name)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", required=True)
    p.add_argument("--target", default="dev")
    p.add_argument("--agent-name", default=DEFAULT_AGENT_NAME, help="agentbricks deployment name (app agent-bricks-<name>)")
    p.add_argument("--skip-bundle-deploy", action="store_true", help="only deploy the agent and write the override")
    args = p.parse_args(argv)

    summary = json.loads(run(["databricks", "bundle", "summary", "-t", args.target, "-o", "json", "--profile", args.profile],
                             cwd=BUNDLE_DIR, capture=True))
    space_id = genie_space_id(summary)
    studio_url = app_url(studio_app_name(summary), args.profile)

    agent_app = agent_app_name(args.agent_name)
    stage = new_stage_dir(args.agent_name)
    try:
        stage_agent(AGENT_DIR, stage)
        if args.agent_name != DEFAULT_AGENT_NAME:
            toml = stage / "agent.toml"
            toml.write_text(rename_agent(toml.read_text(), args.agent_name))
        run(["agentbricks", "-p", args.profile, "tools", "add", "genie-agent", space_id, "--source", str(stage)])
        app_yaml = stage / "app.yaml"
        app_yaml.write_text(set_app_env(app_yaml.read_text(), "CROP_PLAN_STUDIO_URL", studio_url))
        # --allow-user-scope-update: the first deploy (and any scope change) adds sql + dashboards.genie to the app.
        run(["agentbricks", "-p", args.profile, "deploy", "--source", str(stage), "--allow-user-scope-update"])
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    agent_url = app_url(agent_app, args.profile)
    override = BUNDLE_DIR / ".databricks" / "bundle" / args.target / "variable-overrides.json"
    write_override(override, "agent_url", agent_url)
    print(f"agent_url = {agent_url} (recorded in {override.relative_to(ROOT)})")
    if not args.skip_bundle_deploy:
        run(["databricks", "bundle", "deploy", "-t", args.target, "--profile", args.profile], cwd=BUNDLE_DIR)


if __name__ == "__main__":
    main(sys.argv[1:])
