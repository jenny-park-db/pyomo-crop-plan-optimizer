import { describe, expect, test } from 'vitest';
import { tablesFor } from './config';
import { FakeJobs, FakeSql } from './fakes';
import { createStressStarter, startStress, STRESS_MAX_N, stressStatus } from './stress';
import { SubmitError } from './submit';

const at = new Date(Date.UTC(2026, 9, 30, 17, 48, 5));
const t = tablesFor({ catalog: 'cat', schema: 'crop_plan' });
const KNOWN = ['baseline-2027', 'revision-1-2027'];

function world() {
  const sql = new FakeSql().on(/FROM `cat`.`crop_plan`.`scenarios` WHERE scenario_id/, (p) =>
    KNOWN.includes(String(p.scenario_id)) ? [{ scenario_id: p.scenario_id, name: 'x', season: '2027' }] : []);
  const jobs = new FakeJobs();
  return { sql, jobs, deps: { sql, jobs, t, stressJobId: 100 } };
}

describe('live stress runs', () => {
  test('start passes the job parameters, with triggered_by from the caller', async () => {
    const { jobs, deps } = world();
    const r = await startStress(deps, { scenario_id: 'revision-1-2027' }, 'p@example.com', at, () => 0);
    expect(r).toEqual({ stress_id: 'st-20261030174805-aaaaaa-n50-revision-1-2027', job_run_id: '9001', n: 50 });
    expect(jobs.started[0]).toEqual({ jobId: 100, params: {
      scenario_id: 'revision-1-2027', n: '50', seed: '2027', stress_id: r.stress_id, triggered_by: 'p@example.com' } });
  });
  test.each([[0], [STRESS_MAX_N + 1], [12.5], ['many']])('n=%s is rejected', async (n) => {
    await expect(startStress(world().deps, { scenario_id: 'baseline-2027', n }, 'p@example.com'))
      .rejects.toBeInstanceOf(SubmitError);
  });
  test('a scenario the user cannot read (or that does not exist) is a 404 and starts no job', async () => {
    const { sql, jobs, deps } = world();
    await expect(startStress(deps, { scenario_id: 'made-up-2027' }, 'p@example.com')).rejects.toMatchObject({ status: 404 });
    expect(sql.matching(/FROM `cat`.`crop_plan`.`scenarios` WHERE scenario_id/)[0].params).toEqual({ scenario_id: 'made-up-2027' });
    expect(jobs.started).toEqual([]);
  });
  test('a double click starts one stress job; the second start gets a 409', async () => {
    const { jobs, deps } = world();
    const start = createStressStarter();
    const results = await Promise.allSettled([
      start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com'),
      start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com'),
    ]);
    expect(jobs.started).toHaveLength(1);
    expect(results.map((r) => r.status).sort()).toEqual(['fulfilled', 'rejected']);
    expect(results.find((r) => r.status === 'rejected')).toMatchObject({ reason: { status: 409 } });
  });
  test('a start while that scenario\'s stress run is still active gets a 409; after it ends a new one starts', async () => {
    const { jobs, deps } = world();
    const start = createStressStarter();
    const first = await start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com');
    jobs.runs.set(Number(first.job_run_id), { job_id: 100, state: { life_cycle_state: 'RUNNING' } });
    await expect(start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com')).rejects.toMatchObject({ status: 409 });
    await start(deps, { scenario_id: 'revision-1-2027' }, 'p@example.com'); // other scenarios are unaffected
    jobs.runs.set(Number(first.job_run_id), { job_id: 100, state: { life_cycle_state: 'TERMINATED', result_state: 'SUCCESS' } });
    await start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com');
    expect(jobs.started.map((s) => s.params.scenario_id)).toEqual(['baseline-2027', 'revision-1-2027', 'baseline-2027']);
  });
  test('a Jobs API error while checking the active run keeps the guard: 503 and no second GPU job', async () => {
    const { jobs, deps } = world();
    const start = createStressStarter();
    const first = await start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com');
    jobs.failGetRun = new Error('jobs API unavailable');
    await expect(start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com')).rejects.toMatchObject({ status: 503 });
    jobs.failGetRun = null;
    jobs.runs.set(Number(first.job_run_id), { job_id: 100, state: { life_cycle_state: 'RUNNING' } });
    await expect(start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com')).rejects.toMatchObject({ status: 409 });
    expect(jobs.started).toHaveLength(1);
  });
  test('a failed run-now frees the slot; the retry starts exactly one job', async () => {
    const { jobs, deps } = world();
    const start = createStressStarter();
    jobs.failRunNow = new Error('run-now failed');
    await expect(start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com')).rejects.toThrow('run-now failed');
    jobs.failRunNow = null;
    await start(deps, { scenario_id: 'baseline-2027' }, 'p@example.com');
    expect(jobs.started).toHaveLength(1);
  });
  test('status maps Jobs states and refuses runs of other jobs', async () => {
    const jobs = new FakeJobs();
    jobs.runs.set(1, { job_id: 100, state: { life_cycle_state: 'RUNNING' } });
    jobs.runs.set(2, { job_id: 100, state: { life_cycle_state: 'TERMINATED', result_state: 'SUCCESS' } });
    jobs.runs.set(3, { job_id: 100, state: { life_cycle_state: 'INTERNAL_ERROR', result_state: 'FAILED', state_message: 'boom' } });
    jobs.runs.set(4, { job_id: 59, state: { life_cycle_state: 'RUNNING' } });
    const deps = { jobs, stressJobId: 100 };  // status reads Jobs only
    expect((await stressStatus(deps, '1')).state).toBe('running');
    expect((await stressStatus(deps, '2')).state).toBe('succeeded');
    expect(await stressStatus(deps, '3')).toMatchObject({ state: 'failed', message: 'boom' });
    await expect(stressStatus(deps, '4')).rejects.toMatchObject({ status: 404 });
    await expect(stressStatus(deps, 'abc')).rejects.toMatchObject({ status: 400 });
  });
});
