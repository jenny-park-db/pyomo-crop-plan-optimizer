import { describe, expect, test } from 'vitest';
import fixture from '../../../../shared/studio/parity/validation_cases.json';
import { parseOverrides } from '../../../../shared/studio/overrides';
import { DEFAULT_OVERRIDES, type ScenarioInputs } from '../../../../shared/studio/types';
import { validateScenario } from '../../../../shared/studio/validate';
import {
  canRun, formFromOverrides, formToOverrides, inputsFromRow, sameOverrides, storedOverrides, submitReducer,
} from './formModel';

const HYBRIDS = ['H-112', 'H-115'];
const REGIONS = ['IA', 'NE'];

describe('form <-> overrides', () => {
  test('round-trips Revision 1 settings', () => {
    const o = parseOverrides({ supply_pct: { 'H-112': 1.1 }, diversity_cap: 0.45, capacity_pct: { IA: { W1: 0.5 } } });
    const form = formFromOverrides(o, HYBRIDS, REGIONS);
    expect(form.supply).toEqual({ 'H-112': '110', 'H-115': '' });
    expect(form.capacity.IA.W1).toBe('50');
    expect(form.diversity_cap_pct).toBe('45');
    const back = formToOverrides(form);
    expect(back.ok && sameOverrides(back.overrides, o)).toBe(true);
  });
  test('a non-number names the field and blocks Run', () => {
    const form = formFromOverrides(DEFAULT_OVERRIDES, HYBRIDS, REGIONS);
    form.supply['H-112'] = '1o0';
    expect(formToOverrides(form)).toEqual({ ok: false, path: 'Seed supply H-112', error: 'Seed supply H-112 must be a number' });
  });
  test('out-of-range values come back with the parser path', () => {
    const form = formFromOverrides(DEFAULT_OVERRIDES, HYBRIDS, REGIONS);
    form.diversity_cap_pct = '140';
    expect(formToOverrides(form)).toMatchObject({ ok: false, path: 'diversity_cap' });
  });
  test('stored overrides that no longer parse fall back to defaults', () => {
    expect(storedOverrides('{"diversity_cap": 9}')).toEqual(DEFAULT_OVERRIDES);
    expect(storedOverrides(null)).toEqual(DEFAULT_OVERRIDES);
  });
});

test('inputsFromRow reads the JSON arrays and restores null windows (to_json omits them)', () => {
  const inputs = (fixture.inputs as Record<string, ScenarioInputs>).commitments;
  const row = {
    season: '2027',
    fields_json: JSON.stringify(inputs.fields), hybrids_json: JSON.stringify(inputs.hybrids),
    seed_supply_json: JSON.stringify(inputs.seed_supply), yield_forecast_json: JSON.stringify(inputs.yield_forecast),
    planting_capacity_json: JSON.stringify(inputs.planting_capacity),
    fixed_requests_json: '[{"field_id":"F-002","hybrid_id":"H-112"}]',
  };
  const parsed = inputsFromRow(row);
  expect(parsed.season).toBe(2027);
  expect(parsed.fixed_requests).toEqual([{ field_id: 'F-002', hybrid_id: 'H-112', window: null }]);
  expect(validateScenario(parsed, DEFAULT_OVERRIDES).filter((i) => i.severity === 'error')).toEqual([]);
  expect(inputsFromRow({ season: null }).fields).toEqual([]);
});

describe('canRun', () => {
  const ok = { ok: true as const, overrides: DEFAULT_OVERRIDES };
  const base = { parsed: ok, issues: [], name: 'Revision A', dirty: true, submitting: false };
  test('new scenario needs a name and no errors; warnings are fine', () => {
    expect(canRun('new', base)).toEqual({ enabled: true, reason: null });
    expect(canRun('new', { ...base, name: ' ' })).toEqual({ enabled: false, reason: 'Give the scenario a name.' });
    const warning = { severity: 'warning' as const, rule: 'capacity_below_fixed', entity: 'IA/W1', detail: '' };
    expect(canRun('new', { ...base, issues: [warning] }).enabled).toBe(true);
    expect(canRun('new', { ...base, issues: [{ ...warning, severity: 'error' }] }).reason).toBe('Fix 1 validation error first');
  });
  test('malformed JSON blocks both buttons with its message', () => {
    const bad = { ok: false as const, path: 'json', error: 'Overrides JSON is malformed: Unexpected token' };
    expect(canRun('new', { ...base, parsed: bad }).reason).toBe(bad.error);
    expect(canRun('resolve', { ...base, parsed: bad }).enabled).toBe(false);
  });
  test('re-solve is only for unchanged settings and needs no name', () => {
    expect(canRun('resolve', { ...base, name: '', dirty: false })).toEqual({ enabled: true, reason: null });
    expect(canRun('resolve', { ...base, dirty: true }).enabled).toBe(false);
  });
  test('nothing runs while inputs load or a submit is in flight', () => {
    expect(canRun('new', { ...base, issues: null }).enabled).toBe(false);
    expect(canRun('new', { ...base, submitting: true }).enabled).toBe(false);
  });
});

describe('submitReducer', () => {
  test('the form keeps one run_id until a submit succeeds', () => {
    let n = 0;
    const make = () => `app-${++n}`;
    let s = { runId: 'app-0', submitting: false };
    s = submitReducer(s, { type: 'start' }, make);
    expect(submitReducer(s, { type: 'start' }, make)).toBe(s); // a second click while submitting is ignored
    s = submitReducer(s, { type: 'failed' }, make);
    expect(s).toEqual({ runId: 'app-0', submitting: false }); // a retry reuses app-0, so the server dedupes it
    s = submitReducer(submitReducer(s, { type: 'start' }, make), { type: 'succeeded' }, make);
    expect(s).toEqual({ runId: 'app-1', submitting: false });
  });
});

test('inputsFromRow and storedOverrides accept columns AppKit already decoded from JSON (as the deployed app sends them)', () => {
  const inputs = (fixture.inputs as Record<string, ScenarioInputs>).commitments;
  const parsed = inputsFromRow({
    season: '2027', fields_json: inputs.fields, hybrids_json: inputs.hybrids, seed_supply_json: inputs.seed_supply,
    yield_forecast_json: inputs.yield_forecast, planting_capacity_json: inputs.planting_capacity,
    fixed_requests_json: [{ field_id: 'F-002', hybrid_id: 'H-112' }],
  });
  expect(parsed.fields).toHaveLength(inputs.fields.length);
  expect(parsed.fixed_requests).toEqual([{ field_id: 'F-002', hybrid_id: 'H-112', window: null }]);
  expect(storedOverrides({ diversity_cap: 0.45, supply_pct: { 'H-112': 1.1 } }).diversity_cap).toBe(0.45);
});
