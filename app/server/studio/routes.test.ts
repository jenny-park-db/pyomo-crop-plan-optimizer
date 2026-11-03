import { describe, expect, test } from 'vitest';
import { loadConfig } from './config';
import type { AgentFetch } from './agentProxy';
import { FakeJobs, FakeSql } from './fakes';
import { createHandlers, userEmail, type Req, type Res } from './routes';

const env = {
  CROP_PLAN_CATALOG: 'cat', CROP_PLAN_SCHEMA: 'crop_plan', CROP_PLAN_SOLVE_JOB_ID: '59', CROP_PLAN_STRESS_JOB_ID: '100',
  DATABRICKS_HOST: 'my-workspace.cloud.databricks.com', MLFLOW_EXPERIMENT_ID: '123',
};

function req(headers: Record<string, string>, body?: unknown, params: Record<string, string> = {}): Req {
  return { header: (n) => headers[n.toLowerCase()], body, params };
}
function res() {
  const out: { code: number; body: unknown } = { code: 0, body: null };
  const r: Res = { status(c) { out.code = c; return r; }, json(b) { out.body = b; return r; } };
  return { r, out };
}

describe('config', () => {
  test('reads the bundle-provided environment and normalizes the host', () => {
    expect(loadConfig(env)).toEqual({ catalog: 'cat', schema: 'crop_plan', solveJobId: 59, stressJobId: 100,
      host: 'https://my-workspace.cloud.databricks.com', experimentId: '123', mapMode: 'tiles', agentUrl: null });
    expect(loadConfig({ ...env, CROP_PLAN_MAP_MODE: 'svg' }).mapMode).toBe('svg');
    expect(() => loadConfig({ ...env, CROP_PLAN_SOLVE_JOB_ID: '' })).toThrow(/CROP_PLAN_SOLVE_JOB_ID/);
    expect(() => loadConfig({ ...env, CROP_PLAN_SCHEMA: 'x`; DROP' })).toThrow(/CROP_PLAN_SCHEMA/);
  });
});

describe('identity', () => {
  test('comes from x-forwarded-email, never the body', async () => {
    const sql = new FakeSql()
      .on(/FROM `cat`.`crop_plan`.`scenarios` WHERE/, [{ scenario_id: 'baseline-2027', season: '2027' }])
      .on(/MERGE INTO/, [{ num_inserted_rows: '1' }]);
    const jobs = new FakeJobs();
    const h = createHandlers(loadConfig(env), () => ({ sql, jobs }), env);
    const { r, out } = res();
    await h.submitRun(req({ 'x-forwarded-email': 'planner@example.com' }, {
      mode: 'resolve', source_scenario_id: 'baseline-2027', run_id: 'app-1', triggered_by: 'ceo@example.com' }), r);
    expect(out.code).toBe(200);
    expect(jobs.started[0].params.triggered_by).toBe('planner@example.com');
  });
  test('a request without the header is refused (401)', async () => {
    const h = createHandlers(loadConfig(env), () => ({ sql: new FakeSql(), jobs: new FakeJobs() }), env);
    const { r, out } = res();
    await h.submitRun(req({}, {}), r);
    expect(out.code).toBe(401);
  });
  test('local development may name a user explicitly', () => {
    expect(userEmail(req({}), { NODE_ENV: 'development', CROP_PLAN_DEV_USER: 'dev@example.com' })).toBe('dev@example.com');
    expect(() => userEmail(req({}), { CROP_PLAN_DEV_USER: 'dev@example.com' })).toThrow();
  });
});

test('errors map to status codes with the offending path', async () => {
  const sql = new FakeSql().on(/FROM `cat`.`crop_plan`.`scenarios` WHERE/, [{ scenario_id: 'baseline-2027', season: '2027' }]);
  const h = createHandlers(loadConfig(env), () => ({ sql, jobs: new FakeJobs() }), env);
  const { r, out } = res();
  await h.submitRun(req({ 'x-forwarded-email': 'p@example.com' }, {
    mode: 'new', source_scenario_id: 'baseline-2027', run_id: 'app-1', name: 'X', overrides: { bogus: 1 } }), r);
  expect(out).toEqual({ code: 400, body: { error: 'unknown override keys: bogus', path: 'unknown override keys' } });
});
describe('agent URL', () => {
  test('is optional, https only, and loses its trailing slash', () => {
    expect(loadConfig({ ...env, CROP_PLAN_AGENT_URL: 'https://agent-bricks-crop-plan-agent-1.aws.databricksapps.com/' }).agentUrl)
      .toBe('https://agent-bricks-crop-plan-agent-1.aws.databricksapps.com');
    expect(loadConfig({ ...env, CROP_PLAN_AGENT_URL: '' }).agentUrl).toBeNull();
    expect(() => loadConfig({ ...env, CROP_PLAN_AGENT_URL: 'http://evil.example.com' })).toThrow(/CROP_PLAN_AGENT_URL/);
  });

  test('"none" (the bundle default before the agent exists) means not deployed', () => {
    // The Apps API rejects an env var whose value is empty, so a fresh install's first deploy carries "none".
    expect(loadConfig({ ...env, CROP_PLAN_AGENT_URL: 'none' }).agentUrl).toBeNull();
    expect(loadConfig({ ...env, CROP_PLAN_AGENT_URL: ' none ' }).agentUrl).toBeNull();
  });
});

describe('agent-facing routes', () => {
  const USER = { 'x-forwarded-email': 'p@example.com', 'x-forwarded-access-token': 'user-token' };
  const RUN_ROW = { run_id: 'agent-1', scenario_id: 's1', status: 'solving', job_run_id: '77', has_summary: 'false' };

  test('a run report syncs active runs with the Jobs API before answering', async () => {
    let status = 'solving';
    const sql = new FakeSql()
      .on(/FROM `cat`.`crop_plan`.`runs` r LEFT JOIN/, () => [{ ...RUN_ROW, status }])
      .on(/WHERE status IN \('queued'/, [{ run_id: 'agent-1', job_run_id: '77', status: 'solving', submitted_ms: '1' }])
      .on(/SET status = 'failed'/, () => { status = 'failed'; return []; });
    const jobs = new FakeJobs();
    jobs.runs.set(77, { state: { life_cycle_state: 'INTERNAL_ERROR', result_state: 'FAILED', state_message: 'boom' } });
    const h = createHandlers(loadConfig(env), () => ({ sql, jobs }), env);
    const { r, out } = res();
    await h.runReport(req(USER, undefined, { runId: 'agent-1' }), r);
    expect(out.code).toBe(200);
    expect(out.body).toMatchObject({ run_id: 'agent-1', status: 'failed', final: true });
  });

  test('a failed reconciliation still answers with the first read instead of a 5xx', async () => {
    const sql = new FakeSql()
      .on(/FROM `cat`.`crop_plan`.`runs` r LEFT JOIN/, () => [RUN_ROW])
      .on(/WHERE status IN \('queued'/, new Error('DELTA_CONCURRENT_APPEND'));
    const h = createHandlers(loadConfig(env), () => ({ sql, jobs: new FakeJobs() }), env);
    const { r, out } = res();
    await h.runReport(req(USER, undefined, { runId: 'agent-1' }), r);
    expect(out.code).toBe(200);
    expect(out.body).toMatchObject({ run_id: 'agent-1', status: 'solving' });
  });

  test('the report routes and the stress-test route need a signed-in user', async () => {
    const h = createHandlers(loadConfig(env), () => ({ sql: new FakeSql(), jobs: new FakeJobs() }), env);
    for (const [handler, params] of [[h.runReport, { runId: 'a' }], [h.scenarioReport, { scenarioId: 'b' }],
      [h.stressResult, { stressId: 'c' }]] as const) {
      const { r, out } = res();
      await handler(req({}, undefined, params), r);
      expect(out.code).toBe(401);
    }
  });

  test('agent turns forward the user token, never the service principal', async () => {
    const seen: string[] = [];
    const agentFetch: AgentFetch = async (_url, init) => {
      seen.push(String((init.headers as Record<string, string>).Authorization));
      return { ok: true, status: 202, text: async () => JSON.stringify({ id: 'x', status: 'queued' }) };
    };
    const cfgEnv = { ...env, CROP_PLAN_AGENT_URL: 'https://agent-bricks-crop-plan-agent-1.aws.databricksapps.com' };
    const h = createHandlers(loadConfig(cfgEnv), () => ({ sql: new FakeSql(), jobs: new FakeJobs() }), cfgEnv, agentFetch);
    const { r, out } = res();
    await h.agentStart(req(USER, { session_id: '6f1c1e0e-4b8e-4e0f-9a51-3d2f5f1d2a10', message: 'hi' }), r);
    expect([out.code, seen]).toEqual([200, ['Bearer user-token']]);
  });
});
