/**
 * GET /api/studio/stress-tests/:stressId: a stress test by its ID (the agent's get_stress_test). The stored
 * summary is the answer once it exists; until then the stress job run carrying that stress_id says whether it
 * is still going or failed. The summary is read as the signed-in user; the Jobs API as the app SP.
 */
import { jsonValue, num, numOrNull, strOrNull } from '../../shared/studio/format';
import { checkId } from '../../shared/studio/ids';
import type { Tables } from './config';
import { isTerminal, type JobsClient, type ListedRun } from './jobs';
import { statements as S, type SqlRunner } from './sql';
import { SubmitError } from './submit';

/** How far back to look for the job run; live stress runs are rare (one per scenario at a time). */
export const STRESS_LOOKBACK_RUNS = 25;

export interface StressSummary {
  n: number;
  n_solved: number;
  n_invalid: number;
  n_infeasible: number;
  n_failed: number;
  p10_gross_margin: number | null;
  p50_gross_margin: number | null;
  p90_gross_margin: number | null;
  fragile_fields: string[];
  fragile_hybrids: string[];
}

export interface StressResult {
  stress_id: string;
  state: 'done' | 'running' | 'failed';
  scenario_id: string | null;
  job_run_id: string | null;
  message: string | null;
  summary: StressSummary | null;
}

export interface StressResultDeps {
  sql: SqlRunner;
  jobs: JobsClient;
  t: Tables;
  stressJobId: number;
}

const strings = (value: unknown): string[] => {
  const v = jsonValue(value);
  return Array.isArray(v) ? v.map(String) : [];
};

const paramOf = (run: ListedRun, name: string): string | null =>
  run.job_parameters?.find((p) => p.name === name)?.value ?? null;

export async function stressResult(deps: StressResultDeps, rawStressId: unknown): Promise<StressResult> {
  let stressId: string;
  try {
    stressId = checkId(rawStressId, 'stress_id');
  } catch (e) {
    throw new SubmitError(400, (e as Error).message);
  }
  const [row] = await deps.sql.run(S.stressSummary(deps.t), { stress_id: stressId });
  if (row) {
    return {
      stress_id: stressId, state: 'done', scenario_id: String(row.scenario_id), job_run_id: strOrNull(row.job_run_id),
      message: null,
      summary: {
        n: num(row.n), n_solved: num(row.n_solved), n_invalid: num(row.n_invalid), n_infeasible: num(row.n_infeasible),
        n_failed: num(row.n_failed), p10_gross_margin: numOrNull(row.p10_gross_margin),
        p50_gross_margin: numOrNull(row.p50_gross_margin), p90_gross_margin: numOrNull(row.p90_gross_margin),
        fragile_fields: strings(row.fragile_fields_json), fragile_hybrids: strings(row.fragile_hybrids_json),
      },
    };
  }
  const runs = await deps.jobs.listRuns(deps.stressJobId, STRESS_LOOKBACK_RUNS);
  const run = runs.find((r) => paramOf(r, 'stress_id') === stressId);
  if (!run) throw new SubmitError(404, `No stress test ${stressId}`);
  const base = { stress_id: stressId, scenario_id: paramOf(run, 'scenario_id'), job_run_id: strOrNull(run.run_id), summary: null };
  // SUCCESS without a visible summary: the load task's write hasn't landed yet, so keep waiting.
  if (!isTerminal(run) || run.state?.result_state === 'SUCCESS') {
    return { ...base, state: 'running', message: run.state?.life_cycle_state ?? null };
  }
  return { ...base, state: 'failed', message: run.state?.state_message ?? run.state?.result_state ?? 'failed' };
}
