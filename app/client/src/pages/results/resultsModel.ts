/** Pure logic for the Results screen: which run to show, row parsing, KPI deltas, grouping, map projection. */
import { bool, num, numOrNull, strOrNull, toMs } from '../../../../shared/studio/format';
import { isActive } from '../../../../shared/studio/types';
import type { RunView } from '../runs/runsModel';

export type ResultPick =
  | { kind: 'show'; run: RunView; note: string | null }
  | { kind: 'empty'; title: string; description: string; run: RunView | null };

/**
 * The run whose results to show: the requested run if it is done, else the latest done run. When nothing
 * is done, explain the latest run's state instead of drawing an empty map (demo step 4 lands here).
 * `runs` must be sorted newest first (sortRuns).
 */
export function pickResultRun(runs: RunView[], requestedRunId: string | null): ResultPick {
  const requested = requestedRunId ? runs.find((r) => r.run_id === requestedRunId) ?? null : null;
  const latestDone = runs.find((r) => r.status === 'done') ?? null;
  const subject = requested ?? runs[0] ?? null;
  if (requested?.status === 'done') return { kind: 'show', run: requested, note: null };
  if (!requested && latestDone) {
    const newer = runs[0] !== latestDone ? runs[0] : null;
    return { kind: 'show', run: latestDone, note: newer ? `A newer run (${newer.run_id}) is ${newer.status}.` : null };
  }
  if (!subject) return { kind: 'empty', title: 'No runs for this scenario yet', description: 'Run it from Inputs to see a plan.', run: null };
  if (isActive(subject.status)) {
    return { kind: 'empty', title: `Run ${subject.run_id} is ${subject.status}`, description: 'Results appear here when it finishes. This page refreshes every 5 s.', run: subject };
  }
  const why = subject.reason ?? 'No reason was recorded.';
  const title = subject.status === 'infeasible' ? 'No feasible plan'
    : subject.status === 'invalid' ? 'The inputs failed validation' : 'The run failed';
  return { kind: 'empty', title, description: why, run: subject };
}

/** Results reconciles and re-reads while the run it is explaining is still queued or solving (spec §3). */
export function resultsShouldPoll(pick: ResultPick): boolean {
  return pick.kind === 'empty' && isActive(pick.run?.status);
}

export interface PlanRow {
  field_id: string;
  grower_id: string;
  region: string;
  soil_class: string;
  acres: number;
  lat: number;
  lon: number;
  hybrid_id: string | null;
  window: string | null;
  exp_yield: number;
  exp_margin: number;
  is_fixed: boolean;
}

export function toPlanRow(r: Record<string, unknown>): PlanRow {
  return {
    field_id: String(r.field_id), grower_id: String(r.grower_id), region: String(r.region),
    soil_class: String(r.soil_class), acres: num(r.acres), lat: num(r.lat), lon: num(r.lon),
    hybrid_id: strOrNull(r.hybrid_id), window: strOrNull(r.planting_window), exp_yield: num(r.exp_yield),
    exp_margin: num(r.exp_margin), is_fixed: bool(r.is_fixed),
  };
}

export interface Summary {
  run_id: string;
  status: string;
  ended_ms: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  unplanted_penalty_total: number | null;
  acres_planted_pct: number | null;
  unplanted_fields: number | null;
  hybrids_at_limit: number | null;
  termination: string | null;
  mip_gap: number | null;
}

export function toSummary(r: Record<string, unknown>): Summary {
  return {
    run_id: String(r.run_id), status: String(r.status), ended_ms: toMs(r.ended_ms),
    gross_margin: numOrNull(r.gross_margin), net_margin: numOrNull(r.net_margin),
    unplanted_penalty_total: numOrNull(r.unplanted_penalty_total), acres_planted_pct: numOrNull(r.acres_planted_pct),
    unplanted_fields: numOrNull(r.unplanted_fields), hybrids_at_limit: numOrNull(r.hybrids_at_limit),
    termination: strOrNull(r.termination), mip_gap: numOrNull(r.mip_gap),
  };
}

/** a − b, or null when either side is missing. */
export function delta(a: number | null, b: number | null): number | null {
  return a === null || b === null ? null : a - b;
}

export const GROUPINGS = ['region', 'grower', 'field', 'hybrid', 'window'] as const;
export type Grouping = (typeof GROUPINGS)[number];

export interface Filters {
  region: string | null;
  hybrid: string | null;
  window: string | null;
}

export interface GroupRow {
  key: string;
  fields: number;
  acres: number;
  planted_acres: number;
  unplanted_fields: number;
  gross_margin: number;
  /** Acre-weighted expected yield of the planted acres, bu/ac. */
  yield_bu_ac: number | null;
}

const UNPLANTED = 'Unplanted';

function groupKey(r: PlanRow, by: Grouping): string {
  switch (by) {
    case 'region': return r.region;
    case 'grower': return r.grower_id;
    case 'field': return r.field_id;
    case 'hybrid': return r.hybrid_id ?? UNPLANTED;
    case 'window': return r.window ?? UNPLANTED;
  }
}

export function filterPlan(rows: PlanRow[], f: Filters): PlanRow[] {
  return rows.filter((r) => (!f.region || r.region === f.region)
    && (!f.hybrid || (f.hybrid === UNPLANTED ? r.hybrid_id === null : r.hybrid_id === f.hybrid))
    && (!f.window || (f.window === UNPLANTED ? r.window === null : r.window === f.window)));
}

export function groupPlan(rows: PlanRow[], by: Grouping): GroupRow[] {
  const groups = new Map<string, PlanRow[]>();
  for (const r of rows) {
    const k = groupKey(r, by);
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  return [...groups.entries()].map(([key, rs]) => {
    const planted = rs.filter((r) => r.hybrid_id !== null);
    const plantedAcres = planted.reduce((s, r) => s + r.acres, 0);
    return {
      key, fields: rs.length, acres: rs.reduce((s, r) => s + r.acres, 0), planted_acres: plantedAcres,
      unplanted_fields: rs.length - planted.length, gross_margin: rs.reduce((s, r) => s + r.exp_margin, 0),
      yield_bu_ac: plantedAcres > 0 ? planted.reduce((s, r) => s + r.exp_yield * r.acres, 0) / plantedAcres : null,
    };
  }).sort((a, b) => (a.key === UNPLANTED ? 1 : b.key === UNPLANTED ? -1 : a.key.localeCompare(b.key)));
}

export interface Bounds {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
}

export function boundsOf(rows: Array<{ lat: number; lon: number }>, pad = 0.3): Bounds {
  if (!rows.length) return { minLat: 39, maxLat: 44, minLon: -101, maxLon: -87 };
  const lats = rows.map((r) => r.lat);
  const lons = rows.map((r) => r.lon);
  return { minLat: Math.min(...lats) - pad, maxLat: Math.max(...lats) + pad, minLon: Math.min(...lons) - pad, maxLon: Math.max(...lons) + pad };
}

/** Equirectangular projection (x scaled by cos(latitude)) into a w×h SVG box, north up. */
export function project(lat: number, lon: number, b: Bounds, w: number, h: number): { x: number; y: number } {
  const k = Math.cos(((b.minLat + b.maxLat) / 2) * (Math.PI / 180));
  const spanX = (b.maxLon - b.minLon) * k;
  const spanY = b.maxLat - b.minLat;
  const scale = Math.min(w / spanX, h / spanY);
  const offX = (w - spanX * scale) / 2;
  const offY = (h - spanY * scale) / 2;
  return { x: offX + (lon - b.minLon) * k * scale, y: offY + (b.maxLat - lat) * scale };
}

/** Marker radius in pixels: area proportional to acres (spec §6.3 "size = acres"). */
export function radiusFor(acres: number, maxAcres: number, maxRadius = 11): number {
  return maxAcres > 0 ? Math.max(3, maxRadius * Math.sqrt(acres / maxAcres)) : 3;
}
