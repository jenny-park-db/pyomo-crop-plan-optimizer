/** Pure logic for the Runs screen: row parsing, links, ordering, and status tones. */
import { num, numOrNull, strOrNull, toMs } from '../../../../shared/studio/format';
import { isActive } from '../../../../shared/studio/types';
import type { ClientConfig } from '../../../../server/studio/config';

export interface RunView {
  run_id: string;
  scenario_id: string;
  scenario_name: string;
  source: string | null;
  triggered_by: string | null;
  status: string;
  solver: string | null;
  model_version: string | null;
  submitted_ms: number | null;
  started_ms: number | null;
  ended_ms: number | null;
  reason: string | null;
  diagnosis: string | null;
  termination: string | null;
  mip_gap: number | null;
  objective: number | null;
  runtime_s: number | null;
  job_run_url: string | null;
  mlflow_url: string | null;
}

type Cfg = Pick<ClientConfig, 'host' | 'solveJobId' | 'experimentId'>;

export const DIAGNOSIS_LABEL: Record<string, string> = {
  explained: 'Binding constraint found',
  fixed_requests_impossible: 'Fixed requests contradict each other',
  diagnosis_failed: 'Diagnosis failed',
};

export function toRunView(r: Record<string, unknown>, cfg: Cfg): RunView {
  const jobRunId = strOrNull(r.job_run_id);
  const mlflowRunId = strOrNull(r.mlflow_run_id);
  const solver = strOrNull(r.solver);
  const solverVersion = strOrNull(r.solver_version);
  return {
    run_id: String(r.run_id),
    scenario_id: String(r.scenario_id),
    scenario_name: strOrNull(r.scenario_name) ?? String(r.scenario_id),
    source: strOrNull(r.source),
    triggered_by: strOrNull(r.triggered_by),
    status: String(r.status),
    solver: solver ? `${solver}${solverVersion ? ` ${solverVersion}` : ''}` : null,
    model_version: strOrNull(r.model_version),
    submitted_ms: toMs(r.submitted_ms),
    started_ms: toMs(r.started_ms),
    ended_ms: toMs(r.ended_ms),
    reason: strOrNull(r.infeasibility_reason) ?? strOrNull(r.error),
    diagnosis: strOrNull(r.diagnosis),
    termination: strOrNull(r.termination),
    mip_gap: numOrNull(r.mip_gap),
    objective: numOrNull(r.objective),
    runtime_s: numOrNull(r.runtime_s),
    job_run_url: jobRunId ? `${cfg.host}/jobs/${cfg.solveJobId}/runs/${jobRunId}` : null,
    mlflow_url: mlflowRunId && cfg.experimentId ? `${cfg.host}/ml/experiments/${cfg.experimentId}/runs/${mlflowRunId}` : null,
  };
}

/** Newest first by start (or submit) time; rows with no time last. */
export function sortRuns(runs: RunView[]): RunView[] {
  const t = (r: RunView) => r.started_ms ?? r.submitted_ms ?? -Infinity;
  return [...runs].sort((a, b) => t(b) - t(a) || a.run_id.localeCompare(b.run_id));
}

export function anyActive(runs: RunView[]): boolean {
  return runs.some((r) => isActive(r.status));
}

/** Wall-clock time of a run: start→end, or start→now while active. */
export function elapsedMs(r: RunView, nowMs: number): number | null {
  const start = r.started_ms ?? r.submitted_ms;
  if (start === null) return null;
  const end = r.ended_ms ?? (isActive(r.status) ? nowMs : null);
  return end === null ? null : Math.max(0, end - start);
}

export type Tone = 'active' | 'good' | 'bad' | 'warn';

export function statusTone(status: string): Tone {
  if (isActive(status)) return 'active';
  if (status === 'done') return 'good';
  if (status === 'infeasible' || status === 'invalid') return 'warn';
  return 'bad';
}

/** "optimal", or "maxTimeLimit · gap 0.80%" when the solver stopped early with a solution (spec §8). */
export function terminationLabel(r: Pick<RunView, 'termination' | 'mip_gap'>): string {
  if (!r.termination) return '–';
  if (r.termination === 'optimal' || r.mip_gap === null) return r.termination;
  return `${r.termination} · gap ${(num(r.mip_gap) * 100).toFixed(2)}%`;
}
