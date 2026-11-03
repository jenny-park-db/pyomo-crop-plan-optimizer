/**
 * Keeps the runs table honest when a job can't (spec §3 "polling syncs state from the Jobs API"): a job
 * run that ended without its row reaching a final status, or a row whose job never started, becomes
 * `failed` with the reason. Rows are updated as the signed-in user, guarded on an active status.
 */
import { numOrNull, strOrNull } from '../../shared/studio/format';
import type { Tables } from './config';
import { failedTaskRunId, isTerminal, type JobRun, type JobsClient } from './jobs';
import { statements as S, type SqlRunner } from './sql';

/** A queued row with no job run after this long was abandoned between the MERGE and run-now. */
export const NEVER_STARTED_MS = 5 * 60_000;
/** A job that succeeded writes its final status before it ends; allow for Delta commit lag. */
export const SUCCESS_GRACE_MS = 2 * 60_000;

export interface ActiveRun {
  run_id: string;
  job_run_id: string | null;
  status: string;
  submitted_ms: number | null;
}

export interface Failure {
  run_id: string;
  error: string;
}

export function decide(row: ActiveRun, run: JobRun | null | undefined, taskError: string | null, nowMs: number): Failure | null {
  if (!row.job_run_id) {
    if (row.submitted_ms !== null && nowMs - row.submitted_ms > NEVER_STARTED_MS) {
      return { run_id: row.run_id, error: 'The solve job was never started for this run (the app stopped between saving the run and starting the job). Submit it again.' };
    }
    return null;
  }
  if (run === null) return { run_id: row.run_id, error: `Job run ${row.job_run_id} was not found in the Jobs API` };
  if (run === undefined || !isTerminal(run)) return null;
  const result = run.state?.result_state;
  if (result === 'SUCCESS') {
    if (run.end_time && nowMs - run.end_time > SUCCESS_GRACE_MS) {
      return { run_id: row.run_id, error: 'The job run succeeded but never recorded a final status for this run.' };
    }
    return null;
  }
  const outcome = (result ?? run.state?.life_cycle_state ?? 'ended').toLowerCase();
  const reason = taskError || run.state?.state_message || 'no error message';
  return { run_id: row.run_id, error: `Job run ${outcome}: ${reason}` };
}

export interface SyncDeps {
  sql: SqlRunner;
  jobs: JobsClient;
  t: Tables;
}

export interface SyncResult {
  active: number;
  failed: Failure[];
}

export async function syncActiveRuns(deps: SyncDeps, nowMs: number = Date.now()): Promise<SyncResult> {
  const rows = (await deps.sql.run(S.activeRuns(deps.t))).map((r): ActiveRun => ({
    run_id: String(r.run_id),
    job_run_id: strOrNull(r.job_run_id),
    status: String(r.status),
    submitted_ms: numOrNull(r.submitted_ms),
  }));
  const failed: Failure[] = [];
  for (const row of rows) {
    let run: JobRun | null | undefined;
    let taskError: string | null = null;
    if (row.job_run_id) {
      try {
        run = await deps.jobs.getRun(Number(row.job_run_id));
      } catch {
        run = undefined; // the Jobs API is unreachable right now: decide nothing, try on the next poll
      }
      const taskRunId = run && isTerminal(run) && run.state?.result_state !== 'SUCCESS' ? failedTaskRunId(run) : null;
      if (taskRunId) taskError = await deps.jobs.taskError(taskRunId).catch(() => null);
    }
    const failure = decide(row, run, taskError, nowMs);
    if (failure) {
      await deps.sql.run(S.markFailed(deps.t), { run_id: failure.run_id, error: failure.error });
      failed.push(failure);
    }
  }
  return { active: rows.length - failed.length, failed };
}

/**
 * Collapse bursts of polls from several open tabs: within `minMs` of a sync, callers share its result.
 * The work function is passed per call, so a sync always runs with the current caller's credentials.
 */
export function createThrottle<T>(minMs = 3000, now: () => number = Date.now) {
  let last = -Infinity;
  let pending: Promise<T> | null = null;
  return (work: () => Promise<T>): Promise<T> => {
    if (pending && now() - last < minMs) return pending;
    last = now();
    pending = work();
    return pending;
  };
}
