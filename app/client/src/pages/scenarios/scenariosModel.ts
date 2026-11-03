/** Pure logic for the Scenarios screen: lineage, plan diffs, stress-test selection, and histograms. */
import { jsonValue, num, numOrNull, strOrNull, toMs } from '../../../../shared/studio/format';
import type { PlanRow } from '../results/resultsModel';

export interface ScenarioView {
  scenario_id: string;
  name: string;
  parent_scenario_id: string | null;
  source: string | null;
  created_by: string | null;
  created_ms: number | null;
  latest_status: string | null;
  latest_done_run_id: string | null;
}

export function toScenarioView(r: Record<string, unknown>): ScenarioView {
  return {
    scenario_id: String(r.scenario_id), name: strOrNull(r.name) ?? String(r.scenario_id),
    parent_scenario_id: strOrNull(r.parent_scenario_id), source: strOrNull(r.source), created_by: strOrNull(r.created_by),
    created_ms: toMs(r.created_ms), latest_status: strOrNull(r.latest_status), latest_done_run_id: strOrNull(r.latest_done_run_id),
  };
}

export interface LineageNode {
  scenario: ScenarioView;
  depth: number;
  children: LineageNode[];
}

/** Parent → children tree, oldest first. A scenario whose parent is missing (or a cycle) becomes a root. */
export function buildLineage(scenarios: ScenarioView[]): LineageNode[] {
  const byId = new Map(scenarios.map((s) => [s.scenario_id, s]));
  const kids = new Map<string, ScenarioView[]>();
  const roots: ScenarioView[] = [];
  for (const s of scenarios) {
    const p = s.parent_scenario_id;
    if (p && p !== s.scenario_id && byId.has(p)) kids.set(p, [...(kids.get(p) ?? []), s]);
    else roots.push(s);
  }
  const order = (a: ScenarioView, b: ScenarioView) => (a.created_ms ?? 0) - (b.created_ms ?? 0) || a.scenario_id.localeCompare(b.scenario_id);
  const seen = new Set<string>();
  const build = (s: ScenarioView, depth: number): LineageNode => {
    seen.add(s.scenario_id);
    const children = (kids.get(s.scenario_id) ?? []).filter((c) => !seen.has(c.scenario_id)).sort(order).map((c) => build(c, depth + 1));
    return { scenario: s, depth, children };
  };
  const tree = roots.sort(order).map((s) => build(s, 0));
  // Anything not reached is in a parent cycle: show it as a root instead of dropping it.
  for (const s of [...scenarios].sort(order)) {
    if (!seen.has(s.scenario_id)) tree.push(build(s, 0));
  }
  return tree;
}

export function flatten(nodes: LineageNode[]): LineageNode[] {
  return nodes.flatMap((n) => [n, ...flatten(n.children)]);
}

export interface FieldChange {
  field_id: string;
  region: string;
  from: string;
  to: string;
  margin_delta: number;
}

const label = (r: PlanRow | undefined) => (!r ? 'missing' : r.hybrid_id ? `${r.hybrid_id} ${r.window}` : 'unplanted');

/** Fields whose hybrid or window differs between two plans (spec §6.4 "changed-fields list"). */
export function diffPlans(base: PlanRow[], other: PlanRow[]): FieldChange[] {
  const b = new Map(base.map((r) => [r.field_id, r]));
  const o = new Map(other.map((r) => [r.field_id, r]));
  const ids = [...new Set([...b.keys(), ...o.keys()])].sort();
  return ids.flatMap((id) => {
    const x = b.get(id);
    const y = o.get(id);
    if (x && y && x.hybrid_id === y.hybrid_id && x.window === y.window) return [];
    return [{ field_id: id, region: (y ?? x)!.region, from: label(x), to: label(y), margin_delta: (y?.exp_margin ?? 0) - (x?.exp_margin ?? 0) }];
  });
}

export interface StressView {
  stress_id: string;
  scenario_id: string;
  n: number;
  n_solved: number;
  n_failed: number;
  p10: number | null;
  p50: number | null;
  p90: number | null;
  fragile_fields: string[];
  fragile_hybrids: string[];
  mlflow_run_id: string | null;
  triggered_by: string | null;
  created_ms: number | null;
}

const list = (json: unknown): string[] => {
  const v = jsonValue(json);
  return Array.isArray(v) ? v.map(String) : [];
};

export function toStressView(r: Record<string, unknown>): StressView {
  return {
    stress_id: String(r.stress_id), scenario_id: String(r.scenario_id), n: num(r.n), n_solved: num(r.n_solved),
    n_failed: num(r.n_failed), p10: numOrNull(r.p10_gross_margin), p50: numOrNull(r.p50_gross_margin),
    p90: numOrNull(r.p90_gross_margin), fragile_fields: list(r.fragile_fields_json), fragile_hybrids: list(r.fragile_hybrids_json),
    mlflow_run_id: strOrNull(r.mlflow_run_id), triggered_by: strOrNull(r.triggered_by), created_ms: toMs(r.created_ms),
  };
}

/** The stress test that represents a scenario: the largest n, newest among those (the stored N=500 runs). */
export function pickStress(all: StressView[], scenarioId: string): StressView | null {
  const mine = all.filter((s) => s.scenario_id === scenarioId);
  return mine.sort((a, b) => b.n - a.n || (b.created_ms ?? 0) - (a.created_ms ?? 0))[0] ?? null;
}

/**
 * Whether "Run live stress test" is clickable: not while a start request is in flight (a double click would launch
 * two GPU job runs), nor while the started run is pending its first status or still running.
 */
export function canStartLive(starting: boolean, live: { status: { state: string } | null } | null): boolean {
  if (starting) return false;
  if (live === null) return true;
  return live.status !== null && live.status.state !== 'running';
}

export interface Bin {
  label: string;
  from: number;
  to: number;
  [series: string]: number | string;
}

/** Shared-edge histogram for several distributions, so bars compare on one scale (IBCS: same scale). */
export function histogram(series: Record<string, number[]>, bins = 16): Bin[] {
  const all = Object.values(series).flat();
  if (!all.length) return [];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const width = hi > lo ? (hi - lo) / bins : 1;
  return Array.from({ length: bins }, (_, i) => {
    const from = lo + i * width;
    const to = i === bins - 1 ? hi : from + width;
    const bin: Bin = { label: `$${(from / 1e6).toFixed(2)}M`, from, to };
    for (const [name, values] of Object.entries(series)) {
      bin[name] = values.filter((v) => v >= from && (i === bins - 1 ? v <= to : v < to)).length;
    }
    return bin;
  });
}
