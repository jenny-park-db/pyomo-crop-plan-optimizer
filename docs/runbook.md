# Crop Plan Studio demo — runbook

How to stand the demo up in a workspace, give other presenters access, run the 13-minute demo, reset it, and fix
what usually goes wrong. Design: `docs/design.md` ("spec §n" below refers to its sections).

## 1. Prerequisites

- **Workspace:** a Unity Catalog-enabled AWS workspace (built and tested in us-west-2) with serverless jobs, a
  serverless SQL warehouse named `Serverless Starter Warehouse`, Databricks Apps, Genie, Agent Bricks, and AI Runtime
  A10 GPUs. The repo is the source of truth, so a lost or expired workspace is rebuilt, not repaired.
- **Local tools:** Databricks CLI ≥ 1.17 (`databricks --version`), `uv` ≥ 0.9, GNU Make, the Agent Bricks CLI
  0.7.x (`uv tool install "databricks-agentbricks==0.7.*"`), and Node 22 only if you change the app.
- **Login:** `databricks auth login --host https://<workspace>.cloud.databricks.com --profile <profile>`.
- **Settings:** `cp .env.example .env` and set `DATABRICKS_CONFIG_PROFILE`, and set `CROP_PLAN_CATALOG` to an
  existing catalog you can create schemas in (the bootstrap never runs `CREATE CATALOG`, so it also works on
  workspaces that pre-create a catalog and don't allow creating one). If it's empty the bootstrap derives a name from
  the workspace host: some demo workspaces are named `fevm-<name>` and pre-create `<name>_catalog`.
  List other presenters in `CROP_PLAN_PRESENTERS` (comma-separated emails or workspace groups).

## 2. One-command bootstrap

    make bootstrap PROFILE=<profile>

Runs eight steps and prints each one's time. Every step skips finished work, so the same command resumes a
failed bootstrap (or `make bootstrap ARGS="--from precompute"`, `ARGS="--only smoke"`). Skipping means a step never
redoes work that looks complete: `ARGS="--reseed"` rewrites the seeded scenarios and `ARGS="--recompute"` re-runs
precompute (e.g. after the smoke test fails on the stored numbers). If a precompute run from an interrupted bootstrap is
still active, the step stops and prints its URL: wait for it, then re-run.

| Step | What it does | Fresh workspace |
|---|---|---|
| preflight | CLI login, the catalog, recorded as bundle variable `catalog` | seconds |
| tables | schema + 15 empty tables via the warehouse, schema bound to the bundle (Genie checks its tables exist) | ~30 s |
| deploy | `bundle deploy`: schema, volume, experiment, 4 jobs, Genie space, Crop Plan Studio (built and started) | ~4.5 min |
| seed | `seed_data` job: the three seeded scenarios (skipped when present) | ~2 min |
| precompute | three solves + two N=500 stress tests (skipped when stored) | ~16–24 min |
| agent | `scripts/deploy_agent.py`: agent app `agent-bricks-crop-plan-agent`, Studio's `agent_url`, redeploy | ~4.5 min |
| grants | `scripts/grant_presenters.py` for `CROP_PLAN_PRESENTERS` (skipped when empty) | seconds |
| smoke | `scripts/smoke_test.py`: spec §10 at the API level, ~5 min (two agent turns) | ~5 min |

Expect ~30–40 minutes on a fresh install (31 min measured on a clean target) and ~8 minutes for a re-run on a
working one. It ends with
`Smoke test: 9/9 checks passed.` and `Bootstrap finished in … min.` Then open Crop Plan Studio from **Compute →
Apps → crop-plan-studio** (its URL is also in `databricks apps get crop-plan-studio --profile <profile>`).

Workspace-specific values never enter git: `.env` (repo root) and
`bundle/.databricks/bundle/<target>/variable-overrides.json` (`catalog`, `agent_url`) are gitignored.

## 3. Presenter access

    make grant PROFILE=<profile>                  # CROP_PLAN_PRESENTERS from .env
    make grant PROFILE=<profile> ARGS="--presenters a@example.com,Demo Presenters --dry-run"

Least privilege for what Studio and the agent do as the signed-in user: `CAN_USE` on `crop-plan-studio` and
`agent-bricks-crop-plan-agent`, `CAN_RUN` on the Genie space, `CAN_USE` on the warehouse, `USE CATALOG`,
`USE SCHEMA` + `SELECT` on the schema, `MODIFY` on `scenarios`, `runs` and the six input tables, `CAN_VIEW` on
`solve_scenario` / `stress_test` and `CAN_READ` on the experiment (so the Runs links open). No job run
permission: Studio's service principal starts jobs. Grants only add; re-running is safe. Use users or
**account-level** groups: Unity Catalog can't grant to a workspace-local group, so for one of those the workspace
grants succeed and the ten UC grants fail (the script tries all 17, lists failures, and exits non-zero). A presenter's runs and
scenarios are attributed to them (`created_by`, `triggered_by`).

## 4. The demo (~13 minutes)

Before the audience joins: run the demo-day checklist (section 5). Keep two browser tabs: Crop Plan Studio, and the
workspace (for the MLflow run and the bundle). Numbers below are the seeded, deterministic values. Measured times
(dry run 2026-11-03, warm workspace) are in brackets: the waits add up to about 6 minutes, so the talk tracks carry
the rest of the 13.

1. **Inputs → run (1.5 min).** Inputs, *2027 Baseline*: validation passes (no errors). *Re-solve unchanged* →
   Runs: queued → validating → solving → checking → done (~1.5–2.5 min on serverless; keep talking) [measured
   2.0 min: ~60 s queued while serverless starts, ~45 s solving, ~10 s checking; validating flashes past]. Open the
   MLflow run: parameters are the overrides, metrics the KPIs, the plan is an artifact, tags link scenario and job.
   *Talk track:* "Every scenario, from the app or the agent, goes through the same bundle job, lands in Unity
   Catalog keyed by scenario ID, and gets an MLflow run. That's the ops-first pattern."
2. **Results (1.5 min).** Results for the baseline: gross margin $18.81M, planted % below 100, **4 unplanted NE
   fields** (red outlines on the map; all four in NE) [page loads in ~3 s] because seed supply binds on H-112 and the NE-eligible hybrids (H-115, H-204,
   H-209 at 100% in seed utilization). Drill down by region; Export to Excel.
3. **Revision (2 min).** Open *2027 Revision 1* (H-112 supply +10%, diversity cap 0.45). Scenarios → Compare with
   the baseline: gross margin **+$28,254** (18,839,272 vs 18,811,018; the table shows it rounded, **+$28.3K**,
   and "59 fields change"); the change map shows the reassigned fields. [instant: the page opens with the baseline
   and Revision 1 ticked]
   *Talk track:* "A revision is a clone plus overrides, so any scenario re-solves exactly from what's stored."
4. **Infeasible (2 min).** Run *2027 Grower Commitments*: validation passes with a capacity warning, then the run
   ends `infeasible`. The violations list names the binding constraint: **Planting capacity IA/W1 short by 290
   acres**, created by the H-112 commitments pinned to Iowa's first window [measured ~1 min from Re-solve to
   `infeasible`; the warning reads "fixed acres in IA/W1 (2,810) exceed planting capacity (2,520)"]. *Talk track:* "Cheap checks catch bad
   inputs; only the model catches commitments that can't all be honoured, and it says which and by how much."
5. **Agent what-if (2.5 min).** Assistant → Agent: *"What if Iowa loses half its W1 planting capacity to rain?"*
   (~2.5 min: the agent submits through Studio as you, waits for the solve, explains). The tool card shows
   `capacity_pct: {"IA": {"W1": 0.5}}`; the reply links the new scenario and gives gross margin **−$240,972**
   vs the baseline; numbers come only from the solver. [measured ~2.5 min: the agent submits after ~30 s, the solve
   job takes ~75 s, the reply ~30 s more.] The reply's prose rounds ("about 241 thousand dollars, 1.28 percent");
   for the exact figure open the tool card's *Details* → Result: gross 18,570,045.75 vs 18,811,018.
6. **Agent → Genie (1 min).** *"Across today's scenarios, which hybrids always hit their supply limit?"* (~1 min).
   The answer shows Genie's SQL over `seed_utilization`. After step 5 it is **H-115, H-204, H-209** (step 5's
   scenario freed H-112); on a workspace without step 5 it also lists H-112. [measured 40 s; Genie read
   "today's scenarios" as scenarios created today, i.e. step 5's.]
7. **Stress test (1.5 min).** Scenarios → Stress test: stored N=500 results. Revision 1's **P10 gross margin
   $17.81M vs the baseline's $17.69M** (P50 18.59M vs 18.54M): the revision holds up better on the downside.
   [instant]
   Optionally start a live N=50 run (3–8 min, AI Runtime + Ray; mention it and move on) [measured 3.1 min to
   job `SUCCESS` on revision 1].
8. **Close (1 min).** One bundle (dev → prod targets), a governed solver package, MLflow lineage per scenario,
   one-command rebuild (`make bootstrap`). It maps to delivery routing: stores ↔ fields, truck and pallet capacity ↔
   seed supply, delivery days ↔ planting windows, demand-fill band ↔ diversity cap.

## 5. Demo-day checklist

Allow 15 minutes. The 2026-11-03 dry run of section 4 took about 6 minutes of waiting on the screen (step 1 2.0 min,
step 4 1 min, step 5 2.5 min, step 6 40 s, the rest instant), which fits 13 minutes with the talk tracks.

- [ ] `databricks current-user me --profile <profile>` works (else `databricks auth login --profile <profile>`).
- [ ] `make smoke PROFILE=<profile> ARGS=--skip-agent` → `7/7 checks passed` (20 s). Before a big demo, run it
      without `--skip-agent` (5 min) to warm the agent and the serverless pool.
- [ ] `make reset PROFILE=<profile>` (preview), then `make reset PROFILE=<profile> ARGS=--yes`: last demo's
      scenarios, runs, and live stress tests gone; seeded results kept.
- [ ] If the workspace has an expiry date, it is after the demo date + 1 day (or rebuild with `make bootstrap`).
- [ ] Open Studio once (sign-in, app warm), Results for the baseline, and the Agent tab (no "not deployed" banner).
      On a new workspace each person's first visit shows a **Permission Requested** consent page for the app's
      scopes (SQL, Genie): click *Authorize* before the audience is watching.
- [ ] Every presenter has run `make grant` for them or opened Studio successfully.
- [ ] Start a throwaway solve ~5 minutes before (Inputs → Re-solve on the baseline) so serverless is warm, then
      `make reset ARGS=--yes` again, or leave it: step 1 re-solves anyway.

## 6. Reset between demos

    make reset PROFILE=<profile>              # shows what it would delete
    make reset PROFILE=<profile> ARGS=--yes   # deletes

Removes every app/agent scenario (with inputs, runs, outputs), every run of a seeded scenario that precompute
didn't make, every run whose scenario no longer exists (integration-test leftovers), and every stress test except
the two N=500 ones. Keeps the seeded scenarios, their precompute solves,
and the stored stress results. MLflow runs stay (harmless). If a run is still active it says so; wait for it.

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Error: … refresh token is invalid` / `invalid_grant` | OAuth expired: `databricks auth login --profile <profile>` |
| Bootstrap stops in preflight: `Catalog '…' isn't visible` | The catalog doesn't exist or you can't use it: `make bootstrap ARGS="--catalog <name>"` or `CROP_PLAN_CATALOG` in `.env` |
| First deploy by hand fails: `cannot create resources.genie_spaces … Schema '….fields' does not exist` | The tables don't exist yet. Use `make bootstrap` (its tables step creates them) |
| `Schema '…' already exists (SCHEMA_ALREADY_EXISTS)` | The schema exists but the bundle doesn't manage it. `make bootstrap ARGS="--from tables"` binds it |
| App `UNAVAILABLE`, deploy says `0 changed` | An earlier deploy failed after creating the app. `make bootstrap ARGS="--only deploy"` (runs `bundle run crop_plan_studio`) |
| Agent tab: "not deployed for this app yet" | `agent_url` isn't recorded: `make bootstrap ARGS="--only agent"` |
| Agent tab: "You do not have permission to use the planning agent" | No `CAN_USE` on the agent app: `make grant` for that user |
| Studio pages show "permission" errors for a presenter | Missing UC/warehouse grants: `make grant` |
| A solve sits in `queued` for minutes | Serverless cold start or the job queue; Runs syncs with the Jobs API every poll. Over 10 min: open the job run link |
| Step 6 lists H-112 too / not at all | Expected: it depends on which scenarios ran today. Reset before demos |
| AI Runtime task fails `bash: …/command.sh: Input/output error` | The script was uploaded executable. Keep `bundle/stress/*.sh` mode 644 (`tests/test_bundle.py` checks) |
| App build fails with `404` fetching npm packages | `package-lock.json` points at a private registry or mirror: `cd app && npm run lock:public`, commit |
| App types out of date after a schema change | Typegen needs `.env` exported and the warehouse: `cd app && set -a && . ./.env && set +a && npm run typegen`; commit `shared/appkit-types`, revert the tsconfig rewrite |
| `agentbricks deploy`: `Error downloading source code … no files found` | Deployed from a gitignored folder. Always deploy via `scripts/deploy_agent.py` (stages outside the repo) |
| Smoke test `baseline solve` fails on gross margin only | The solver or generator changed the optimum (a new HiGHS/Pyomo resolved from PyPI). Pin the version in `pyproject.toml` or update the expected values deliberately |

## 8. Known limitations

- Agent MLflow traces: trace records appear in `/Shared/agentbricks_traces/crop-plan-agent`, but span uploads fail
  from the Apps runtime. The evaluation logs its own client-side traces.
- One agent deployment serves one Studio (`dev`). A `prod` target deploy gets Studio and the Genie space, not a
  second agent (`make bootstrap TARGET=prod` would point the one agent at prod; use `CROP_PLAN_AGENT_NAME` for a
  separate one).
- Minor known issues: a crafted request with unknown hybrid/region/window names gets 200 then an `invalid` run
  instead of 400 (the form blocks it); a run_id kept after a failed submit can dedupe to the earlier run; two tabs
  create two scenarios for one click each; sync throws on a single Delta conflict in `markFailed` and the 3 s
  throttle shares that rejection; Results reads the latest 300 runs, so very old scenarios can show "no runs"; a
  failed live stress run shows the job's generic `state_message`; 500 responses pass warehouse error text through;
  the Agent tab gives up after 10 minutes; agent replies sometimes use Markdown bold (shown as `**`).
- The demo was built and tested on AWS; Azure (Gurobi licensing) is untested (spec §12).

## 9. Teardown

    cd bundle && databricks bundle destroy -t dev --profile <profile> --auto-approve   # schema, tables, jobs, app, Genie
    agentbricks -p <profile> deployments delete agent-bricks-crop-plan-agent --delete-source -y
    agentbricks -p <profile> memory stores delete crop-plan-agent-memory -y
    agentbricks -p <profile> sessions stores delete crop-plan-agent-sessions -y
    databricks experiments delete-experiment \
      "$(databricks experiments get-by-name /Shared/agentbricks_traces/crop-plan-agent --profile <profile> -o json | jq -r .experiment.experiment_id)" --profile <profile>

Or delete the workspace. Rebuilding is `make bootstrap`.

**Rebuilding in a new workspace.** A from-zero bootstrap of a clean target took 31 min end to end and ended with
`Smoke test: 9/9` and the original numbers. In a brand-new workspace:

1. `databricks auth login --host <new host> --profile <new profile>`.
2. Clone the repo to an empty folder (no `bundle/.databricks/` state), `cp .env.example .env`, and set
   `DATABRICKS_CONFIG_PROFILE=<new profile>` and `CROP_PLAN_CATALOG=<existing catalog>`.
3. `time make bootstrap` → expect a `bundle deployment bind … crop_plan` line in `tables`, `Created
   genie_spaces.crop_plan_results` in `deploy`, and `Smoke test: 9/9` with gross 18,811,018 / 18,839,272.
4. `git status --short` prints nothing (only gitignored files were written).
