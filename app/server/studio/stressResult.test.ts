import { describe, expect, test } from 'vitest';
import { tablesFor } from './config';
import { FakeJobs, FakeSql } from './fakes';
import { stressResult } from './stressResult';

const t = tablesFor({ catalog: 'cat', schema: 'crop_plan' });
const ID = 'st-20261102101500-q7w2ze-n50-revision-1-2027';
const SUMMARY = {
  stress_id: ID, scenario_id: 'revision-1-2027', n: '50', n_solved: '50', n_invalid: '0', n_infeasible: '0', n_failed: '0',
  p10_gross_margin: '17810000.5', p50_gross_margin: '18590000', p90_gross_margin: '18780000',
  fragile_fields_json: '["F-115","F-131"]', fragile_hybrids_json: '["H-112"]', job_run_id: '555',
};

function world(summary: Record<string, unknown>[] = []) {
  const sql = new FakeSql().on(/FROM `cat`.`crop_plan`.`stress_test_summary`/, summary);
  const jobs = new FakeJobs();
  return { sql, jobs, deps: { sql, jobs, t, stressJobId: 100 } };
}
const param = (stressId: string) => [{ name: 'stress_id', value: stressId }, { name: 'n', value: '50' }];

describe('stressResult', () => {
  test('a finished stress test returns its stored summary with numbers parsed', async () => {
    const { deps, jobs } = world([SUMMARY]);
    expect(await stressResult(deps, ID)).toEqual({
      stress_id: ID, state: 'done', scenario_id: 'revision-1-2027', job_run_id: '555', message: null,
      summary: { n: 50, n_solved: 50, n_invalid: 0, n_infeasible: 0, n_failed: 0, p10_gross_margin: 17810000.5,
        p50_gross_margin: 18590000, p90_gross_margin: 18780000, fragile_fields: ['F-115', 'F-131'], fragile_hybrids: ['H-112'] },
    });
    expect(jobs.listed).toEqual([]);
  });

  test('without a summary yet, the job run that carries this stress_id says running', async () => {
    const { deps, jobs } = world();
    jobs.recent = [
      { run_id: 1, job_parameters: param('st-other'), state: { life_cycle_state: 'TERMINATED', result_state: 'SUCCESS' } },
      { run_id: 2, job_parameters: param(ID), state: { life_cycle_state: 'RUNNING' } },
    ];
    expect(await stressResult(deps, ID)).toMatchObject({ state: 'running', job_run_id: '2', summary: null });
    expect(jobs.listed).toEqual([{ jobId: 100, limit: 25 }]);
  });

  test('a job run that succeeded but whose summary is not visible yet still counts as running', async () => {
    const { deps, jobs } = world();
    jobs.recent = [{ run_id: 2, job_parameters: param(ID), state: { life_cycle_state: 'TERMINATED', result_state: 'SUCCESS' } }];
    expect((await stressResult(deps, ID)).state).toBe('running');
  });

  test('a failed job run reports failed with its message', async () => {
    const { deps, jobs } = world();
    jobs.recent = [{ run_id: 2, job_parameters: param(ID),
      state: { life_cycle_state: 'INTERNAL_ERROR', result_state: 'FAILED', state_message: 'GPU quota exceeded' } }];
    expect(await stressResult(deps, ID)).toMatchObject({ state: 'failed', message: 'GPU quota exceeded' });
  });

  test('an unknown stress_id is a 404; a malformed one is a 400', async () => {
    await expect(stressResult(world().deps, 'st-nope')).rejects.toMatchObject({ status: 404 });
    await expect(stressResult(world().deps, "x' OR 1=1")).rejects.toMatchObject({ status: 400 });
  });
});
