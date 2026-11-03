# Pyomo Crop Plan Demo — Design

- **Date:** 2026-10-28
- **Status:** implemented

## 1. Purpose and context

Build a working Databricks demo in which crop planners create, revise, compare, and stress-test a
**2027 hybrid-to-field plan** produced by a mixed-integer optimization model, with an AI agent for
natural-language what-ifs and Q&A.

**Audience:** Data/ML platform teams and business planners at organizations that run (or are
building) optimization models and want an "ops first" pattern: standardized, bundle-based pipelines
whose outputs (timestamped, keyed by `scenario_id`) are consumed by an application used by planners.
The architecture follows a predict → optimize reference pattern (Pyomo MIP, HiGHS, validate → solve →
validate, UC + MLflow + Jobs + bundles).

**Reusability:** The domain data is interchangeable; the story arc is the point. The same architecture
fits other planning problems such as direct-to-store delivery routing or production allocation
(Gurobi or HiGHS MIP; inputs → run → summary/detail → map → scenarios/versioning).

**Inspiration:** `databricks-industry-solutions/supply-chain-stress-test` (Pyomo + HiGHS, Ray-scaled
disruption scenarios, LangGraph agent with an optimization tool). We reuse the pattern and agent
design, not its chat-only frontend.

### Success criteria

1. A planner can go from baseline inputs → validated run → results/map → revision → comparison → stress
   test entirely in the app, live, in ~13 minutes.
2. Every scenario (app-triggered or agent-triggered) goes through the same job, is persisted in UC, and
   has an MLflow run per solve with its parameters, KPIs, and plan artifact.
3. Infeasible or penalized results are explained (which constraint binds and by how much), not just
   flagged. The demo includes a deliberately infeasible scenario to show this.
4. The agent answers what-ifs by calling the solver (no invented numbers) and answers cross-scenario
   questions through Genie with visible SQL.
5. Everything except the agent deploys from one Declarative Automation Bundle; the agent deploys with
   the Agent Bricks CLI.
6. **Rebuildable from zero.** If the workspace is deleted, a single bootstrap command stands the
   whole demo up again in a new workspace. Nothing exists only in the workspace.
7. Any past scenario can be re-solved exactly from its stored inputs and overrides.

### Non-goals

Model tuning/accuracy, a real planting-window ML model (forecasts are synthetic), Excel template
upload, manual editing of individual assignments, RBAC/roles beyond per-user attribution, ERP or
execution integration, mobile layouts, production hardening.

## 2. Environment

- **Workspace:** a dedicated AWS workspace with Unity Catalog and serverless compute. Treated as disposable
  (see §11, rebuildability).
- **Compute:** serverless SQL warehouse (app reads, Genie); serverless jobs (seed + solve); AI Runtime
  single A10 node for Ray stress tests (CPU cores do the solving; GPU idle—acceptable for demo).
- **Identity:** the app and agent act **on behalf of the signed-in user (OBO)**, so `created_by` and
  `triggered_by` are real user identities. Users need UC grants (read the schema; write `scenarios`, `runs`, and the six input tables),
  `CAN_USE` on both apps and the warehouse, and `CAN_RUN` on the Genie space; `scripts/grant_presenters.py`
  (a bootstrap step, also `make grant`) sets these. Exception: `jobs` is not an Apps user scope, so job runs
  are triggered by the app/agent service principal; every job takes a `triggered_by` parameter
  carrying the signed-in user's email and stores it.
- **Beta/unknown dependencies, validated before building on them:**
  1. Agent Bricks CLI (`databricks-agentbricks`, Beta): `deploy` works in the workspace; how a Databricks App
     can call the deployed agent (request format, auth). The CLI docs don't document this.
  2. **OBO:** the app can call Jobs, SQL, and the agent as the signed-in user; the agent can run its
     tools (SQL insert, job run-now) as the calling user.
  3. `pyomo`/`highspy` installable in the agent runtime (only needed if a tool ever solves inline; the
     default design runs solves via Jobs, so this is a soft dependency).
  4. AI Runtime GPU availability in the workspace; `ray_init()` from `databricks.air` works as a job task.
  5. Map tile servers (OpenStreetMap) reachable from the Databricks App.
  6. Whether bundles can create the Genie space natively (otherwise it is created by script).

### Fallbacks

| If this fails | Fall back to |
|---|---|
| App can't call the deployed agent | Embed or link the agent's built-in chat UI in the Assistant panel |
| Agent can't run tools as the calling user | App passes the user's email to the agent as a tool argument; tools run as the agent identity and record that email in `created_by` |
| AI Runtime / Ray unavailable | Serverless Spark `applyInPandas` fan-out, one solve per scenario (same results table) |
| Map tiles blocked | SVG plot of field points on a lat/lon graticule (runtime switch CROP_PLAN_MAP_MODE=svg) |
| Bundle can't create Genie space | Script creates it from checked-in instructions and example SQL |

## 3. Domain and data

Catalog from the bundle variable `catalog` (default `pyomo_crop_plan_demo_catalog`; the catalog must already exist: the bootstrap never runs `CREATE CATALOG`, so it also works on workspaces that pre-create a catalog and don't allow creating one), schema `crop_plan`. All data synthetic, seeded by a deterministic generator
(fixed random seed) so demo numbers are reproducible.

### Inputs (all keyed by `scenario_id`)

Creating or cloning a scenario **copies the parent's input rows under the new `scenario_id`**
(~150 fields, so this is cheap). Overrides are applied at solve time and stored on the scenario row.
Together, the per-scenario input rows plus the overrides make any scenario exactly reproducible.

| Table | Grain (within a scenario) | Key columns |
|---|---|---|
| `fields` | field | `scenario_id, field_id, grower_id, region (IA/IL/NE), acres, lat, lon, soil_class, rm_min, rm_max` |
| `hybrids` | hybrid | `scenario_id, hybrid_id (e.g. H-112), relative_maturity, seed_cost_per_unit, units_per_acre, disease_tolerance` |
| `seed_supply` | season × hybrid | `scenario_id, season, hybrid_id, units_available` |
| `yield_forecast` | region × soil_class × hybrid × window | `scenario_id, exp_yield_bu_ac, yield_sd, source_model_version` (framed as the upstream planting-window model output) |
| `planting_capacity` | region × window | `scenario_id, region, window (W1–W4), acres_capacity` |
| `fixed_requests` | field | `scenario_id, field_id, hybrid_id, window (nullable)` — grower-requested assignments |

Scale: ~150 fields, 25 growers (6 fields each), 3 regions, 8 hybrids, 4 windows. W1–W4 are ~4-week
planting windows (mid-April → early July); planting capacity per region is 25/40/35/25% of the
region's acres for W1/W2/W3/W4. NE fields allow relative maturity 110–114 only (H-115, H-204, H-209).
The baseline is tuned so that supply binds on H-112 and the NE-eligible hybrids (H-115, H-204, H-209)
and ~4 NE fields go unplanted (the demo's opening "tension").

### Seeded scenarios (fixed IDs)

| `scenario_id` | Purpose |
|---|---|
| `baseline-2027` | The "2027 Baseline"; feasible; supply binds on H-112 and the NE-eligible hybrids |
| `grower-commitments-2027` | Same inputs plus a `fixed_requests` set of H-112 commitments that **fit within total H-112 supply** (so validation passes, with a "capacity below fixed acres" warning) but are pinned to IA/W1 beyond that window's planting capacity. **Deliberately infeasible**, caught only by the solver; diagnosis names the IA-W1 capacity constraint and the acre shortfall |
| `revision-1-2027` | Pre-built Revision 1 (H-112 supply +10%, diversity cap 0.45), with precomputed stress-test results for demo step 7 |

Validation errors (`invalid`) and solver infeasibility (`infeasible`) are deliberately distinct:
the first is caught by cheap pre-solve checks, the second only by the model.

### Scenario settings (`overrides` schema)

```json
{
  "supply_pct": {"H-112": 1.10},          // multiplier on units_available, per hybrid
  "capacity_pct": {"IA": {"W1": 0.5}},     // multiplier on planting capacity
  "diversity_cap": 0.40,                    // max share of a grower's total acres on one hybrid
  "unplanted_penalty_per_acre": 150,
  "corn_price_per_bu": 4.25,
  "fixed_requests_enabled": true,
  "solver": "highs",                        // "gurobi" supported by config, not installed
  "time_limit_s": 60,
  "mip_rel_gap": 0.001,                     // stop within 0.1% of the best bound
  "threads": 1,                             // single-thread HiGHS is deterministic (and faster here)
  "random_seed": 2027
}
```

The same schema is used by the app form, the agent tool, and the stress-test disruption generator.

### Outputs

| Table | Contents |
|---|---|
| `scenarios` | `scenario_id, name, parent_scenario_id, season, overrides (JSON), created_by (user, via OBO), created_at, source ('app'/'agent'/'stress'/'seed'), status` |
| `runs` | One row per solve attempt: `run_id, scenario_id, job_run_id, mlflow_run_id, triggered_by, status, solver, solver_version, model_version, started_at, ended_at, error, infeasibility_reason, mip_gap, termination, objective, runtime_s, diagnosis ('explained'/'fixed_requests_impossible'/'diagnosis_failed' when infeasible), submitted_at` |
| `plan_assignments` | `scenario_id, run_id, field_id, hybrid_id (nullable), window (nullable), acres, exp_yield, exp_margin, is_fixed` |
| `run_summary` | `scenario_id, run_id, acres_planted_pct, gross_margin, unplanted_penalty_total, net_margin, unplanted_fields, violations_count` |
| `seed_utilization` | Long format: `scenario_id, run_id, hybrid_id, units_used, units_available, pct` |
| `violations` | `scenario_id, run_id, rule, entity, severity ('hard'/'penalized' post-solve, 'error'/'warning' validation, 'binding' diagnosis), detail` |
| `stress_test_results` | `stress_id, scenario_id, sample_id, disruption (JSON), gross_margin, acres_planted_pct, status` |
| `stress_test_summary` | `stress_id, scenario_id, n, p10/p50/p90 gross margin, fragile_fields, fragile_hybrids, n_solved, n_invalid, n_infeasible, n_failed, seed, job_run_id, mlflow_run_id, triggered_by, created_at` |

`scenarios` has no `mlflow_run_id`: a scenario can have several solves, so the MLflow link lives on
`runs` (1:1 with a solve). Compare uses **gross margin** so scenarios with different penalty settings
remain comparable; net margin is shown alongside.

Status lifecycle (`runs.status`): `queued → validating → solving → checking → done | invalid | infeasible | failed`.

### Run records and MLflow linkage

- The **app or agent writes the `runs` row at submit time** with status `queued`, then updates
  `job_run_id` once the Jobs API returns it. There is never a gap where a submitted run is invisible.
- The solve job updates `status` at each stage and writes `mlflow_run_id` in the same update.
- While a run is active, **polling syncs state from the Jobs API**, so a crash before the job can
  write its own failure status still surfaces as `failed` with the error text.
- Each MLflow run is tagged with `scenario_id`, `run_id`, and `job_run_id` explicitly (not relying on
  system tags) and named after the scenario, so lookup works in both directions.

## 4. Optimization model (`cropplan` package)

**Decision variables:** `x[f,h,w] ∈ {0,1}` (field f gets hybrid h in window w); `u[f] ∈ {0,1}` (field
unplanted). Only eligible (f,h) pairs (`rm_min ≤ RM(h) ≤ rm_max`) are created.

**Objective (maximize net margin):**
Σ x·acres·(exp_yield·price − units_per_acre·seed_cost) − Σ u·acres·unplanted_penalty

Gross margin is the first term; the second is reported separately as the unplanted penalty.

**Constraints:**
1. Each field is assigned once or left unplanted: Σ_{h,w} x[f,h,w] + u[f] = 1
2. Seed supply: Σ_{f,w} x·acres·units_per_acre ≤ units_available·supply_pct, per h
3. Planting capacity: Σ_{f∈region,h} x·acres ≤ acres_capacity·capacity_pct, per region and window
4. Diversity cap: Σ_{f∈grower,w} x·acres ≤ diversity_cap · (grower's **total** acres), per grower and
   hybrid. Unplanted land counts in the denominator, which keeps the constraint linear and simple to
   explain.
5. Fixed requests (if enabled): if the window is specified, `x[f,h_req,w_req] = 1`; if null,
   `Σ_w x[f,h_req,w] = 1`.

Because constraint 1 allows any field to go unplanted, the model is infeasible **only** when fixed
requests force assignments that collide with seed supply, capacity, or the diversity cap.

**Package modules:**
- `cropplan.data`: load inputs for a `scenario_id` into typed frames
- `cropplan.validate`: pre-solve checks → list of errors and warnings. Errors include: fixed requests
  exceed supply, fixed requests exceed a grower's diversity cap, a field with no eligible hybrid that
  is also fixed, missing forecast rows. Warnings include: a field with no eligible hybrid, capacity
  below fixed acres.
- `cropplan.model`: build the Pyomo model
- `cropplan.solve`: solve with the solver from config (HiGHS); returns status and gap
- `cropplan.diagnose`: on infeasible, re-solve with every hard constraint relaxed by penalized slack
  variables; report the constraints with nonzero slack and their amounts
- `cropplan.postcheck`: re-verify business rules on the solution and write `violations`
- `cropplan_jobs` (separate import package, same wheel): UC table I/O behind a `TableStore`
  interface, MLflow logging (params = overrides, metrics = summary KPIs, artifact =
  `plan_assignments.parquet`, tags = scenario_id, run_id, job_run_id, solver and model version), and
  the job entry points. `cropplan` itself has no Spark/MLflow dependency.
- `cropplan.disrupt`: sample disruption overrides for stress tests (seed shortfall per hybrid, lost
  capacity per region/window, lost acreage per region); seeded so results are reproducible

## 5. Platform architecture

```
Planner ─▶ Databricks App "Crop Plan Studio" (AppKit/React, OBO)
             │ SQL reads (warehouse)   │ Jobs API run-now     │ agent call
             ▼                          ▼                      ▼
   UC <catalog>.crop_plan           solve_scenario job      Agent (Agent Bricks CLI, LangGraph)
   inputs + outputs              stress_test job (Ray)    tools: solve_scenario → job
             ▲                          │                        stress_test_plan → job
             └──────────────────────────┘                        genie_agent → Genie space
   MLflow experiment /Shared/pyomo_crop_plan_scenarios — one run per solve, tagged by scenario_id
```

### Components

1. **Bundle (`databricks.yml`):** catalog and schema, the jobs, the app, and the MLflow experiment.
   The agent's app URL (`agent_url`, recorded by `scripts/deploy_agent.py`) and the SQL warehouse ID are **bundle variables**. (`agent_url` defaults to `none`, because the Apps API rejects an empty env value.) Targets `dev` and `prod`
   (`dev` is a plain target, not `mode: development`, because development mode renames the schema
   and experiment; `prod` uses schema `crop_plan_prod` and experiment
   `/Shared/pyomo_crop_plan_scenarios_prod`)
   (demo uses `dev`; `prod` illustrates the promotion story, though in a single workspace it is
   a narrative rather than a true environment promotion). The bundle syncs `bundle/` and `app/` (`sync.paths`), so bundle files land under `${workspace.file_path}/bundle/`.
2. **Jobs:**
   - `seed_data`: one-off; generates the synthetic inputs and the three seeded scenarios
   - `solve_scenario(scenario_id, run_id)`: serverless; validate → solve → diagnose if infeasible →
     postcheck → write outputs + MLflow; updates `runs.status` at each stage
   - `stress_test(scenario_id, n)`: AI Runtime A10; `ray_init()`; `n` Ray tasks, each sampling a
     disruption and solving with `cropplan`; writes `stress_test_results` and the summary. Stress
     samples aren't logged as individual MLflow runs; one parent run per stress test holds the
     summary metrics. Three tasks: serverless `prepare` (UC → files in volume `stress`) → AI Runtime
     `solve` (Ray; AI Runtime has no Spark session and takes no task parameters) → serverless `load`
     (files → UC). Per-sample solve settings: `mip_rel_gap=0.01`, `time_limit_s=30`. The AI Runtime
     task's own MLflow run, in the scenarios experiment, is the stress test's parent run.
   - `precompute`: runs `solve_scenario` on the three seeded scenarios and `stress_test` (N=500,
     fixed seed) on `baseline-2027` and `revision-1-2027`, so the demo shows stored results.
3. **Storage:** Delta only. App and agent writes (scenario rows, input copies, `runs` rows) go through
   the SQL warehouse as the signed-in user. Lakebase is out of scope unless manual assignment editing
   is added later.
4. **Genie space "Crop Plan Results":** tables `scenarios, runs, run_summary, seed_utilization,
   plan_assignments, violations, stress_test_summary, fields, hybrids`; instructions defining KPIs
   (gross margin, net margin, planted %, seed utilization); about 10 example SQL queries. Defined as a bundle
   `genie_spaces` resource in `genie/crop_plan_results.yml`, so it is recreated by `bundle deploy`.
5. **App:** AppKit (Node/TypeScript + React). Backend routes: create/clone scenarios and open `runs` rows (as the
   signed-in user), trigger jobs and sync their state from the Jobs API (as the app service principal,
   with `triggered_by` from the request's `x-forwarded-email`), and proxy the Agent tab to the agent's `/api/invocations` with the signed-in user's token (background invocations the browser polls). It also serves the agent's reads: run and scenario reports and stress tests by ID.
   Reads are AppKit `.obo.sql` queries and Genie runs as the user (scopes `sql`, `dashboards.genie`).
   Export to Excel is built in the browser.
6. **Agent:** see §7.

## 6. App screens

Left nav + right-docked Assistant panel with two tabs: Ask data (Genie) and Agent.

1. **Inputs:** Start from the 2027 Baseline or clone any scenario. The validation panel shows errors
   (block the run) and warnings. Settings form for the overrides schema. "Run as new scenario" (requires a
   name; clones the source) and "Re-solve unchanged" (runs the selected scenario as stored).
2. **Runs:** Table with status chips, solver and model version, triggered by, source (app or agent),
   times, error or infeasibility reason, links to the job run and MLflow run. Polls while active.
3. **Results (per scenario):** KPI tiles; field map (color = hybrid, size = acres, red outline =
   unplanted, click → field detail); drill-down table by region/grower/field/hybrid/window with
   filters and Export to Excel; violations list.
4. **Scenarios:** Lineage tree; Compare 2–3 scenarios (gross margin deltas, changed-fields list,
   change map); Stress test tab (stored results, with optional live run; margin distribution with
   P10/P50/P90, fragile fields and hybrids).
5. **Assistant:** Agent chat. Scenario IDs in replies link to Results; Genie answers show their SQL.

Required states on every data view: loading, empty, and error.

## 7. Agent

- **Scaffold:** `agentbricks init --framework langgraph --name crop-plan-agent --disable-chat-app` in `agent/` (the API-only scaffold is tracked, except `uv.lock`); deployed by `scripts/deploy_agent.py`, which binds the Genie space and Crop Plan Studio's URL at deploy time.
- **LLM:** Claude Sonnet via Foundation Model APIs. The system prompt is adapted from the
  supply-chain-stress-test agent: explain solver output in plain business language, cite numbers
  only from tool results, keep replies under 300 words.
- **Tools:**
  - `solve_scenario(base_scenario_id, overrides, name)` (custom Python): submit the what-if to Crop Plan Studio's `POST /api/studio/runs` as the calling user (`mode: new`, `source: agent`), so the app's validation, dedupe, and job start apply and `created_by`/`triggered_by` are that user → poll the run report up to **240 s** (allowing for serverless cold start) → return KPIs, the change against the base scenario (absolute and percent), hybrids at their supply limit, violations or the infeasibility reason, and the scenario ID. On timeout, return the run ID and status.
  - `stress_test_plan(scenario_id, n=50)` (custom Python, n 1–100 like the app's live run): start it through Crop Plan Studio and return the `stress_id`. `get_stress_test(stress_id)` returns the summary when it's done.
  - `genie_agent` (`agent.toml` `kind = "genie_agent"`, `space_id` = Crop Plan Results).
- **Routing guidance in the prompt:** plan changes → `solve_scenario`; data and history questions →
  `genie_agent`; robustness questions → `stress_test_plan`.
- **Weather translation:** weather what-ifs are framed as lost capacity. "Iowa loses half its W1
  planting capacity" maps directly to `capacity_pct: {"IA": {"W1": 0.5}}`. For looser phrasing such as
  "a week's delay," the prompt documents a mapping (one week ≈ 25% of that window's capacity), and the
  agent must state the assumption in its reply. Because the assumption appears in the tool-call
  arguments, it counts as grounded.
- **Managed features:** session store, memory store, and MLflow tracing (all CLI defaults).
- **Evaluation:** ~15 questions (what-ifs, data questions, robustness questions, off-topic) scored
  with MLflow judges for correct tool selection and groundedness (numbers appear in tool outputs or
  stated assumptions). Tool choice and grounded numbers are code scorers and form the pass gate; an MLflow `make_judge` groundedness judge is reported as an advisory second opinion.

## 8. Error handling

| Situation | Behavior |
|---|---|
| Validation errors | Status `invalid`; errors listed in the app and returned to the agent; no solve |
| Infeasible | Diagnose with slack variables; status `infeasible` with a named binding constraint and amount |
| Solver time limit | Return the best solution found as `done`, with `mip_gap` shown |
| Job failure | Status `failed` with the error text and a link to the job run (synced from the Jobs API if the job couldn't write it) |
| Agent tool timeout | Return the run ID and current status; planner checks Runs |

## 9. Testing

- **Unit (pytest, local, run in CI):** a 5-field instance with a known optimum; a deliberately
  infeasible instance (diagnosis names the right constraint); validation cases (including fixed
  requests vs diversity cap); overrides schema checks; disruption sampler bounds and seeding.
- **Integration (deployed dev target):** seed → solve baseline → assert KPIs in the expected band →
  solve `grower-commitments-2027` and assert `infeasible` with the IA-W1 capacity constraint named →
  stress test with N=20 → re-solve an older scenario with the same settings (threads=1, fixed seed,
  gap 0.1%, time limit not reached) and assert solver termination `optimal` and objective equal to the
  original within 1e-6. Assignments aren't compared row by row, because ties between equally good
  solutions are allowed.
- **Agent:** the evaluation set in §7; pass bar is correct tool on ≥ 90% and no ungrounded numbers.
- **App:** browser walkthrough of the demo script with no console errors; loading, empty, and error
  states checked.

## 10. Demo script (~13 minutes)

1. Inputs: the 2027 Baseline validates → Run → Runs status → MLflow run.
2. Results: KPIs and map; 4 unplanted NE fields because seed supply binds.
3. Revision: H-112 supply +10% and diversity cap 0.45 → Compare with baseline; map of what changed.
4. Infeasible: run "2027 Grower Commitments" → passes validation (with a capacity warning) →
   status `infeasible` → the app names the binding IA-W1 capacity constraint and the acre shortfall
   created by the H-112 commitments.
5. Agent: "What if Iowa loses half its W1 planting capacity to rain?" → new scenario plus a trade-off
   explanation.
6. Agent → Genie: "Across today's scenarios, which hybrids always hit their supply limit?" → answer
   with SQL.
7. Stress test: show stored N=500 results for `revision-1-2027` next to the baseline (P10 margin holds
   up better); optionally launch a live N=50 run.
8. Close: one bundle (dev → prod), a governed solver package, MLflow lineage per scenario, one-command
   rebuild — the "ops-first" pattern for optimization; it maps directly to delivery routing (stores ↔
   fields, truck and pallet capacity ↔ seed supply, delivery days ↔ planting windows, demand-fill band
   ↔ diversity cap).

## 11. Rebuildability and repository

The workspace is disposable; the repo is the source of truth.

**Bootstrap:** one command (`make bootstrap PROFILE=<profile>`, wrapping `scripts/bootstrap.py`) takes a Databricks CLI
profile for a fresh workspace and runs: preflight (login, catalog) → create the schema and its tables, empty, and bind
the schema to the bundle → bundle deploy (jobs, Genie space, app) → `seed_data` → `precompute` → deploy the agent and
point the app at it → grant presenter permissions → smoke test (spec §10 at the API level). Every step skips work that
is already done, so re-running the command resumes a failed bootstrap. The tables come first because the Genie space
can only be created once its tables exist. `docs/runbook.md` documents prerequisites, presenter grants, the demo,
resetting between demos, and troubleshooting.

**Principles:**
- Fixed IDs for seeded scenarios, so the demo script never depends on generated IDs.
- Deterministic data generation and seeded stress sampling, so numbers reproduce across rebuilds.
- Workspace-specific values (host, warehouse ID, agent endpoint, user lists) live in bundle variables
  and a gitignored `.env`; no secrets in the repo.
- Genie space, grants, and agent config are scripted from checked-in files.

**Repo layout (GitHub-ready from the start):**

```
bundle/        databricks.yml, job and app resource definitions, targets
src/cropplan/  solver package (+ data generator)
app/           Crop Plan Studio (AppKit)
agent/         Agent Bricks project, prompts, eval set
genie/         space instructions and example SQL
scripts/       bootstrap, presenter grants, smoke test, demo reset, agent deploy
tests/         unit and integration tests
docs/          this design, runbook
```

CI runs the pytest unit tests on each push.

## 12. Open questions (not blocking)

- Diversity cap denominator is total grower acres (§4); switch to share of planted acres if that
  better matches how planners think.
- Whether to also validate the bundle on Azure (portability; Gurobi license handling).
- Whether to add a second optimization model (e.g., seed-lot drying allocation) to the same app shell.
