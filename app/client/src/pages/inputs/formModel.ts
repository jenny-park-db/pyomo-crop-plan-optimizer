/**
 * Pure logic behind the Inputs screen: overrides <-> form fields, the scenario inputs row, whether Run is
 * allowed, and the submit state machine that keeps one run_id per attempt (double-click safe).
 */
import { jsonValue, num, numOrNull } from '../../../../shared/studio/format';
import { checkName, newRunId } from '../../../../shared/studio/ids';
import { parseOverrides, parseOverridesText, stableJson, type ParsedText } from '../../../../shared/studio/overrides';
import { errorsOf } from '../../../../shared/studio/validate';
import { DEFAULT_OVERRIDES, WINDOWS, type Issue, type Overrides, type ScenarioInputs } from '../../../../shared/studio/types';

/** Percent fields are edited as percentages ("110" = ×1.10); blank means "no override" (×1.00). */
export interface FormState {
  supply: Record<string, string>;
  capacity: Record<string, Record<string, string>>;
  diversity_cap_pct: string;
  unplanted_penalty_per_acre: string;
  corn_price_per_bu: string;
  fixed_requests_enabled: boolean;
  time_limit_s: string;
  mip_rel_gap_pct: string;
  /** Kept from the source scenario; not editable in the form (edit them as JSON). */
  rest: Pick<Overrides, 'solver' | 'threads' | 'random_seed'>;
}

const pctText = (multiplier: number) => String(Math.round(multiplier * 1000) / 10);

export function formFromOverrides(o: Overrides, hybrids: string[], regions: string[]): FormState {
  return {
    supply: Object.fromEntries(hybrids.map((h) => [h, o.supply_pct[h] === undefined ? '' : pctText(o.supply_pct[h])])),
    capacity: Object.fromEntries(regions.map((r) => [r, Object.fromEntries(WINDOWS.map((w) => {
      const v = o.capacity_pct[r]?.[w];
      return [w, v === undefined ? '' : pctText(v)];
    }))])),
    diversity_cap_pct: pctText(o.diversity_cap),
    unplanted_penalty_per_acre: String(o.unplanted_penalty_per_acre),
    corn_price_per_bu: String(o.corn_price_per_bu),
    fixed_requests_enabled: o.fixed_requests_enabled,
    time_limit_s: String(o.time_limit_s),
    mip_rel_gap_pct: String(Math.round(o.mip_rel_gap * 100000) / 1000),
    rest: { solver: o.solver, threads: o.threads, random_seed: o.random_seed },
  };
}

function field(text: string, label: string): number {
  const n = numOrNull(text.trim());
  if (n === null) throw new FormFieldError(label, `${label} must be a number`);
  return n;
}

export class FormFieldError extends Error {
  readonly path: string;
  constructor(path: string, message: string) {
    super(message);
    this.path = path;
  }
}

/** Form → overrides, through the same parser the server and the job use. */
export function formToOverrides(form: FormState): ParsedText {
  try {
    const supply_pct: Record<string, number> = {};
    for (const [h, text] of Object.entries(form.supply)) {
      if (text.trim() !== '') supply_pct[h] = field(text, `Seed supply ${h}`) / 100;
    }
    const capacity_pct: Record<string, Record<string, number>> = {};
    for (const [r, windows] of Object.entries(form.capacity)) {
      for (const [w, text] of Object.entries(windows)) {
        if (text.trim() === '') continue;
        (capacity_pct[r] ??= {})[w] = field(text, `Planting capacity ${r}/${w}`) / 100;
      }
    }
    const payload = {
      supply_pct, capacity_pct,
      diversity_cap: field(form.diversity_cap_pct, 'Diversity cap') / 100,
      unplanted_penalty_per_acre: field(form.unplanted_penalty_per_acre, 'Unplanted penalty'),
      corn_price_per_bu: field(form.corn_price_per_bu, 'Corn price'),
      fixed_requests_enabled: form.fixed_requests_enabled,
      time_limit_s: field(form.time_limit_s, 'Time limit'),
      mip_rel_gap: field(form.mip_rel_gap_pct, 'MIP gap') / 100,
      ...form.rest,
    };
    return parseOverridesText(JSON.stringify(payload));
  } catch (e) {
    if (e instanceof FormFieldError) return { ok: false, path: e.path, error: e.message };
    throw e;
  }
}

/** Overrides stored on a scenario row (JSON, possibly already decoded by AppKit); a bad payload falls back to defaults. */
export function storedOverrides(json: unknown): Overrides {
  try {
    return parseOverrides(jsonValue(json) ?? {});
  } catch {
    return DEFAULT_OVERRIDES;
  }
}

export function sameOverrides(a: Overrides, b: Overrides): boolean {
  return stableJson(a) === stableJson(b);
}

function parseArray<T>(json: unknown): T[] {
  const v = jsonValue(json);
  return Array.isArray(v) ? (v as T[]) : [];
}

/** The single row of scenario_inputs.obo.sql (JSON arrays per table) → ScenarioInputs. */
export function inputsFromRow(row: Record<string, unknown>): ScenarioInputs {
  return {
    season: num(row.season),
    fields: parseArray(row.fields_json),
    hybrids: parseArray(row.hybrids_json),
    seed_supply: parseArray(row.seed_supply_json),
    yield_forecast: parseArray(row.yield_forecast_json),
    planting_capacity: parseArray(row.planting_capacity_json),
    fixed_requests: parseArray<{ field_id: string; hybrid_id: string; window?: string | null }>(row.fixed_requests_json)
      .map((r) => ({ field_id: r.field_id, hybrid_id: r.hybrid_id, window: r.window ?? null })), // to_json drops nulls
  };
}

export type RunMode = 'new' | 'resolve';

export interface RunCheck {
  enabled: boolean;
  reason: string | null;
}

/** Why a Run button is disabled, in the words the planner sees. */
export function canRun(mode: RunMode, args: {
  parsed: ParsedText; issues: Issue[] | null; name: string; dirty: boolean; submitting: boolean;
}): RunCheck {
  if (args.submitting) return { enabled: false, reason: 'Submitting…' };
  if (!args.parsed.ok) return { enabled: false, reason: args.parsed.error };
  if (args.issues === null) return { enabled: false, reason: 'Checking the inputs…' };
  const errors = errorsOf(args.issues);
  if (errors.length) return { enabled: false, reason: `Fix ${errors.length} validation error${errors.length > 1 ? 's' : ''} first` };
  if (mode === 'new') {
    const named = checkName(args.name);
    if (!named.ok) return { enabled: false, reason: named.error };
  } else if (args.dirty) {
    return { enabled: false, reason: 'Settings changed: run them as a new scenario' };
  }
  return { enabled: true, reason: null };
}

/** One run_id per attempt: kept while submitting and after a failure (a retry dedupes), replaced on success. */
export interface SubmitState {
  runId: string;
  submitting: boolean;
}
export type SubmitEvent = { type: 'start' } | { type: 'succeeded' } | { type: 'failed' };

export function submitReducer(state: SubmitState, event: SubmitEvent, makeId: () => string = newRunId): SubmitState {
  switch (event.type) {
    case 'start':
      return state.submitting ? state : { ...state, submitting: true };
    case 'succeeded':
      return { runId: makeId(), submitting: false };
    case 'failed':
      return { ...state, submitting: false };
  }
}
