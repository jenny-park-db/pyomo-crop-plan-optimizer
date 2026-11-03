# Pyomo Crop Plan Demo

Crop planners build, revise, compare, and stress-test a hybrid-to-field plan produced by a Pyomo
mixed-integer model on Databricks: a solver package and jobs in one bundle, results in Unity Catalog with an MLflow
run per solve, the Crop Plan Studio app, a Genie space, and an Agent Bricks agent for what-ifs. All data is
synthetic. Design: `docs/design.md` ("the spec" in code comments; `§n` refers to its sections).

## Quick start

    cp .env.example .env              # set DATABRICKS_CONFIG_PROFILE, CROP_PLAN_CATALOG (and CROP_PLAN_PRESENTERS)
    databricks auth login --host https://<workspace>.cloud.databricks.com --profile <profile>
    make bootstrap PROFILE=<profile>  # ~30-40 min on a fresh workspace; safe to re-run

Then follow **`docs/runbook.md`**: presenter access (`make grant`), the 13-minute demo script, the demo-day
checklist, resetting between demos (`make reset`), troubleshooting, and known limitations.

## Layout

    bundle/        databricks.yml, job and app resources, targets dev/prod
    src/cropplan/  solver package (+ data generator); src/cropplan_jobs/ job entry points and UC/MLflow I/O
    app/           Crop Plan Studio (AppKit)
    agent/         Agent Bricks project, prompt, evaluation set
    genie/         Genie space definition (instructions, example SQL)
    scripts/       bootstrap, grant_presenters, smoke_test, reset_demo, deploy_agent
    tests/         unit tests (CI) and integration tests against a deployed workspace (`-m integration`)
    docs/          design.md, runbook.md

## Tests

    make test      # root pytest, app vitest, agent pytest (what CI runs)

Integration tests (need a deployed workspace): `UV_HTTP_TIMEOUT=180 uv run pytest -m integration tests/integration -v`.

No `uv.lock` is committed: `uv sync` (or `uv run`) resolves the declared dependency ranges in `pyproject.toml`
fresh from your package index, as CI does. The app's `package-lock.json` resolves from the public npm registry.
