/**
 * TypeScript port of cropplan.validate.validate: cheap pre-solve checks for the Inputs screen.
 * Errors block Run; warnings don't. The job re-runs the Python original in its `validating` stage, so this
 * is a preview that must agree with it: parity/validation_cases.json (generated from Python) is the contract.
 */
import { pyFixed0, pyRepr } from './format';
import { WINDOWS, type Issue, type Overrides, type ScenarioInputs } from './types';

const err = (rule: string, entity: string, detail: string): Issue => ({ severity: 'error', rule, entity, detail });
const warn = (rule: string, entity: string, detail: string): Issue => ({ severity: 'warning', rule, entity, detail });
const isWindow = (w: string): boolean => (WINDOWS as readonly string[]).includes(w);

function supplyMultiplier(o: Overrides, h: string): number {
  return o.supply_pct[h] ?? 1.0;
}
function capacityMultiplier(o: Overrides, r: string, w: string): number {
  return o.capacity_pct[r]?.[w] ?? 1.0;
}

export function eligiblePairs(inputs: ScenarioInputs): Array<[string, string]> {
  const pairs: Array<[string, string]> = [];
  for (const f of inputs.fields) {
    for (const h of inputs.hybrids) {
      if (h.relative_maturity >= f.rm_min && h.relative_maturity <= f.rm_max) pairs.push([f.field_id, h.hybrid_id]);
    }
  }
  return pairs;
}

function overrideNames(inputs: ScenarioInputs, o: Overrides): Issue[] {
  const issues: Issue[] = [];
  const hybrids = new Set(inputs.hybrids.map((h) => h.hybrid_id));
  const regions = new Set(inputs.fields.map((f) => f.region));
  for (const h of Object.keys(o.supply_pct)) {
    if (!hybrids.has(h)) issues.push(err('unknown_hybrid', h, `supply_pct names unknown hybrid ${pyRepr(h)}`));
  }
  for (const [r, windows] of Object.entries(o.capacity_pct)) {
    if (!regions.has(r)) issues.push(err('unknown_region', r, `capacity_pct names unknown region ${pyRepr(r)}`));
    for (const w of Object.keys(windows)) {
      if (!isWindow(w)) issues.push(err('unknown_window', `${r}/${w}`, `capacity_pct names unknown window ${pyRepr(w)}`));
    }
  }
  return issues;
}

function seedSupply(inputs: ScenarioInputs): Issue[] {
  const issues: Issue[] = [];
  const hybrids = new Set(inputs.hybrids.map((h) => h.hybrid_id));
  const otherSeasons = [...new Set(inputs.seed_supply.filter((s) => s.season !== inputs.season).map((s) => s.season))];
  if (otherSeasons.length) {
    const seasons = otherSeasons.sort((a, b) => a - b).join(', ');
    issues.push(err('supply_season_mismatch', seasons,
      `seed_supply has rows for season(s) ${seasons}; scenario season is ${inputs.season}`));
  }
  const counts = new Map<string, number>();
  for (const s of inputs.seed_supply) counts.set(s.hybrid_id, (counts.get(s.hybrid_id) ?? 0) + 1);
  for (const [h, n] of counts) {
    if (n > 1) issues.push(err('duplicate_supply', h, `seed_supply has ${n} rows for ${h}; expected 1`));
  }
  for (const h of [...counts.keys()].filter((h) => !hybrids.has(h)).sort()) {
    issues.push(err('unknown_supply_hybrid', h, `seed_supply names unknown hybrid ${pyRepr(h)}`));
  }
  for (const h of [...hybrids].filter((h) => !counts.has(h)).sort()) {
    issues.push(warn('missing_supply', h, `no seed_supply row for ${h}; treated as 0 units`));
  }
  return issues;
}

function forecastCoverage(inputs: ScenarioInputs): Issue[] {
  const have = new Set(inputs.yield_forecast.map((y) => `${y.region}/${y.soil_class}/${y.hybrid_id}/${y.window}`));
  const fields = new Map(inputs.fields.map((f) => [f.field_id, f]));
  const missing = new Set<string>();
  for (const [f, h] of eligiblePairs(inputs)) {
    const field = fields.get(f)!;
    for (const w of WINDOWS) {
      const key = `${field.region}/${field.soil_class}/${h}/${w}`;
      if (!have.has(key)) missing.add(key);
    }
  }
  return [...missing].sort().map((k) => err('missing_forecast', k, `no yield forecast for ${k}`));
}

function eligibility(inputs: ScenarioInputs): Issue[] {
  const eligible = new Set(eligiblePairs(inputs).map(([f]) => f));
  return inputs.fields
    .filter((f) => !eligible.has(f.field_id))
    .map((f) => warn('no_eligible_hybrid', f.field_id, "no hybrid matches this field's maturity range; it will be unplanted"));
}

function sumBy<T>(rows: T[], key: (r: T) => string, value: (r: T) => number): Map<string, number> {
  const out = new Map<string, number>();
  for (const r of rows) out.set(key(r), (out.get(key(r)) ?? 0) + value(r));
  return out;
}

function fixedRequests(inputs: ScenarioInputs, o: Overrides): Issue[] {
  const req = inputs.fixed_requests;
  if (!o.fixed_requests_enabled || req.length === 0) return [];
  const issues: Issue[] = [];
  const fields = new Map(inputs.fields.map((f) => [f.field_id, f]));
  const hybrids = new Map(inputs.hybrids.map((h) => [h.hybrid_id, h]));
  const pairs = new Set(eligiblePairs(inputs).map(([f, h]) => `${f}|${h}`));

  const known = req.filter((r) => fields.has(r.field_id) && hybrids.has(r.hybrid_id));
  for (const r of req.filter((r) => !(fields.has(r.field_id) && hybrids.has(r.hybrid_id)))) {
    issues.push(err('unknown_fixed_request', r.field_id,
      `fixed request references unknown field or hybrid (${r.field_id}, ${r.hybrid_id})`));
  }
  for (const [f, n] of sumBy(known, (r) => r.field_id, () => 1)) {
    if (n > 1) issues.push(err('duplicate_fixed_request', f, `${n} fixed requests for one field`));
  }
  for (const r of known) {
    if (!pairs.has(`${r.field_id}|${r.hybrid_id}`)) {
      issues.push(err('fixed_request_ineligible', r.field_id, `${r.hybrid_id} maturity is outside ${r.field_id}'s allowed range`));
    }
    if (typeof r.window === 'string' && !isWindow(r.window)) {
      issues.push(err('unknown_window', r.field_id, `unknown window ${pyRepr(r.window)}`));
    } else if (r.window !== null && typeof r.window !== 'string') {
      issues.push(err('unknown_window', r.field_id,
        `window must be one of ${WINDOWS.join(', ')} or empty, got ${pyRepr(r.window)}`));
    }
  }

  const supply = new Map(inputs.seed_supply.map((s) => [s.hybrid_id, s.units_available]));
  const units = sumBy(known, (r) => r.hybrid_id, (r) => fields.get(r.field_id)!.acres * hybrids.get(r.hybrid_id)!.units_per_acre);
  for (const [h, u] of units) {
    const limit = (supply.get(h) ?? 0) * supplyMultiplier(o, h);
    if (u > limit + 1e-6) {
      issues.push(err('fixed_exceeds_supply', h, `fixed requests need ${pyFixed0(u)} units of ${h}; ${pyFixed0(limit)} available`));
    }
  }

  const growerAcres = sumBy(inputs.fields, (f) => f.grower_id, (f) => f.acres);
  const byGrowerHybrid = sumBy(known, (r) => `${fields.get(r.field_id)!.grower_id}/${r.hybrid_id}`, (r) => fields.get(r.field_id)!.acres);
  for (const [gh, acres] of byGrowerHybrid) {
    const [g, h] = gh.split('/');
    const limit = o.diversity_cap * (growerAcres.get(g) ?? 0);
    if (acres > limit + 1e-6) {
      issues.push(err('fixed_exceeds_diversity', gh,
        `fixed ${h} acres for ${g} (${pyFixed0(acres)}) exceed the diversity cap (${pyFixed0(limit)})`));
    }
  }

  const capacity = new Map(inputs.planting_capacity.map((c) => [`${c.region}/${c.window}`, c.acres_capacity]));
  const windowed = known.filter((r) => typeof r.window === 'string' && isWindow(r.window));
  for (const [rw, acres] of sumBy(windowed, (r) => `${fields.get(r.field_id)!.region}/${r.window}`, (r) => fields.get(r.field_id)!.acres)) {
    const [r, w] = rw.split('/');
    const limit = (capacity.get(rw) ?? 0) * capacityMultiplier(o, r, w);
    if (acres > limit + 1e-6) {
      issues.push(warn('capacity_below_fixed', rw,
        `fixed acres in ${rw} (${pyFixed0(acres)}) exceed planting capacity (${pyFixed0(limit)})`));
    }
  }
  return issues;
}

export function validateScenario(inputs: ScenarioInputs, overrides: Overrides): Issue[] {
  return [
    ...overrideNames(inputs, overrides),
    ...seedSupply(inputs),
    ...forecastCoverage(inputs),
    ...eligibility(inputs),
    ...fixedRequests(inputs, overrides),
  ];
}

export function errorsOf(issues: Issue[]): Issue[] {
  return issues.filter((i) => i.severity === 'error');
}
