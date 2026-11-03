/**
 * TypeScript port of cropplan.overrides.parse_overrides. Same keys, ranges, and error *paths*; the
 * parity fixture (parity/overrides_cases.json, generated from Python) is the contract. Names (hybrids,
 * regions, windows) are checked against the scenario's inputs in validate.ts, as in cropplan.validate.
 */
import { DEFAULT_OVERRIDES, type Overrides } from './types';
import { pyRepr } from './format';

export const SOLVERS = ['highs', 'gurobi'] as const;
export const MAX_MULTIPLIER = 3.0;
const KNOWN = Object.keys(DEFAULT_OVERRIDES);

export class OverridesError extends Error {
  /** The offending key path, e.g. "supply_pct.H-112" or "unknown override keys". */
  readonly path: string;
  constructor(path: string, message: string) {
    super(message);
    this.path = path;
  }
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isNumber(v: unknown): v is number {
  return typeof v === 'number';
}

function multiplier(value: unknown, path: string): number {
  if (!isNumber(value)) throw new OverridesError(path, `${path} must be a number, got ${pyRepr(value)}`);
  if (!Number.isFinite(value)) throw new OverridesError(path, `${path} must be a finite number, got ${pyRepr(value)}`);
  if (value < 0 || value > MAX_MULTIPLIER) {
    throw new OverridesError(path, `${path} must be between 0 and ${MAX_MULTIPLIER.toFixed(1)}, got ${value}`);
  }
  return value;
}

function finite(value: unknown, path: string): number {
  if (!isNumber(value) || !Number.isFinite(value)) {
    throw new OverridesError(path, `${path} must be a finite number, got ${pyRepr(value)}`);
  }
  return value;
}

function whole(value: unknown, path: string): number {
  if (!isNumber(value) || !Number.isInteger(value)) {
    throw new OverridesError(path, `${path} must be a whole number, got ${pyRepr(value)}`);
  }
  return value;
}

function pick(payload: Record<string, unknown>, key: keyof Overrides): unknown {
  return key in payload ? payload[key] : DEFAULT_OVERRIDES[key];
}

/** Validate the shape and ranges of an overrides payload; throws OverridesError. */
export function parseOverrides(payload: unknown): Overrides {
  if (payload === null || payload === undefined) payload = {};
  if (!isPlainObject(payload)) throw new OverridesError('overrides', 'overrides must be a JSON object');
  const unknown = Object.keys(payload).filter((k) => !KNOWN.includes(k)).sort();
  if (unknown.length) {
    throw new OverridesError('unknown override keys', `unknown override keys: ${unknown.join(', ')}`);
  }

  const supply = pick(payload, 'supply_pct');
  if (!isPlainObject(supply)) {
    throw new OverridesError('supply_pct', 'supply_pct must be an object of hybrid_id -> multiplier');
  }
  const supply_pct: Record<string, number> = {};
  for (const [h, v] of Object.entries(supply)) supply_pct[h] = multiplier(v, `supply_pct.${h}`);

  const capacity = pick(payload, 'capacity_pct');
  if (!isPlainObject(capacity) || !Object.values(capacity).every(isPlainObject)) {
    throw new OverridesError('capacity_pct', 'capacity_pct must be an object of region -> {window -> multiplier}');
  }
  const capacity_pct: Record<string, Record<string, number>> = {};
  for (const [r, windows] of Object.entries(capacity as Record<string, Record<string, unknown>>)) {
    capacity_pct[r] = {};
    for (const [w, v] of Object.entries(windows)) capacity_pct[r][w] = multiplier(v, `capacity_pct.${r}.${w}`);
  }

  const diversity_cap = finite(pick(payload, 'diversity_cap'), 'diversity_cap');
  if (!(diversity_cap > 0 && diversity_cap <= 1)) {
    throw new OverridesError('diversity_cap', `diversity_cap must be in (0, 1], got ${diversity_cap}`);
  }
  const penalty = finite(pick(payload, 'unplanted_penalty_per_acre'), 'unplanted_penalty_per_acre');
  if (penalty < 0) throw new OverridesError('unplanted_penalty_per_acre', 'unplanted_penalty_per_acre must be >= 0');
  const price = finite(pick(payload, 'corn_price_per_bu'), 'corn_price_per_bu');
  if (price <= 0) throw new OverridesError('corn_price_per_bu', 'corn_price_per_bu must be > 0');
  const solver = pick(payload, 'solver');
  if (solver !== 'highs' && solver !== 'gurobi') {
    throw new OverridesError('solver', `solver must be one of ('highs', 'gurobi'), got ${pyRepr(solver)}`);
  }
  const time_limit_s = whole(pick(payload, 'time_limit_s'), 'time_limit_s');
  if (time_limit_s < 1 || time_limit_s > 3600) {
    throw new OverridesError('time_limit_s', 'time_limit_s must be between 1 and 3600');
  }
  const mip_rel_gap = finite(pick(payload, 'mip_rel_gap'), 'mip_rel_gap');
  if (mip_rel_gap < 0 || mip_rel_gap > 0.05) {
    throw new OverridesError('mip_rel_gap', 'mip_rel_gap must be between 0 and 0.05');
  }
  const threadsRaw = pick(payload, 'threads');
  const threads = threadsRaw === null ? null : whole(threadsRaw, 'threads');
  if (threads !== null && threads < 1) throw new OverridesError('threads', `threads must be at least 1, got ${threads}`);
  const seedRaw = pick(payload, 'random_seed');
  const random_seed = seedRaw === null ? null : whole(seedRaw, 'random_seed');
  const enabled = pick(payload, 'fixed_requests_enabled');
  if (typeof enabled !== 'boolean') {
    throw new OverridesError('fixed_requests_enabled', `fixed_requests_enabled must be true or false, got ${pyRepr(enabled)}`);
  }

  return {
    supply_pct, capacity_pct, diversity_cap, unplanted_penalty_per_acre: penalty, corn_price_per_bu: price,
    fixed_requests_enabled: enabled, solver, time_limit_s, mip_rel_gap, threads, random_seed,
  };
}

export type ParsedText = { ok: true; overrides: Overrides } | { ok: false; path: string; error: string };

/** The "Edit as JSON" box: malformed JSON and bad values are both rejected here, before Run is enabled. */
export function parseOverridesText(text: string): ParsedText {
  let payload: unknown;
  try {
    payload = text.trim() === '' ? {} : JSON.parse(text);
  } catch (e) {
    return { ok: false, path: 'json', error: `Overrides JSON is malformed: ${(e as Error).message}` };
  }
  try {
    return { ok: true, overrides: parseOverrides(payload) };
  } catch (e) {
    if (e instanceof OverridesError) return { ok: false, path: e.path, error: e.message };
    throw e;
  }
}

/** JSON with sorted keys at every level, like the job's json.dumps(..., sort_keys=True); the job re-parses it. */
export function stableJson(value: unknown): string {
  const sort = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sort);
    if (isPlainObject(v)) {
      return Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort(v[k])]));
    }
    return v;
  };
  return JSON.stringify(sort(value));
}
