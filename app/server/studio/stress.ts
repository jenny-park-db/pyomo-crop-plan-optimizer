/** Live stress-test runs from the Scenarios screen (spec §6.4 "optional live run"). */
import { checkId, stressIdFor } from '../../shared/studio/ids';
import type { Tables } from './config';
import { isTerminal, type JobsClient } from './jobs';
import { statements as S, type SqlRunner } from './sql';
import { SubmitError } from './submit';

export const STRESS_DEFAULT_N = 50;
export const STRESS_MAX_N = 100; // N≤50 takes a few minutes; keep the demo's live run short

export interface StressDeps {
  jobs: JobsClient;
  stressJobId: number;
}

/** Starting also reads the scenario as the signed-in user (OBO) before the SP launches anything. */
export interface StartStressDeps extends StressDeps {
  sql: SqlRunner;
  t: Tables;
}

type StressBody = { scenario_id?: unknown; n?: unknown };
type Started = { stress_id: string; job_run_id: string; n: number };

function parseStart(body: StressBody): { scenarioId: string; n: number } {
  let scenarioId: string;
  try {
    scenarioId = checkId(body.scenario_id, 'scenario_id');
  } catch (e) {
    throw new SubmitError(400, (e as Error).message);
  }
  const n = body.n === undefined ? STRESS_DEFAULT_N : Number(body.n);
  if (!Number.isInteger(n) || n < 1 || n > STRESS_MAX_N) {
    throw new SubmitError(400, `n must be a whole number from 1 to ${STRESS_MAX_N}`, 'n');
  }
  return { scenarioId, n };
}

/** 404 unless the user can read the scenario: a made-up ID or a user without table access starts no GPU job. */
async function requireScenario(deps: StartStressDeps, scenarioId: string): Promise<void> {
  const [row] = await deps.sql.run(S.findScenario(deps.t), { scenario_id: scenarioId });
  if (!row) throw new SubmitError(404, `Scenario ${scenarioId} not found`);
}

async function launch(deps: StartStressDeps, scenarioId: string, n: number, email: string, now: Date,
                      random: () => number): Promise<Started> {
  const stressId = stressIdFor(scenarioId, n, now, random);
  const jobRunId = await deps.jobs.runNow(deps.stressJobId, {
    scenario_id: scenarioId, n: String(n), seed: '2027', stress_id: stressId, triggered_by: email,
  });
  return { stress_id: stressId, job_run_id: String(jobRunId), n };
}

export async function startStress(deps: StartStressDeps, body: StressBody, email: string, now: Date = new Date(),
                                  random: () => number = Math.random): Promise<Started> {
  const { scenarioId, n } = parseStart(body);
  await requireScenario(deps, scenarioId);
  return launch(deps, scenarioId, n, email, now, random);
}

/**
 * One live stress run per scenario at a time in this process (the app runs one instance): a double click or a
 * second tab gets a 409 while the first start is in flight or its job run is still active.
 */
export function createStressStarter() {
  const active = new Map<string, { pending: true } | { jobRunId: number }>();
  return async (deps: StartStressDeps, body: StressBody, email: string, now: Date = new Date(),
                random: () => number = Math.random): Promise<Started> => {
    const { scenarioId, n } = parseStart(body);
    await requireScenario(deps, scenarioId);
    const busy = () => new SubmitError(409, `A live stress test for ${scenarioId} is already running`);
    const prior = active.get(scenarioId);
    if (prior && 'pending' in prior) throw busy();
    active.set(scenarioId, { pending: true });
    try {
      if (prior) {
        let run: Awaited<ReturnType<typeof deps.jobs.getRun>>;
        try {
          run = await deps.jobs.getRun(prior.jobRunId);
        } catch {
          // Can't tell whether the earlier GPU run is still going: keep remembering it and refuse for now.
          active.set(scenarioId, prior);
          throw new SubmitError(503, `Couldn't check the running stress test for ${scenarioId}; try again shortly`);
        }
        if (run && !isTerminal(run)) {
          active.set(scenarioId, prior);
          throw busy();
        }
      }
      const started = await launch(deps, scenarioId, n, email, now, random);
      active.set(scenarioId, { jobRunId: Number(started.job_run_id) });
      return started;
    } catch (e) {
      const current = active.get(scenarioId);
      if (current && 'pending' in current) active.delete(scenarioId);
      throw e;
    }
  };
}

export type StressState = 'running' | 'succeeded' | 'failed';

export async function stressStatus(deps: StressDeps, jobRunId: string):
  Promise<{ state: StressState; message: string | null; run_page_url: string | null }> {
  const id = Number(jobRunId);
  if (!Number.isSafeInteger(id) || id <= 0) throw new SubmitError(400, 'job run ID must be a number');
  const run = await deps.jobs.getRun(id);
  if (!run || run.job_id !== deps.stressJobId) throw new SubmitError(404, `No stress-test run ${jobRunId}`);
  const url = run.run_page_url ?? null;
  if (!isTerminal(run)) return { state: 'running', message: run.state?.life_cycle_state ?? null, run_page_url: url };
  if (run.state?.result_state === 'SUCCESS') return { state: 'succeeded', message: null, run_page_url: url };
  return { state: 'failed', message: run.state?.state_message ?? run.state?.result_state ?? null, run_page_url: url };
}
