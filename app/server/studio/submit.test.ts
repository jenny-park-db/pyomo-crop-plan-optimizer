import { describe, expect, test } from 'vitest';
import contract from '../../shared/studio/parity/table_contract.json';
import { tablesFor } from './config';
import { FakeJobs, FakeSql } from './fakes';
import { INPUT_COLUMNS, INPUT_TABLES, type Row } from './sql';
import { createSubmitter, submitRun, SubmitError, type SubmitRequest } from './submit';

const t = tablesFor({ catalog: 'cat', schema: 'crop_plan' });
const RUN = 'app-20261030174805-k3x9qa';
const NEW: SubmitRequest = {
  mode: 'new', source_scenario_id: 'baseline-2027', run_id: RUN, name: 'Revision A',
  overrides: { supply_pct: { 'H-112': 1.1 }, diversity_cap: 0.45 },
};

function world() {
  const sql = new FakeSql()
    .on(/FROM `cat`.`crop_plan`.`scenarios` WHERE scenario_id/, (p) =>
      p.scenario_id === 'baseline-2027' ? [{ scenario_id: 'baseline-2027', name: '2027 Baseline', season: '2027' }] : [])
    .on(/MERGE INTO `cat`.`crop_plan`.`runs`/, [{ num_inserted_rows: '1' }]);
  const jobs = new FakeJobs();
  return { sql, jobs, deps: { sql, jobs, t, solveJobId: 59 } };
}

async function rejection(p: Promise<unknown>): Promise<SubmitError> {
  try {
    await p;
  } catch (e) {
    expect(e).toBeInstanceOf(SubmitError);
    return e as SubmitError;
  }
  throw new Error('expected a SubmitError');
}

describe('submitRun', () => {
  test('new scenario: copies every input table, writes the scenario, opens the run, starts the job as the SP', async () => {
    const { sql, jobs, deps } = world();
    const r = await submitRun(deps, NEW, 'planner@example.com');
    expect(r).toEqual({ run_id: RUN, scenario_id: 'revision-a-k3x9qa', job_run_id: '9001', status: 'queued', deduped: false });
    expect(sql.matching(/^INSERT INTO/).map((c) => c.params)).toEqual(
      INPUT_TABLES.map(() => ({ new_id: 'revision-a-k3x9qa', source_id: 'baseline-2027' })));
    const [scenario] = sql.matching(/MERGE INTO `cat`.`crop_plan`.`scenarios`/);
    expect(scenario.params).toMatchObject({ name: 'Revision A', parent_id: 'baseline-2027', season: 2027, created_by: 'planner@example.com' });
    expect(JSON.parse(String(scenario.params.overrides))).toMatchObject({ diversity_cap: 0.45, supply_pct: { 'H-112': 1.1 } });
    expect(jobs.started).toEqual([{ jobId: 59, params: { scenario_id: 'revision-a-k3x9qa', run_id: RUN, triggered_by: 'planner@example.com' } }]);
    expect(sql.matching(/SET job_run_id/)[0].params).toEqual({ run_id: RUN, job_run_id: '9001' });
  });

  test('the scenario records who asked for it: app by default, agent when the agent submits', async () => {
    const { sql, deps } = world();
    await submitRun(deps, NEW, 'p@example.com');
    await submitRun(deps, { ...NEW, run_id: 'agent-20261102101500-q7w2ze', source: 'agent' }, 'p@example.com');
    expect(sql.matching(/MERGE INTO `cat`.`crop_plan`.`scenarios`/).map((c) => c.params.source)).toEqual(['app', 'agent']);
  });

  test('an unknown source is a 400 before anything is written', async () => {
    const { sql, jobs, deps } = world();
    const e = await rejection(submitRun(deps, { ...NEW, source: 'stress' as never }, 'p@example.com'));
    expect([e.status, e.path]).toEqual([400, 'source']);
    expect(sql.matching(/^INSERT|^MERGE/)).toEqual([]);
    expect(jobs.started).toEqual([]);
  });

  test('re-solve runs the existing scenario without cloning', async () => {
    const { sql, jobs, deps } = world();
    const r = await submitRun(deps, { mode: 'resolve', source_scenario_id: 'baseline-2027', run_id: RUN }, 'p@example.com');
    expect(r.scenario_id).toBe('baseline-2027');
    expect(sql.matching(/^INSERT INTO|MERGE INTO `cat`.`crop_plan`.`scenarios`/)).toEqual([]);
    expect(jobs.started[0].params.scenario_id).toBe('baseline-2027');
  });

  test('a second submit with the same run_id returns the first run', async () => {
    const { sql, jobs, deps } = world();
    sql.on(/SELECT run_id, scenario_id, job_run_id, status FROM/, [], 1)
      .on(/SELECT run_id, scenario_id, job_run_id, status FROM/, [{ scenario_id: 'revision-a-k3x9qa', job_run_id: 9001, status: 'solving' }]);
    await submitRun(deps, NEW, 'p@example.com');
    const again = await submitRun(deps, NEW, 'p@example.com');
    expect(again).toEqual({ run_id: RUN, scenario_id: 'revision-a-k3x9qa', job_run_id: '9001', status: 'solving', deduped: true });
    expect(jobs.started).toHaveLength(1);
  });

  test('two submits racing in one process start one job', async () => {
    const { jobs, deps } = world();
    const submit = createSubmitter();
    const [a, b] = await Promise.all([submit(deps, NEW, 'p@example.com'), submit(deps, NEW, 'p@example.com')]);
    expect(jobs.started).toHaveLength(1);
    expect([a.deduped, b.deduped].sort()).toEqual([false, true]);
    expect(b.job_run_id).toBe(a.job_run_id);
  });

  test('a concurrent MERGE conflict is reported as a duplicate, not an error', async () => {
    const { sql, jobs, deps } = world();
    const conflict = new Error('[DELTA_CONCURRENT_APPEND.ROW_LEVEL_CHANGES] Transaction conflict detected.');
    const fresh = new FakeSql()
      .on(/SELECT run_id, scenario_id, job_run_id, status FROM/, [], 1)
      .on(/SELECT run_id, scenario_id, job_run_id, status FROM/, [{ scenario_id: 'baseline-2027', job_run_id: null, status: 'queued' }])
      .on(/FROM `cat`.`crop_plan`.`scenarios` WHERE/, [{ scenario_id: 'baseline-2027', season: '2027' }])
      .on(/MERGE INTO `cat`.`crop_plan`.`runs`/, conflict);
    const r = await submitRun({ ...deps, sql: fresh }, { mode: 'resolve', source_scenario_id: 'baseline-2027', run_id: RUN }, 'p@example.com');
    expect(r).toMatchObject({ deduped: true, status: 'queued' });
    expect(jobs.started).toEqual([]);
    expect(sql.calls).toEqual([]);
  });

  test('another writer opened the row first (0 rows inserted): no second job', async () => {
    const { jobs, deps } = world();
    const sql = new FakeSql()
      .on(/SELECT run_id, scenario_id, job_run_id, status FROM/, [], 1)
      .on(/SELECT run_id, scenario_id, job_run_id, status FROM/, [{ scenario_id: 'baseline-2027', job_run_id: '77', status: 'queued' }])
      .on(/FROM `cat`.`crop_plan`.`scenarios` WHERE/, [{ scenario_id: 'baseline-2027', season: '2027' }])
      .on(/MERGE INTO `cat`.`crop_plan`.`runs`/, [{ num_inserted_rows: '0' }]);
    const r = await submitRun({ ...deps, sql }, { mode: 'resolve', source_scenario_id: 'baseline-2027', run_id: RUN }, 'p@example.com');
    expect(r).toMatchObject({ deduped: true, job_run_id: '77' });
    expect(jobs.started).toEqual([]);
  });

  test('a failed run-now marks the queued row failed and says why', async () => {
    const { sql, jobs, deps } = world();
    jobs.failRunNow = new Error('PERMISSION_DENIED: CAN_MANAGE_RUN required');
    const r = await submitRun(deps, NEW, 'p@example.com');
    expect(r).toMatchObject({ status: 'failed', job_run_id: null, error: 'Could not start the solve job: PERMISSION_DENIED: CAN_MANAGE_RUN required' });
    const [failed] = sql.matching(/SET status = 'failed'/);
    expect(failed.params).toEqual({ run_id: RUN, error: r.error });
    expect(failed.statement).toMatch(/status IN \('queued', 'validating', 'solving', 'checking'\)/);
  });

  test('submit rejects bad overrides before writing anything', async () => {
    const { sql, jobs, deps } = world();
    const e = await rejection(submitRun(deps, { ...NEW, overrides: { diversity_cap: '0.4' } }, 'p@example.com'));
    expect([e.status, e.path]).toEqual([400, 'diversity_cap']);
    expect(sql.matching(/^INSERT|^MERGE|^UPDATE/)).toEqual([]);
    expect(jobs.started).toEqual([]);
  });

  test.each([
    [{ ...NEW, name: '   ' }, 400, 'name'],
    [{ ...NEW, run_id: "x' OR 1=1" }, 400, undefined],
    [{ ...NEW, source_scenario_id: 'nope' }, 404, undefined],
    [{ ...NEW, mode: 'other' as 'new' }, 400, undefined],
    [{ mode: 'resolve' as const, source_scenario_id: 'baseline-2027', run_id: RUN, overrides: {} }, 400, undefined],
  ])('rejects %#', async (req, status, path) => {
    const { deps } = world();
    const e = await rejection(submitRun(deps, req, 'p@example.com'));
    expect([e.status, e.path]).toEqual([status, path]);
  });

  test('a failed copy removes only the rows this request inserted', async () => {
    const { sql, jobs, deps } = world();
    sql.on(/^INSERT INTO `cat`.`crop_plan`.`yield_forecast`/, new Error('warehouse stopped'));
    await expect(submitRun(deps, NEW, 'p@example.com')).rejects.toThrow('warehouse stopped');
    const done = INPUT_TABLES.slice(0, INPUT_TABLES.indexOf('yield_forecast'));
    expect(sql.matching(/^DELETE FROM/).map((c) => c.statement.split('`')[5])).toEqual(done);
    expect(sql.matching(/^DELETE FROM/).every((c) => c.params.scenario_id === 'revision-a-k3x9qa')).toBe(true);
    expect(jobs.started).toEqual([]);
  });

  test('a new-scenario id that collides with an existing scenario is a 409 and touches nothing', async () => {
    const { jobs, deps } = world();
    // "Revision" + a run_id ending in 1-2027 slugs to the seeded revision-1-2027.
    const seeded = new FakeSql().on(/FROM `cat`.`crop_plan`.`scenarios` WHERE scenario_id/, (p) =>
      ['baseline-2027', 'revision-1-2027'].includes(String(p.scenario_id))
        ? [{ scenario_id: p.scenario_id, name: 'seeded', season: '2027' }] : []);
    const req = { ...NEW, name: 'Revision', run_id: 'app-20261030174805-1-2027' };
    const e = await rejection(submitRun({ ...deps, sql: seeded }, req, 'p@example.com'));
    expect(e.status).toBe(409);
    expect(e.message).toMatch(/revision-1-2027 already exists/);
    expect(seeded.matching(/^INSERT INTO|^DELETE FROM|^MERGE INTO/)).toEqual([]);
    expect(jobs.started).toEqual([]);
  });

  test('a retry with the same run_id after the clone landed but opening the run failed reuses its own clone', async () => {
    const { jobs, deps } = world();
    // The first attempt wrote revision-a-k3x9qa (same parent, same creator) and then failed before opening the run.
    const sql = new FakeSql()
      .on(/FROM `cat`.`crop_plan`.`scenarios` WHERE scenario_id/, (p) => ({
        'baseline-2027': [{ scenario_id: 'baseline-2027', name: '2027 Baseline', season: '2027' }],
        'revision-a-k3x9qa': [{ scenario_id: 'revision-a-k3x9qa', name: 'Revision A', season: '2027',
                                parent_scenario_id: 'baseline-2027', created_by: 'p@example.com' }],
      } as Record<string, Row[]>)[String(p.scenario_id)] ?? [])
      .on(/MERGE INTO `cat`.`crop_plan`.`runs`/, [{ num_inserted_rows: '1' }]);
    const r = await submitRun({ ...deps, sql }, NEW, 'p@example.com');
    expect(r).toMatchObject({ scenario_id: 'revision-a-k3x9qa', status: 'queued', deduped: false });
    expect(sql.matching(/^INSERT INTO|^DELETE FROM|MERGE INTO `cat`.`crop_plan`.`scenarios`/)).toEqual([]);
    expect(jobs.started).toHaveLength(1);
  });

  test('a colliding scenario with the same id but another creator or parent is still a 409', async () => {
    const { deps } = world();
    for (const other of [{ created_by: 'someone@example.com', parent_scenario_id: 'baseline-2027' },
                         { created_by: 'p@example.com', parent_scenario_id: 'revision-1-2027' }]) {
      const sql = new FakeSql().on(/FROM `cat`.`crop_plan`.`scenarios` WHERE scenario_id/, (p) =>
        p.scenario_id === 'baseline-2027' ? [{ scenario_id: 'baseline-2027', name: 'b', season: '2027' }]
          : [{ scenario_id: p.scenario_id, name: 'Revision A', season: '2027', ...other }]);
      expect((await rejection(submitRun({ ...deps, sql }, NEW, 'p@example.com'))).status).toBe(409);
    }
  });

  test('the clone copies exactly the columns cropplan_jobs.tables.INPUTS declares', () => {
    expect(INPUT_COLUMNS).toEqual(contract.inputs);
  });
});
