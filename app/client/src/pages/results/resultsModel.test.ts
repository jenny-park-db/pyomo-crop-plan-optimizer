import { describe, expect, test } from 'vitest';
import { toRunView, type RunView } from '../runs/runsModel';
import { boundsOf, filterPlan, groupPlan, pickResultRun, project, radiusFor, resultsShouldPoll, toPlanRow, toSummary } from './resultsModel';

const cfg = { host: 'https://ws', solveJobId: 1, experimentId: null };
const run = (id: string, status: string, extra: Record<string, unknown> = {}): RunView =>
  toRunView({ run_id: id, scenario_id: 's', status, started_ms: '1', ...extra }, cfg);

describe('resultsShouldPoll', () => {
  test('polls while the picked run is queued or solving', () => {
    expect(resultsShouldPoll(pickResultRun([run('r1', 'queued')], null))).toBe(true);
    expect(resultsShouldPoll(pickResultRun([run('r2', 'solving'), run('r1', 'failed')], 'r2'))).toBe(true);
  });
  test('stops once the run finishes, however it finished', () => {
    for (const status of ['done', 'failed', 'infeasible', 'invalid']) {
      expect(resultsShouldPoll(pickResultRun([run('r1', status)], null))).toBe(false);
    }
    expect(resultsShouldPoll(pickResultRun([], null))).toBe(false);
  });
});

describe('pickResultRun', () => {
  test('shows the latest done run and notes a newer active one', () => {
    const pick = pickResultRun([run('r3', 'solving'), run('r2', 'done'), run('r1', 'done')], null);
    expect(pick).toMatchObject({ kind: 'show', run: { run_id: 'r2' }, note: 'A newer run (r3) is solving.' });
  });
  test('a requested done run wins over the latest', () => {
    expect(pickResultRun([run('r2', 'done'), run('r1', 'done')], 'r1')).toMatchObject({ kind: 'show', run: { run_id: 'r1' } });
  });
  test('an infeasible scenario explains why instead of drawing an empty map', () => {
    const reason = 'Infeasible: Planting capacity IA/W1 short by 290 acres';
    expect(pickResultRun([run('r1', 'infeasible', { infeasibility_reason: reason })], null)).toMatchObject({
      kind: 'empty', title: 'No feasible plan', description: reason, run: { run_id: 'r1' } });
  });
  test('a requested run that is still running or failed says so', () => {
    expect(pickResultRun([run('r2', 'queued'), run('r1', 'done')], 'r2')).toMatchObject({ kind: 'empty', title: 'Run r2 is queued' });
    expect(pickResultRun([run('r1', 'failed', { error: 'RuntimeError: boom' })], 'r1'))
      .toMatchObject({ kind: 'empty', title: 'The run failed', description: 'RuntimeError: boom' });
    expect(pickResultRun([run('r1', 'invalid')], null)).toMatchObject({ title: 'The inputs failed validation', description: 'No reason was recorded.' });
  });
  test('no runs at all', () => {
    expect(pickResultRun([], null)).toMatchObject({ kind: 'empty', title: 'No runs for this scenario yet' });
  });
});

const rows = [
  { field_id: 'F-1', grower_id: 'G-1', region: 'IA', soil_class: 'A', acres: '100', lat: '41', lon: '-93', hybrid_id: 'H-112', planting_window: 'W1', exp_yield: '200', exp_margin: '1000', is_fixed: 'true' },
  { field_id: 'F-2', grower_id: 'G-1', region: 'IA', soil_class: 'B', acres: '300', lat: '42', lon: '-94', hybrid_id: 'H-104', planting_window: 'W2', exp_yield: '180', exp_margin: '2000', is_fixed: 'false' },
  { field_id: 'F-3', grower_id: 'G-2', region: 'NE', soil_class: 'B', acres: '200', lat: '41', lon: '-99', hybrid_id: null, planting_window: null, exp_yield: '0', exp_margin: '0', is_fixed: 'false' },
].map(toPlanRow);

describe('plan rows', () => {
  test('parse strings, nulls, and booleans', () => {
    expect(rows[0]).toMatchObject({ acres: 100, is_fixed: true, window: 'W1' });
    expect(rows[2]).toMatchObject({ hybrid_id: null, window: null });
  });
  test('group by region with acre-weighted yield over planted acres only', () => {
    expect(groupPlan(rows, 'region')).toEqual([
      { key: 'IA', fields: 2, acres: 400, planted_acres: 400, unplanted_fields: 0, gross_margin: 3000, yield_bu_ac: 185 },
      { key: 'NE', fields: 1, acres: 200, planted_acres: 0, unplanted_fields: 1, gross_margin: 0, yield_bu_ac: null },
    ]);
  });
  test('unplanted sorts last when grouping by hybrid, and is filterable', () => {
    expect(groupPlan(rows, 'hybrid').map((g) => g.key)).toEqual(['H-104', 'H-112', 'Unplanted']);
    expect(filterPlan(rows, { region: null, hybrid: 'Unplanted', window: null }).map((r) => r.field_id)).toEqual(['F-3']);
    expect(filterPlan(rows, { region: 'IA', hybrid: null, window: 'W2' }).map((r) => r.field_id)).toEqual(['F-2']);
  });
});

test('summary parsing keeps missing KPIs null (infeasible runs have no run_summary row)', () => {
  expect(toSummary({ run_id: 'r', status: 'infeasible', gross_margin: null, hybrids_at_limit: '0' }))
    .toMatchObject({ gross_margin: null, hybrids_at_limit: 0 });
});

test('projection keeps north up and the points inside the box', () => {
  const b = boundsOf([{ lat: 40, lon: -100 }, { lat: 43, lon: -88 }], 0);
  const nw = project(43, -100, b, 600, 300);
  const se = project(40, -88, b, 600, 300);
  expect(nw.y).toBeLessThan(se.y);
  expect(nw.x).toBeLessThan(se.x);
  for (const p of [nw, se]) {
    expect(p.x).toBeGreaterThanOrEqual(0);
    expect(p.x).toBeLessThanOrEqual(600);
    expect(p.y).toBeGreaterThanOrEqual(0);
    expect(p.y).toBeLessThanOrEqual(300);
  }
  expect(radiusFor(200, 200)).toBe(11);
  expect(radiusFor(50, 200)).toBeCloseTo(5.5);
  expect(radiusFor(1, 200)).toBe(3);
});
