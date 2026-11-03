import { describe, expect, test } from 'vitest';
import { toPlanRow } from '../results/resultsModel';
import { buildLineage, canStartLive, diffPlans, flatten, histogram, pickStress, toScenarioView, toStressView } from './scenariosModel';

const sc = (id: string, parent: string | null, created: number) =>
  toScenarioView({ scenario_id: id, name: id, parent_scenario_id: parent, created_ms: String(created) });

describe('lineage', () => {
  test('children sit under parents, oldest first', () => {
    const tree = buildLineage([sc('rev-b', 'baseline-2027', 30), sc('baseline-2027', null, 10), sc('rev-a', 'baseline-2027', 20), sc('rev-a2', 'rev-a', 40)]);
    expect(flatten(tree).map((n) => `${'  '.repeat(n.depth)}${n.scenario.scenario_id}`)).toEqual(
      ['baseline-2027', '  rev-a', '    rev-a2', '  rev-b']);
  });
  test('a missing parent or a cycle never drops a scenario', () => {
    const tree = buildLineage([sc('orphan', 'gone', 1), sc('x', 'y', 2), sc('y', 'x', 3)]);
    expect(flatten(tree).map((n) => n.scenario.scenario_id).sort()).toEqual(['orphan', 'x', 'y']);
  });
});

const plan = (rows: Array<[string, string | null, string | null, number]>) =>
  rows.map(([field_id, hybrid_id, w, margin]) => toPlanRow({ field_id, grower_id: 'G', region: 'IA', soil_class: 'A', acres: 100,
    lat: 41, lon: -93, hybrid_id, planting_window: w, exp_yield: 1, exp_margin: margin, is_fixed: false }));

test('diffPlans lists changed hybrid/window and the margin change', () => {
  const base = plan([['F-1', 'H-104', 'W3', 100], ['F-2', 'H-101', 'W2', 50], ['F-3', null, null, 0]]);
  const rev = plan([['F-1', 'H-112', 'W1', 130], ['F-2', 'H-101', 'W2', 50], ['F-3', 'H-115', 'W2', 40]]);
  expect(diffPlans(base, rev)).toEqual([
    { field_id: 'F-1', region: 'IA', from: 'H-104 W3', to: 'H-112 W1', margin_delta: 30 },
    { field_id: 'F-3', region: 'IA', from: 'unplanted', to: 'H-115 W2', margin_delta: 40 },
  ]);
});

describe('stress', () => {
  const s = (id: string, scenario: string, n: number, created: number) =>
    toStressView({ stress_id: id, scenario_id: scenario, n: String(n), n_solved: String(n), p10_gross_margin: '1.7689E7',
      fragile_fields_json: '["F-141","F-143"]', fragile_hybrids_json: null, created_ms: String(created) });
  test('the stored N=500 run represents a scenario even after a newer live N=50', () => {
    const all = [s('live', 'baseline-2027', 50, 300), s('stress-baseline-2027-n500', 'baseline-2027', 500, 100), s('old', 'baseline-2027', 20, 50)];
    expect(pickStress(all, 'baseline-2027')?.stress_id).toBe('stress-baseline-2027-n500');
    expect(pickStress(all, 'nope')).toBeNull();
    expect(all[0].fragile_fields).toEqual(['F-141', 'F-143']);
    expect(all[0].fragile_hybrids).toEqual([]);
    expect(all[0].p10).toBe(17689000);
  });
  test('histogram bins share edges and count every value once', () => {
    const bins = histogram({ base: [1, 2, 3, 10], rev: [5, 10] }, 3);
    expect(bins.map((b) => [b.from, b.to])).toEqual([[1, 4], [4, 7], [7, 10]]);
    expect(bins.map((b) => [b.base, b.rev])).toEqual([[3, 0], [0, 1], [1, 1]]);
    expect(histogram({}, 3)).toEqual([]);
  });
});

test('toStressView accepts fragile lists AppKit already decoded from JSON', () => {
  const v = toStressView({ stress_id: 's', scenario_id: 'b', n: '500', fragile_fields_json: ['F-141'], fragile_hybrids_json: ['H-112'] });
  expect(v.fragile_fields).toEqual(['F-141']);
  expect(v.fragile_hybrids).toEqual(['H-112']);
});

describe('canStartLive', () => {
  test('the live-run button is disabled while a start request is in flight', () => {
    expect(canStartLive(false, null)).toBe(true);
    expect(canStartLive(true, null)).toBe(false);
  });
  test('and while a started run is pending or running; enabled again once it ends', () => {
    expect(canStartLive(false, { status: null })).toBe(false);
    expect(canStartLive(false, { status: { state: 'running' } })).toBe(false);
    expect(canStartLive(false, { status: { state: 'succeeded' } })).toBe(true);
    expect(canStartLive(false, { status: { state: 'failed' } })).toBe(true);
  });
});
