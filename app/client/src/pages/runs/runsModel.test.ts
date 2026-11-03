import { describe, expect, test } from 'vitest';
import { anyActive, elapsedMs, sortRuns, statusTone, terminationLabel, toRunView } from './runsModel';

const cfg = { host: 'https://ws.example.com', solveJobId: 59, experimentId: '42' };
const raw = {
  run_id: 'run-1', scenario_id: 'baseline-2027', scenario_name: '2027 Baseline', source: 'seed', job_run_id: '123456789012345',
  mlflow_run_id: '92735d', triggered_by: 'planner@example.com', status: 'done', solver: 'highs', solver_version: '1.15.1',
  model_version: 'cropplan@0.2.0', submitted_ms: '1793377192496', started_ms: '1793377192496', ended_ms: '1793377262824',
  error: null, infeasibility_reason: null, diagnosis: null, mip_gap: '1.636185341958261E-4', termination: 'optimal',
  objective: '1.8709018E7', runtime_s: '40.1',
};

describe('runsModel', () => {
  test('parses string numbers and builds job-run and MLflow links', () => {
    const v = toRunView(raw, cfg);
    expect(v.objective).toBe(18709018);
    expect(v.started_ms).toBe(1793377192496);
    expect(v.solver).toBe('highs 1.15.1');
    expect(v.job_run_url).toBe('https://ws.example.com/jobs/59/runs/123456789012345');
    expect(v.mlflow_url).toBe('https://ws.example.com/ml/experiments/42/runs/92735d');
  });
  test('no MLflow link without an experiment ID; reason prefers the infeasibility reason', () => {
    const v = toRunView({ ...raw, status: 'infeasible', infeasibility_reason: 'Infeasible: Planting capacity IA/W1 short by 290 acres',
      error: 'x', diagnosis: 'explained' }, { ...cfg, experimentId: null });
    expect(v.mlflow_url).toBeNull();
    expect(v.reason).toBe('Infeasible: Planting capacity IA/W1 short by 290 acres');
  });
  test('sorts newest first numerically even though times arrive as strings', () => {
    const rows = [
      toRunView({ ...raw, run_id: 'a', started_ms: '999999999999' }, cfg),
      toRunView({ ...raw, run_id: 'b', started_ms: '1000000000000' }, cfg),
      toRunView({ ...raw, run_id: 'c', started_ms: null, submitted_ms: null }, cfg),
    ];
    expect(sortRuns(rows).map((r) => r.run_id)).toEqual(['b', 'a', 'c']);
  });
  test('queued rows fall back to submitted time; active rows count up to now', () => {
    const q = toRunView({ ...raw, status: 'queued', started_ms: null, ended_ms: null, submitted_ms: '1000' }, cfg);
    expect(anyActive([q])).toBe(true);
    expect(elapsedMs(q, 61_000)).toBe(60_000);
    expect(elapsedMs(toRunView(raw, cfg), 0)).toBe(70_328);
  });
  test('tones and termination labels', () => {
    expect(['queued', 'solving', 'done', 'infeasible', 'invalid', 'failed'].map(statusTone))
      .toEqual(['active', 'active', 'good', 'warn', 'warn', 'bad']);
    expect(terminationLabel({ termination: 'optimal', mip_gap: 0.0001 })).toBe('optimal');
    expect(terminationLabel({ termination: 'maxTimeLimit', mip_gap: 0.008 })).toBe('maxTimeLimit · gap 0.80%');
    expect(terminationLabel({ termination: null, mip_gap: null })).toBe('–');
  });
});
