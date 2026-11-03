/**
 * POST /api/studio/runs: create (or reuse) the scenario, open the runs row as `queued`, then start the
 * solve job as the app SP. The browser sends one run_id per form (newRunId); a repeat of that run_id —
 * a double click, a retry, a second tab — returns the first run instead of starting another job.
 */
import { checkId, checkName, scenarioIdFor } from '../../shared/studio/ids';
import { parseOverrides, stableJson } from '../../shared/studio/overrides';
import { num, strOrNull } from '../../shared/studio/format';
import type { Tables } from './config';
import type { JobsClient } from './jobs';
import { INPUT_TABLES, isWriteConflict, statements as S, type SqlRunner } from './sql';

export interface SubmitRequest {
  mode: 'new' | 'resolve';
  source_scenario_id: string;
  run_id: string;
  name?: string;
  overrides?: unknown;
  /** Who asked for the scenario (scenarios.source). A provenance label, not identity: triggered_by is the header. */
  source?: ScenarioSource;
}

export const SCENARIO_SOURCES = ['app', 'agent'] as const;
export type ScenarioSource = (typeof SCENARIO_SOURCES)[number];

export interface SubmitResult {
  run_id: string;
  scenario_id: string;
  job_run_id: string | null;
  status: string;
  deduped: boolean;
  error?: string;
}

export class SubmitError extends Error {
  readonly status: number;
  readonly path?: string;
  constructor(status: number, message: string, path?: string) {
    super(message);
    this.status = status;
    this.path = path;
  }
}

export interface SubmitDeps {
  sql: SqlRunner;
  jobs: JobsClient;
  t: Tables;
  solveJobId: number;
}

async function existingRun(deps: SubmitDeps, runId: string): Promise<SubmitResult | null> {
  const [row] = await deps.sql.run(S.findRun(deps.t), { run_id: runId });
  if (!row) return null;
  const jobRunId = strOrNull(row.job_run_id);
  return { run_id: runId, scenario_id: String(row.scenario_id), job_run_id: jobRunId, status: String(row.status), deduped: true };
}

async function cloneScenario(deps: SubmitDeps, sourceId: string, newId: string, name: string, season: number,
                             overridesJson: string, email: string, source: ScenarioSource): Promise<void> {
  // The slug can collide with a scenario someone else made (name "Revision" + a run_id ending 1-2027 is the
  // seeded revision-1-2027): refuse rather than no-op the copy and later delete that scenario's rows.
  const [taken] = await deps.sql.run(S.findScenario(deps.t), { scenario_id: newId });
  // A retry with the same run_id after this clone landed (the scenarios row is written last, so it's complete)
  // but before the run opened: same parent, same creator — reuse it instead of refusing our own scenario.
  if (taken && strOrNull(taken.parent_scenario_id) === sourceId && strOrNull(taken.created_by) === email) return;
  if (taken) {
    throw new SubmitError(409, `Scenario ${newId} already exists; pick a different name for the new scenario`, 'name');
  }
  const copied: Array<(typeof INPUT_TABLES)[number]> = [];
  try {
    for (const table of INPUT_TABLES) {
      await deps.sql.run(S.copyInputs(deps.t, table), { new_id: newId, source_id: sourceId });
      copied.push(table);
    }
    await deps.sql.run(S.insertScenario(deps.t), {
      scenario_id: newId, name, parent_id: sourceId, season, overrides: overridesJson, created_by: email, source,
    });
  } catch (e) {
    // Undo only the copies this request completed; the scenarios row is written last, so a failure never left one.
    for (const table of copied) {
      await deps.sql.run(S.deleteScenarioRows(deps.t, table), { scenario_id: newId }).catch(() => undefined);
    }
    throw e;
  }
}

export async function submitRun(deps: SubmitDeps, req: SubmitRequest, email: string): Promise<SubmitResult> {
  let runId: string;
  let sourceId: string;
  try {
    runId = checkId(req.run_id, 'run_id');
    sourceId = checkId(req.source_scenario_id, 'source_scenario_id');
  } catch (e) {
    throw new SubmitError(400, (e as Error).message);
  }
  if (req.mode !== 'new' && req.mode !== 'resolve') throw new SubmitError(400, "mode must be 'new' or 'resolve'");
  const source = req.source ?? 'app';
  if (!SCENARIO_SOURCES.includes(source)) throw new SubmitError(400, "source must be 'app' or 'agent'", 'source');

  const prior = await existingRun(deps, runId);
  if (prior) return prior;

  const [sourceRow] = await deps.sql.run(S.findScenario(deps.t), { scenario_id: sourceId });
  if (!sourceRow) throw new SubmitError(404, `Scenario ${sourceId} not found`);

  let scenarioId = sourceId;
  if (req.mode === 'new') {
    const named = checkName(req.name);
    if (!named.ok) throw new SubmitError(400, named.error, 'name');
    let overridesJson: string;
    try {
      overridesJson = stableJson(parseOverrides(req.overrides));
    } catch (e) {
      const path = (e as { path?: string }).path;
      throw new SubmitError(400, (e as Error).message, path);
    }
    scenarioId = scenarioIdFor(named.name, runId);
    await cloneScenario(deps, sourceId, scenarioId, named.name, num(sourceRow.season), overridesJson, email, source);
  } else if (req.overrides !== undefined) {
    throw new SubmitError(400, 'Re-solve runs the scenario unchanged; save edited settings as a new scenario');
  }

  let inserted: boolean;
  try {
    const [merge] = await deps.sql.run(S.openRun(deps.t), { run_id: runId, scenario_id: scenarioId, triggered_by: email });
    inserted = num(merge?.num_inserted_rows) === 1;
  } catch (e) {
    if (!isWriteConflict(e)) throw e;
    inserted = false;
  }
  if (!inserted) {
    const winner = await existingRun(deps, runId);
    if (winner) return winner;
    throw new SubmitError(409, `Run ${runId} could not be opened; try again`);
  }

  let jobRunId: number;
  try {
    jobRunId = await deps.jobs.runNow(deps.solveJobId, { scenario_id: scenarioId, run_id: runId, triggered_by: email });
  } catch (e) {
    const error = `Could not start the solve job: ${(e as Error).message}`;
    await deps.sql.run(S.markFailed(deps.t), { run_id: runId, error });
    return { run_id: runId, scenario_id: scenarioId, job_run_id: null, status: 'failed', deduped: false, error };
  }
  await deps.sql.run(S.setJobRunId(deps.t), { run_id: runId, job_run_id: String(jobRunId) });
  return { run_id: runId, scenario_id: scenarioId, job_run_id: String(jobRunId), status: 'queued', deduped: false };
}

/** One in-flight submit per run_id in this process; the second caller gets the first one's result. */
export function createSubmitter() {
  const inflight = new Map<string, Promise<SubmitResult>>();
  return async (deps: SubmitDeps, req: SubmitRequest, email: string): Promise<SubmitResult> => {
    const key = String(req.run_id);
    const pending = inflight.get(key);
    if (pending) return { ...(await pending), deduped: true };
    const p = submitRun(deps, req, email).finally(() => inflight.delete(key));
    inflight.set(key, p);
    return p;
  };
}
