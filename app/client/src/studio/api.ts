/** fetch helpers for the app's own /api/studio routes. */
import type { TurnState, TurnStatus } from '../../../server/studio/agentProxy';
import type { ClientConfig } from '../../../server/studio/config';
import type { SubmitRequest, SubmitResult } from '../../../server/studio/submit';
import type { SyncResult } from '../../../server/studio/reconcile';

export class ApiError extends Error {
  readonly status: number;
  readonly path: string | null;
  constructor(status: number, message: string, path: string | null) {
    super(message);
    this.status = status;
    this.path = path;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  const body = (await res.json().catch(() => ({}))) as { error?: string; path?: string | null };
  if (!res.ok) throw new ApiError(res.status, body.error ?? `${res.status} ${res.statusText}`, body.path ?? null);
  return body as T;
}

export interface Me {
  email: string;
  name: string | null;
  obo_scopes: string[];
}

export type StressStart = { stress_id: string; job_run_id: string; n: number };
export type StressStatus = { state: 'running' | 'succeeded' | 'failed'; message: string | null; run_page_url: string | null };

export const studioApi = {
  config: () => call<ClientConfig>('/api/studio/config'),
  whoami: () => call<Me>('/api/studio/whoami'),
  submit: (body: SubmitRequest) => call<SubmitResult>('/api/studio/runs', { method: 'POST', body: JSON.stringify(body) }),
  sync: () => call<SyncResult>('/api/studio/runs/sync', { method: 'POST', body: '{}' }),
  startStress: (scenario_id: string, n: number) =>
    call<StressStart>('/api/studio/stress', { method: 'POST', body: JSON.stringify({ scenario_id, n }) }),
  stressStatus: (jobRunId: string) => call<StressStatus>(`/api/studio/stress/${encodeURIComponent(jobRunId)}`),
  agentStart: (session_id: string, message: string) =>
    call<{ id: string; status: TurnStatus }>('/api/studio/agent/turns', { method: 'POST', body: JSON.stringify({ session_id, message }) }),
  agentPoll: (id: string) => call<TurnState>(`/api/studio/agent/turns/${encodeURIComponent(id)}`),
};
