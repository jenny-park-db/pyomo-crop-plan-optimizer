/**
 * The app's write statements (and the reads its write paths depend on). Every value is a named parameter;
 * only table names, which come from validated config, are interpolated. They run as the signed-in user.
 */
import type { StudioTable, Tables } from './config';
import { ACTIVE_STATUSES } from '../../shared/studio/types';

export type Row = Record<string, unknown>;
export type SqlParam = string | number | boolean;
export type SqlParams = Record<string, SqlParam>;

/** Runs one statement as the signed-in user and returns its rows (all values may arrive as strings). */
export interface SqlRunner {
  run(statement: string, params?: SqlParams): Promise<Row[]>;
}

export const INPUT_TABLES = [
  'fields', 'hybrids', 'seed_supply', 'yield_forecast', 'planting_capacity', 'fixed_requests',
] as const satisfies readonly StudioTable[];
export type InputTable = (typeof INPUT_TABLES)[number];

/** Per-scenario input tables and their columns after scenario_id (cropplan_jobs.tables.INPUTS). */
export const INPUT_COLUMNS: Record<InputTable, string[]> = {
  fields: ['field_id', 'grower_id', 'region', 'acres', 'lat', 'lon', 'soil_class', 'rm_min', 'rm_max'],
  hybrids: ['hybrid_id', 'relative_maturity', 'seed_cost_per_unit', 'units_per_acre', 'disease_tolerance'],
  seed_supply: ['season', 'hybrid_id', 'units_available'],
  yield_forecast: ['region', 'soil_class', 'hybrid_id', 'window', 'exp_yield_bu_ac', 'yield_sd', 'source_model_version'],
  planting_capacity: ['region', 'window', 'acres_capacity'],
  fixed_requests: ['field_id', 'hybrid_id', 'window'],
};

const ACTIVE_LIST = ACTIVE_STATUSES.map((s) => `'${s}'`).join(', ');
const q = (c: string) => `\`${c}\``;

export const statements = {
  findRun: (t: Tables) =>
    `SELECT run_id, scenario_id, job_run_id, status FROM ${t('runs')} WHERE run_id = :run_id`,

  findScenario: (t: Tables) =>
    `SELECT scenario_id, name, season, parent_scenario_id, created_by FROM ${t('scenarios')} WHERE scenario_id = :scenario_id`,

  /** Copy one input table from the source scenario. A no-op when the new scenario already has rows. */
  copyInputs: (t: Tables, table: InputTable) => {
    const cols = INPUT_COLUMNS[table].map(q).join(', ');
    const name = t(table);
    return `INSERT INTO ${name} (${q('scenario_id')}, ${cols}) ` +
      `SELECT :new_id, ${cols} FROM ${name} WHERE ${q('scenario_id')} = :source_id ` +
      `AND NOT EXISTS (SELECT 1 FROM ${name} WHERE ${q('scenario_id')} = :new_id)`;
  },

  deleteScenarioRows: (t: Tables, table: StudioTable) =>
    `DELETE FROM ${t(table)} WHERE scenario_id = :scenario_id`,

  insertScenario: (t: Tables) =>
    `MERGE INTO ${t('scenarios')} AS t USING (SELECT :scenario_id AS scenario_id) AS s ` +
    `ON t.scenario_id = s.scenario_id WHEN NOT MATCHED THEN INSERT ` +
    `(scenario_id, name, parent_scenario_id, season, overrides, created_by, created_at, source, status) VALUES ` +
    `(:scenario_id, :name, :parent_id, CAST(:season AS INT), :overrides, :created_by, current_timestamp(), :source, 'active')`,

  /** The runs row the job will reuse (status queued). num_inserted_rows = 0 means someone else opened it. */
  openRun: (t: Tables) =>
    `MERGE INTO ${t('runs')} AS t USING (SELECT :run_id AS run_id) AS s ON t.run_id = s.run_id ` +
    `WHEN NOT MATCHED THEN INSERT (run_id, scenario_id, triggered_by, status, submitted_at) ` +
    `VALUES (:run_id, :scenario_id, :triggered_by, 'queued', current_timestamp())`,

  setJobRunId: (t: Tables) =>
    `UPDATE ${t('runs')} SET job_run_id = :job_run_id WHERE run_id = :run_id AND job_run_id IS NULL`,

  /** Only an active row is failed, so a final status the job wrote in the meantime is never overwritten. */
  markFailed: (t: Tables) =>
    `UPDATE ${t('runs')} SET status = 'failed', error = :error, ended_at = current_timestamp() ` +
    `WHERE run_id = :run_id AND status IN (${ACTIVE_LIST})`,

  /** One run with its scenario and KPIs (LEFT JOIN: KPIs exist only for a done run). Read as the user. */
  runReport: (t: Tables) =>
    `SELECT r.run_id, r.scenario_id, s.name AS scenario_name, s.source, s.overrides, r.status, r.job_run_id, r.error, ` +
    `r.infeasibility_reason, r.diagnosis, r.termination, r.mip_gap, m.gross_margin, m.net_margin, ` +
    `m.unplanted_penalty_total, m.acres_planted_pct, m.unplanted_fields, m.violations_count, ` +
    `(SELECT sum(a.acres) FROM ${t('plan_assignments')} a WHERE a.run_id = r.run_id AND a.hybrid_id IS NULL) AS unplanted_acres, ` +
    `m.run_id IS NOT NULL AS has_summary ` +
    `FROM ${t('runs')} r LEFT JOIN ${t('scenarios')} s ON s.scenario_id = r.scenario_id ` +
    `LEFT JOIN ${t('run_summary')} m ON m.run_id = r.run_id WHERE r.run_id = :run_id`,

  /** Hybrids whose seed use reached the supply limit (same 99% threshold as the Results tiles and Genie). */
  hybridsAtLimit: (t: Tables) =>
    `SELECT hybrid_id FROM ${t('seed_utilization')} WHERE run_id = :run_id AND pct >= 0.99 ORDER BY hybrid_id`,

  /** The first ten findings of a run, most important first (same order as the Results violations list). */
  runViolations: (t: Tables) =>
    `SELECT rule, entity, severity, detail FROM ${t('violations')} WHERE run_id = :run_id ` +
    `ORDER BY CASE severity WHEN 'binding' THEN 0 WHEN 'error' THEN 1 WHEN 'hard' THEN 2 WHEN 'warning' THEN 3 ELSE 4 END, ` +
    `entity LIMIT 10`,

  /** The scenario's most recent finished run, a done run first. */
  latestFinishedRun: (t: Tables) =>
    `SELECT run_id FROM ${t('runs')} WHERE scenario_id = :scenario_id AND status IN ('done', 'invalid', 'infeasible', 'failed') ` +
    `ORDER BY CASE WHEN status = 'done' THEN 0 ELSE 1 END, coalesce(ended_at, started_at, submitted_at) DESC LIMIT 1`,

  stressSummary: (t: Tables) =>
    `SELECT stress_id, scenario_id, n, n_solved, n_invalid, n_infeasible, n_failed, p10_gross_margin, p50_gross_margin, ` +
    `p90_gross_margin, to_json(fragile_fields) AS fragile_fields_json, to_json(fragile_hybrids) AS fragile_hybrids_json, ` +
    `job_run_id FROM ${t('stress_test_summary')} WHERE stress_id = :stress_id`,


  activeRuns: (t: Tables) =>
    `SELECT run_id, job_run_id, status, unix_millis(submitted_at) AS submitted_ms FROM ${t('runs')} ` +
    `WHERE status IN (${ACTIVE_LIST})`,
};

/** Delta reports a concurrent writer on the same rows this way (verified with three parallel MERGEs). */
export function isWriteConflict(e: unknown): boolean {
  const text = e instanceof Error ? e.message : String(e);
  return /DELTA_CONCURRENT_APPEND|ConcurrentAppend|CONCURRENT_WRITE/i.test(text);
}
