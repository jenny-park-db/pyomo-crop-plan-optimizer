/**
 * GET /api/studio/runs/:runId/report and /api/studio/scenarios/:scenarioId/report: one run's outcome in the
 * shape the planning agent cites from (spec §7 "tool results must carry the numbers the agent cites").
 * Read as the signed-in user, so the agent sees exactly what that user may see.
 */
import { bool, jsonValue, numOrNull, strOrNull } from '../../shared/studio/format';
import { checkId } from '../../shared/studio/ids';
import { isActive } from '../../shared/studio/types';
import type { Tables } from './config';
import { statements as S, type SqlRunner } from './sql';
import { SubmitError } from './submit';

export interface RunKpis {
  gross_margin: number | null;
  net_margin: number | null;
  unplanted_penalty_total: number | null;
  acres_planted_pct: number | null;
  unplanted_fields: number | null;
  /** Acres of the unplanted fields (plan_assignments rows with no hybrid), so nobody has to add them up. */
  unplanted_acres: number | null;
  violations_count: number | null;
}

export interface Finding {
  rule: string;
  entity: string;
  severity: string;
  detail: string;
}

export interface RunReport {
  run_id: string;
  scenario_id: string;
  scenario_name: string | null;
  source: string | null;
  overrides: unknown;
  status: string;
  final: boolean;
  job_run_id: string | null;
  error: string | null;
  infeasibility_reason: string | null;
  diagnosis: string | null;
  termination: string | null;
  mip_gap: number | null;
  kpis: RunKpis | null;
  hybrids_at_supply_limit: string[];
  violations: Finding[];
}

export interface ReportDeps {
  sql: SqlRunner;
  t: Tables;
}

function id(value: unknown, what: string): string {
  try {
    return checkId(value, what);
  } catch (e) {
    throw new SubmitError(400, (e as Error).message);
  }
}

export async function runReport(deps: ReportDeps, rawRunId: unknown): Promise<RunReport> {
  const runId = id(rawRunId, 'run_id');
  const [row] = await deps.sql.run(S.runReport(deps.t), { run_id: runId });
  if (!row) throw new SubmitError(404, `Run ${runId} not found`);
  const status = String(row.status);
  const final = !isActive(status);
  const kpis: RunKpis | null = bool(row.has_summary) ? {
    gross_margin: numOrNull(row.gross_margin),
    net_margin: numOrNull(row.net_margin),
    unplanted_penalty_total: numOrNull(row.unplanted_penalty_total),
    acres_planted_pct: numOrNull(row.acres_planted_pct),
    unplanted_fields: numOrNull(row.unplanted_fields),
    unplanted_acres: numOrNull(row.unplanted_acres),
    violations_count: numOrNull(row.violations_count),
  } : null;
  const [limits, findings] = final
    ? await Promise.all([
      deps.sql.run(S.hybridsAtLimit(deps.t), { run_id: runId }),
      deps.sql.run(S.runViolations(deps.t), { run_id: runId }),
    ])
    : [[], []];
  return {
    run_id: runId,
    scenario_id: String(row.scenario_id),
    scenario_name: strOrNull(row.scenario_name),
    source: strOrNull(row.source),
    overrides: row.overrides == null ? null : jsonValue(row.overrides),
    status,
    final,
    job_run_id: strOrNull(row.job_run_id),
    error: strOrNull(row.error),
    infeasibility_reason: strOrNull(row.infeasibility_reason),
    diagnosis: strOrNull(row.diagnosis),
    termination: strOrNull(row.termination),
    mip_gap: numOrNull(row.mip_gap),
    kpis,
    hybrids_at_supply_limit: limits.map((r) => String(r.hybrid_id)),
    violations: findings.map((r) => ({
      rule: String(r.rule), entity: String(r.entity), severity: String(r.severity), detail: String(r.detail),
    })),
  };
}

export async function scenarioReport(deps: ReportDeps, rawScenarioId: unknown): Promise<RunReport> {
  const scenarioId = id(rawScenarioId, 'scenario_id');
  const [latest] = await deps.sql.run(S.latestFinishedRun(deps.t), { scenario_id: scenarioId });
  if (!latest) throw new SubmitError(404, `Scenario ${scenarioId} has no finished run`);
  return runReport(deps, latest.run_id);
}
