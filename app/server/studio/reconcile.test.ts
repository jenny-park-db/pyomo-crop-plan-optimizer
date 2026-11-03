import { describe, expect, test } from 'vitest';
import { tablesFor } from './config';
import { FakeJobs, FakeSql } from './fakes';
import type { JobRun } from './jobs';
import { createThrottle, decide, NEVER_STARTED_MS, SUCCESS_GRACE_MS, syncActiveRuns, type ActiveRun } from './reconcile';

const NOW = 1_800_000_000_000;
const row = (over: Partial<ActiveRun> = {}): ActiveRun => ({ run_id: 'r1', job_run_id: '501', status: 'queued', submitted_ms: NOW - 60_000, ...over });
const failedRun: JobRun = {
  job_id: 59,
  state: { life_cycle_state: 'INTERNAL_ERROR', result_state: 'FAILED', state_message: 'Task solve failed with message: Workload failed, see run output for details.' },
  tasks: [{ run_id: 601, task_key: 'solve', state: { result_state: 'FAILED' } }],
};

describe('decide', () => {
  test('a job that died before opening its row fails the run with the task error', () => {
    expect(decide(row(), failedRun, "ModuleNotFoundError: No module named 'cropplan'", NOW)).toEqual({
      run_id: 'r1', error: "Job run failed: ModuleNotFoundError: No module named 'cropplan'" });
  });
  test('without a task error it falls back to the run state message', () => {
    expect(decide(row(), failedRun, null, NOW)?.error).toBe(
      'Job run failed: Task solve failed with message: Workload failed, see run output for details.');
  });
  test('a cancelled run says so', () => {
    const run: JobRun = { state: { life_cycle_state: 'TERMINATED', result_state: 'CANCELED', state_message: 'Run cancelled.' } };
    expect(decide(row(), run, null, NOW)?.error).toBe('Job run canceled: Run cancelled.');
  });
  test('a running job is left alone', () => {
    expect(decide(row({ status: 'solving' }), { state: { life_cycle_state: 'RUNNING' } }, null, NOW)).toBeNull();
  });
  test('a successful job gets time to commit its final status, then is flagged', () => {
    const ok = (end: number): JobRun => ({ state: { life_cycle_state: 'TERMINATED', result_state: 'SUCCESS' }, end_time: end });
    expect(decide(row({ status: 'checking' }), ok(NOW - 10_000), null, NOW)).toBeNull();
    expect(decide(row({ status: 'checking' }), ok(NOW - SUCCESS_GRACE_MS - 1), null, NOW)?.error).toMatch(/never recorded a final status/);
  });
  test('a queued row whose job never started fails only after the grace period', () => {
    expect(decide(row({ job_run_id: null, submitted_ms: NOW - 30_000 }), undefined, null, NOW)).toBeNull();
    expect(decide(row({ job_run_id: null, submitted_ms: NOW - NEVER_STARTED_MS - 1 }), undefined, null, NOW)?.error).toMatch(/never started/);
  });
  test('a job run the Jobs API has never heard of fails the row', () => {
    expect(decide(row(), null, null, NOW)?.error).toBe('Job run 501 was not found in the Jobs API');
  });
  test('an unreachable Jobs API decides nothing', () => {
    expect(decide(row(), undefined, null, NOW)).toBeNull();
  });
});

describe('syncActiveRuns', () => {
  test('reads active rows, asks the Jobs API, and fails only the dead ones', async () => {
    const sql = new FakeSql().on(/SELECT run_id, job_run_id, status, unix_millis/, [
      { run_id: 'dead', job_run_id: '501', status: 'queued', submitted_ms: String(NOW - 60_000) },
      { run_id: 'alive', job_run_id: '502', status: 'solving', submitted_ms: String(NOW - 60_000) },
    ]);
    const jobs = new FakeJobs();
    jobs.runs.set(501, failedRun);
    jobs.runs.set(502, { state: { life_cycle_state: 'RUNNING' } });
    jobs.taskErrors.set(601, 'RuntimeError: died before opening the runs row');
    const out = await syncActiveRuns({ sql, jobs, t: tablesFor({ catalog: 'cat', schema: 's' }) }, NOW);
    expect(out).toEqual({ active: 1, failed: [{ run_id: 'dead', error: 'Job run failed: RuntimeError: died before opening the runs row' }] });
    expect(sql.matching(/SET status = 'failed'/).map((c) => c.params.run_id)).toEqual(['dead']);
  });
});

test('createThrottle shares one sync across a burst but uses each new caller after the window', async () => {
  let clock = 0;
  const throttle = createThrottle<string>(3000, () => clock);
  const a = throttle(async () => 'first');
  const b = throttle(async () => 'second');
  expect(await a).toBe('first');
  expect(await b).toBe('first');
  clock = 3500;
  expect(await throttle(async () => 'third')).toBe('third');
});
