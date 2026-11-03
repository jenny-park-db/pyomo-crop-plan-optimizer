/**
 * POST /api/studio/agent/turns and GET /api/studio/agent/turns/:id: the Assistant's Agent tab talks to the
 * planning agent (an Agent Bricks Databricks App) through these routes, forwarding the signed-in user's
 * token (x-forwarded-access-token) so the agent and its tools act as that user.
 * Turns run as background invocations and the browser polls, so no request outlives the Apps proxy timeout
 * while the agent waits up to 240 s on a solve.
 */
import { randomUUID } from 'node:crypto';
import { SubmitError } from './submit';

export const MESSAGE_MAX = 4000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback);

/** The subset of fetch used here, so tests can fake it. */
export type AgentFetch = (url: string, init: RequestInit) => Promise<{ ok: boolean; status: number; text(): Promise<string> }>;

export interface AgentProxyDeps {
  agentUrl: string | null;
  fetch: AgentFetch;
  newId?: () => string;
  /** Per call to the agent. Turns are background invocations, so every call returns at once when healthy. */
  timeoutMs?: number;
}

export const AGENT_CALL_TIMEOUT_MS = 30_000;

export type TurnStatus = 'queued' | 'active' | 'completed' | 'failed';

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

/** A LangGraph message without token counts and provider metadata. */
export interface SlimMessage {
  type: string;
  content: unknown;
  tool_calls?: ToolCall[];
  name?: string;
  tool_call_id?: string;
  status?: string;
}

export interface TurnState {
  id: string;
  status: TurnStatus;
  error: string | null;
  messages: SlimMessage[];
}

function requireAgent(deps: AgentProxyDeps, token: string | undefined): { url: string; token: string } {
  if (!deps.agentUrl) throw new SubmitError(503, 'The planning agent is not deployed for this app yet (CROP_PLAN_AGENT_URL is not set).');
  if (!token) throw new SubmitError(401, "Agent chat needs the signed-in user's token; open the deployed app instead of local dev.");
  return { url: deps.agentUrl, token };
}

async function call(deps: AgentProxyDeps, url: string, token: string, init: RequestInit, routingKey?: string): Promise<Record<string, unknown>> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };
  if (routingKey) headers['X-Routing-Key'] = routingKey;
  // redirect: manual, so an Apps sign-in redirect (no CAN_USE) is reported as such, not parsed as the agent's reply.
  const timeoutMs = deps.timeoutMs ?? AGENT_CALL_TIMEOUT_MS;
  let res: Awaited<ReturnType<AgentFetch>>;
  let text: string;
  try {
    res = await deps.fetch(url, { ...init, headers, redirect: 'manual', signal: AbortSignal.timeout(timeoutMs) });
    text = await res.text();
  } catch (e) {
    if (e instanceof Error && (e.name === 'TimeoutError' || e.name === 'AbortError')) {
      throw new SubmitError(504, `The planning agent did not answer within ${Math.round(timeoutMs / 1000)} s; try again.`);
    }
    throw e;
  }
  if (res.status === 401 || res.status === 403 || (res.status >= 300 && res.status < 400)) {
    throw new SubmitError(403, 'You do not have permission to use the planning agent (ask for CAN_USE on its app).');
  }
  if (!res.ok) throw new SubmitError(502, `The planning agent answered ${res.status}: ${text.slice(0, 300)}`);
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new SubmitError(502, `The planning agent sent a non-JSON reply: ${text.slice(0, 200)}`);
  }
}

export async function startTurn(deps: AgentProxyDeps, token: string | undefined, body: unknown): Promise<{ id: string; status: TurnStatus }> {
  const { session_id: sessionId, message } = (body ?? {}) as { session_id?: unknown; message?: unknown };
  const text = typeof message === 'string' ? message.trim() : '';
  if (!text || text.length > MESSAGE_MAX) throw new SubmitError(400, `Type a message of 1–${MESSAGE_MAX} characters.`, 'message');
  if (typeof sessionId !== 'string' || !UUID.test(sessionId)) throw new SubmitError(400, 'session_id must be a UUID', 'session_id');
  const agent = requireAgent(deps, token);
  const id = (deps.newId ?? randomUUID)();
  const out = await call(deps, `${agent.url}/api/invocations`, agent.token, {
    method: 'POST',
    body: JSON.stringify({ id, session_id: sessionId, background: true, input: { messages: [{ role: 'user', content: text }] } }),
  }, sessionId);
  return { id: str(out.id, id), status: str(out.status, 'queued') as TurnStatus };
}

export function slimMessages(raw: unknown): SlimMessage[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isRecord).map((m) => {
    const slim: SlimMessage = { type: str(m.type), content: m.content ?? '' };
    if (slim.type === 'ai') {
      slim.tool_calls = (Array.isArray(m.tool_calls) ? m.tool_calls : []).filter(isRecord).map((c) => ({
        id: str(c.id), name: str(c.name), args: isRecord(c.args) ? c.args : {},
      }));
    }
    if (slim.type === 'tool') {
      slim.name = str(m.name);
      slim.tool_call_id = str(m.tool_call_id);
      slim.status = str(m.status, 'success');
    }
    return slim;
  });
}

function errorText(error: unknown): string {
  if (isRecord(error) && typeof error.message === 'string') return error.message;
  return typeof error === 'string' ? error : 'The planning agent failed on this turn.';
}

export async function pollTurn(deps: AgentProxyDeps, token: string | undefined, id: string): Promise<TurnState> {
  if (!UUID.test(id)) throw new SubmitError(400, 'invocation id must be a UUID');
  const agent = requireAgent(deps, token);
  const out = await call(deps, `${agent.url}/api/invocations/${id}`, agent.token, { method: 'GET' });
  const status = str(out.status, 'active') as TurnStatus;
  const output = isRecord(out.output) ? out.output.output : undefined;
  return {
    id,
    status,
    error: status === 'failed' ? errorText(out.error) : null,
    messages: status === 'completed' ? slimMessages(output) : [],
  };
}
