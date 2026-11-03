/** Domain types shared by the browser and the server. Mirrors spec §3 and cropplan.overrides.Overrides. */

export const WINDOWS = ['W1', 'W2', 'W3', 'W4'] as const;
export type PlantingWindow = (typeof WINDOWS)[number];

export const ACTIVE_STATUSES = ['queued', 'validating', 'solving', 'checking'] as const;
export const FINAL_STATUSES = ['done', 'invalid', 'infeasible', 'failed'] as const;
export type RunStatus = (typeof ACTIVE_STATUSES)[number] | (typeof FINAL_STATUSES)[number];

export function isActive(status: string | null | undefined): boolean {
  return (ACTIVE_STATUSES as readonly string[]).includes(status ?? '');
}

export const SEEDED_SCENARIOS = ['baseline-2027', 'grower-commitments-2027', 'revision-1-2027'] as const;
export const BASELINE_ID = 'baseline-2027';

export interface Overrides {
  supply_pct: Record<string, number>;
  capacity_pct: Record<string, Record<string, number>>;
  diversity_cap: number;
  unplanted_penalty_per_acre: number;
  corn_price_per_bu: number;
  fixed_requests_enabled: boolean;
  solver: 'highs' | 'gurobi';
  time_limit_s: number;
  mip_rel_gap: number;
  threads: number | null;
  random_seed: number | null;
}

export const DEFAULT_OVERRIDES: Overrides = {
  supply_pct: {},
  capacity_pct: {},
  diversity_cap: 0.4,
  unplanted_penalty_per_acre: 150,
  corn_price_per_bu: 4.25,
  fixed_requests_enabled: true,
  solver: 'highs',
  time_limit_s: 60,
  mip_rel_gap: 0.001,
  threads: 1,
  random_seed: 2027,
};

export interface FieldRow {
  field_id: string;
  grower_id: string;
  region: string;
  acres: number;
  lat: number;
  lon: number;
  soil_class: string;
  rm_min: number;
  rm_max: number;
}
export interface HybridRow {
  hybrid_id: string;
  relative_maturity: number;
  units_per_acre: number;
}
export interface SupplyRow {
  season: number;
  hybrid_id: string;
  units_available: number;
}
export interface ForecastKey {
  region: string;
  soil_class: string;
  hybrid_id: string;
  window: string;
}
export interface CapacityRow {
  region: string;
  window: string;
  acres_capacity: number;
}
export interface FixedRequestRow {
  field_id: string;
  hybrid_id: string;
  window: string | null;
}

/** The parts of a scenario's inputs that pre-solve validation reads (cropplan.data.ScenarioInputs). */
export interface ScenarioInputs {
  season: number;
  fields: FieldRow[];
  hybrids: HybridRow[];
  seed_supply: SupplyRow[];
  yield_forecast: ForecastKey[];
  planting_capacity: CapacityRow[];
  fixed_requests: FixedRequestRow[];
}

export interface Issue {
  severity: 'error' | 'warning';
  rule: string;
  entity: string;
  detail: string;
}
