import { describe, expect, test } from 'vitest';
import { checkId, checkName, IdError, newRunId, scenarioIdFor, stressIdFor } from './ids';

const fixed = new Date(Date.UTC(2026, 9, 30, 17, 48, 5));
const rand = () => 0.5;

describe('ids', () => {
  test('checkId mirrors cropplan_jobs.tables.check_id', () => {
    for (const ok of ['baseline-2027', 'run-123', 'a.b_c']) expect(checkId(ok)).toBe(ok);
    for (const bad of ['', "x' OR '1'='1", 'a b', '-lead', '../up', 'x'.repeat(65), null, 7, 'abc\n']) {
      expect(() => checkId(bad, 'scenario_id')).toThrow(IdError);
    }
  });
  test('run ids are UTC-stamped, random-tailed, and valid', () => {
    const id = newRunId(fixed, rand);
    expect(id).toBe('app-20261030174805-ssssss');
    expect(checkId(id)).toBe(id);
  });
  test('scenario ids slug the name and keep the run tail, whatever the name', () => {
    const run = 'app-20261030174805-k3x9qa';
    expect(scenarioIdFor('Revision A', run)).toBe('revision-a-k3x9qa');
    expect(scenarioIdFor("  Grower's Plan: IA/W1 ½ capacity!! ", run)).toBe('grower-s-plan-ia-w1-1-2-capacity-k3x9qa');
    expect(scenarioIdFor('Ünïcödé façade', run)).toBe('unicode-facade-k3x9qa');
    expect(scenarioIdFor('🌽🌽', run)).toBe('scenario-k3x9qa');
    expect(scenarioIdFor('x'.repeat(200), run).length).toBeLessThanOrEqual(64);
    expect(scenarioIdFor("'; DROP TABLE runs; --", run)).toBe('drop-table-runs-k3x9qa');
  });
  test('stress ids stay within 64 characters', () => {
    const id = stressIdFor('a'.repeat(60), 50, fixed);
    expect(id.length).toBeLessThanOrEqual(64);
    expect(checkId(id)).toBe(id);
    expect(stressIdFor('baseline-2027', 50, fixed, () => 0)).toBe('st-20261030174805-aaaaaa-n50-baseline-2027');
  });
  test('two stress starts in the same second get different stress ids', () => {
    let i = 0;
    const counter = () => ((i++ % 36) / 36);
    expect(stressIdFor('baseline-2027', 50, fixed, counter)).not.toBe(stressIdFor('baseline-2027', 50, fixed, counter));
  });
  test('names are trimmed and bounded', () => {
    expect(checkName('  Revision   A ')).toEqual({ ok: true, name: 'Revision A' });
    expect(checkName('')).toEqual({ ok: false, error: 'Give the scenario a name.' });
    expect(checkName('   ')).toMatchObject({ ok: false });
    expect(checkName('x'.repeat(81))).toMatchObject({ ok: false });
    expect(checkName(42)).toMatchObject({ ok: false });
  });
});
