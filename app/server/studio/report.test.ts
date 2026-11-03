import { describe, expect, test } from 'vitest';
import { tablesFor } from './config';
import { FakeSql } from './fakes';
import { runReport, scenarioReport } from './report';
import { SubmitError } from './submit';

const t = tablesFor({ catalog: 'cat', schema: 'crop_plan' });

const DONE = {
  run_id: 'agent-1', scenario_id: 'ia-w1-half-q7w2ze', scenario_name: 'IA W1 half', source: 'agent',
  overrides: '{"capacity_pct":{"IA":{"W1":0.5}}}', status: 'done', job_run_id: '77', error: null,
  infeasibility_reason: null, diagnosis: null, termination: 'optimal', mip_gap: '0.0004',
  gross_margin: '18512345.5', net_margin: '18290000.25', unplanted_penalty_total: '222345.25',
  acres_planted_pct: '0.951', unplanted_fields: '9', unplanted_acres: '1180.5', violations_count: '0', has_summary: 'true',
};

function world(run: Record<string, unknown> | null = DONE) {
  return new FakeSql()
    .on(/FROM `cat`.`crop_plan`.`runs` r/, (p) => (run && p.run_id === run.run_id ? [run] : []))
    .on(/FROM `cat`.`crop_plan`.`seed_utilization`/, [{ hybrid_id: 'H-112' }, { hybrid_id: 'H-115' }])
    .on(/FROM `cat`.`crop_plan`.`violations`/, [
      { rule: 'capacity', entity: 'IA/W1', severity: 'binding', detail: 'short by 290 acres' }]);
}

describe('runReport', () => {
  test('a finished run carries the numbers the agent may cite, parsed from warehouse strings', async () => {
    const sql = world();
    expect(await runReport({ sql, t }, 'agent-1')).toEqual({
      run_id: 'agent-1', scenario_id: 'ia-w1-half-q7w2ze', scenario_name: 'IA W1 half', source: 'agent',
      overrides: { capacity_pct: { IA: { W1: 0.5 } } }, status: 'done', final: true, job_run_id: '77',
      error: null, infeasibility_reason: null, diagnosis: null, termination: 'optimal', mip_gap: 0.0004,
      kpis: { gross_margin: 18512345.5, net_margin: 18290000.25, unplanted_penalty_total: 222345.25,
        acres_planted_pct: 0.951, unplanted_fields: 9, unplanted_acres: 1180.5, violations_count: 0 },
      hybrids_at_supply_limit: ['H-112', 'H-115'],
      violations: [{ rule: 'capacity', entity: 'IA/W1', severity: 'binding', detail: 'short by 290 acres' }],
    });
    expect(sql.matching(/seed_utilization/)[0].params).toEqual({ run_id: 'agent-1' });
  });

  test('a run that is still solving has no KPIs and reads nothing else', async () => {
    const sql = world({ ...DONE, status: 'solving', has_summary: 'false', gross_margin: null, net_margin: null,
      unplanted_penalty_total: null, acres_planted_pct: null, unplanted_fields: null, violations_count: null });
    const r = await runReport({ sql, t }, 'agent-1');
    expect([r.status, r.final, r.kpis, r.violations]).toEqual(['solving', false, null, []]);
    expect(sql.matching(/FROM `cat`.`crop_plan`.`(seed_utilization|violations)`/)).toEqual([]);
  });

  test('an infeasible run reports its reason and binding constraint, without KPIs', async () => {
    const sql = world({ ...DONE, status: 'infeasible', has_summary: 'false', gross_margin: null,
      infeasibility_reason: 'Planting capacity IA/W1 short by 290 acres', diagnosis: 'explained' });
    const r = await runReport({ sql, t }, 'agent-1');
    expect([r.final, r.kpis, r.infeasibility_reason, r.violations[0].severity])
      .toEqual([true, null, 'Planting capacity IA/W1 short by 290 acres', 'binding']);
  });

  test('an unknown or unreadable run is a 404', async () => {
    await expect(runReport({ sql: world(), t }, 'nope')).rejects.toMatchObject({ status: 404 });
    await expect(runReport({ sql: world(), t }, 'bad id;')).rejects.toBeInstanceOf(SubmitError);
  });
});

describe('scenarioReport', () => {
  test('reports the latest finished run of a scenario, preferring a done run', async () => {
    const sql = world().on(/ORDER BY/, [{ run_id: 'agent-1' }]);
    const r = await scenarioReport({ sql, t }, 'ia-w1-half-q7w2ze');
    expect(r.run_id).toBe('agent-1');
    const [latest] = sql.matching(/ORDER BY/);
    expect(latest.params).toEqual({ scenario_id: 'ia-w1-half-q7w2ze' });
    expect(latest.statement).toMatch(/CASE WHEN status = 'done' THEN 0 ELSE 1 END/);
  });

  test('a scenario without a finished run is a 404', async () => {
    await expect(scenarioReport({ sql: world(), t }, 'baseline-2027')).rejects.toMatchObject({ status: 404 });
  });
});
