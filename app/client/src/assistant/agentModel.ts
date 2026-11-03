/**
 * Pure helpers for the Agent tab (spec §6.5): the reply text, one card per tool call (with its result, the
 * scenario it created, and Genie's SQL), and scenario IDs in the reply turned into links to Results.
 * Input is the slim LangGraph message list GET /api/studio/agent/turns/:id returns.
 */
import type { SlimMessage, TurnState } from '../../../server/studio/agentProxy';
import { SEEDED_SCENARIOS } from '../../../shared/studio/types';
import { ApiError } from '../studio/api';

export type CardState = 'pending' | 'running' | 'done' | 'rejected' | 'error';

export interface ToolCard {
  id: string;
  name: string;
  label: string;
  args: Record<string, unknown>;
  state: CardState;
  /** One line for the card: the rejection or error text, the timeout message, or the run status. */
  detail: string | null;
  result: Record<string, unknown> | null;
  scenarioId: string | null;
  assumptions: string | null;
  sql: string | null;
  sqlTitle: string | null;
  link: string | null;
}

const LABELS: Record<string, string> = {
  solve_scenario: 'Solved a what-if',
  stress_test_plan: 'Started a stress test',
  get_stress_test: 'Read a stress test',
  genie_agent_ask: 'Asked Genie',
  genie_agent_poll: 'Waited for Genie',
  genie_agent_query_result: 'Read Genie’s result rows',
};

export const AGENT_SAMPLES = [
  'What if Iowa loses half its W1 planting capacity to rain?',
  "Across today's scenarios, which hybrids always hit their supply limit?",
  'How robust is revision-1-2027? Show its stored stress test.',
];

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown, fallback: string): string => (typeof v === 'string' ? v : fallback);

/** LangGraph content is a string or a list of blocks; keep the text blocks. */
export function textOf(content: unknown): string {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content.filter(isRecord).filter((b) => b.type === 'text' && typeof b.text === 'string').map((b) => String(b.text)).join('');
}

export function turnReply(messages: SlimMessage[]): string {
  const last = [...messages].reverse().find((m) => m.type === 'ai' && textOf(m.content).trim());
  return last ? textOf(last.content).trim() : '';
}

function parse(content: unknown): Record<string, unknown> | null {
  const text = textOf(content);
  try {
    const v = JSON.parse(text) as unknown;
    return isRecord(v) ? v : null;
  } catch {
    return null;
  }
}

function genieSql(result: Record<string, unknown> | null): { sql: string | null; title: string | null } {
  const attachments = Array.isArray(result?.attachments) ? result.attachments.filter(isRecord) : [];
  for (const a of attachments) {
    const q = isRecord(a.query) ? a.query : null;
    if (q && typeof q.query === 'string') return { sql: q.query, title: typeof q.description === 'string' ? q.description : null };
  }
  return { sql: null, title: null };
}

function stateOf(status: string | undefined, result: Record<string, unknown> | null, raw: string): { state: CardState; detail: string | null } {
  if (status === 'error') return { state: 'error', detail: raw.slice(0, 300) };
  if (result?.status === 'rejected') return { state: 'rejected', detail: str(result.error, 'rejected') };
  if (result?.timed_out === true || result?.state === 'running' || result?.status === 'unknown') {
    return { state: 'running', detail: str(result.message, 'still running') };
  }
  if (result?.state === 'failed') return { state: 'error', detail: str(result.message, 'failed') };
  // A solve whose job died: its report says failed with the job's error.
  if (result?.status === 'failed') return { state: 'error', detail: str(result.error, 'The solve failed.') };
  if (result?.status === 'infeasible' || result?.status === 'invalid') {
    return { state: 'done', detail: str(result.infeasibility_reason, str(result.error, result.status)) };
  }
  return { state: 'done', detail: null };
}

/** A poll that failed on the server or the network is worth retrying; a 4xx (bad id, no permission) is final. */
export function pollRetryable(e: unknown): boolean {
  return e instanceof ApiError ? e.status >= 500 : true;
}

/** Seconds since the turn started for the "Working…" line; 0 while the clock tick predates the turn. */
export function elapsedSeconds(now: number, startedAt: number): number {
  return Math.max(0, Math.round((now - startedAt) / 1000));
}

export const POLL_RETRIES = 3; // consecutive server/network failures tolerated before the turn shows the error
export const GIVE_UP_MS = 10 * 60_000; // a turn waits at most 240 s per solve; ten minutes means something is stuck

export type PollStep =
  | { kind: 'again'; failures: number }
  | { kind: 'done'; bump: boolean }
  | { kind: 'stop' }
  | { kind: 'error'; message: string };

/** What the Agent tab does after one poll: poll again (with the running failure count), finish, or show an error. */
export function nextPollStep(outcome: { state: TurnState } | { error: unknown }, failures: number,
                             startedAt: number, now: number): PollStep {
  if ('error' in outcome) {
    // The agent keeps working through a proxy blip; only give up after a few failures in a row or a 4xx.
    if (pollRetryable(outcome.error) && failures < POLL_RETRIES) return { kind: 'again', failures: failures + 1 };
    const e = outcome.error;
    return { kind: 'error', message: e instanceof Error ? e.message : String(e) };
  }
  const { state } = outcome;
  if (state.status === 'completed') return { kind: 'done', bump: toolCards(state.messages).some((c) => c.scenarioId) };
  if (state.status === 'failed') return { kind: 'stop' };
  if (now - startedAt > GIVE_UP_MS) {
    return { kind: 'error', message: 'The agent has not answered in 10 minutes. Check the Runs screen, then start a new conversation.' };
  }
  return { kind: 'again', failures: 0 };
}

export function toolCards(messages: SlimMessage[]): ToolCard[] {
  const results = new Map(messages.filter((m) => m.type === 'tool').map((m) => [m.tool_call_id, m]));
  return messages.filter((m) => m.type === 'ai').flatMap((m) => m.tool_calls ?? []).map((call) => {
    const msg = results.get(call.id);
    const result = msg ? parse(msg.content) : null;
    const { state, detail } = msg ? stateOf(msg.status, result, textOf(msg.content)) : { state: 'pending' as const, detail: null };
    const { sql, title } = genieSql(result);
    const scenarioId = typeof result?.scenario_id === 'string' ? result.scenario_id : null;
    return {
      id: call.id, name: call.name, label: LABELS[call.name] ?? call.name, args: call.args, state, detail, result,
      scenarioId, assumptions: typeof call.args.assumptions === 'string' && call.args.assumptions ? call.args.assumptions : null,
      sql, sqlTitle: title, link: typeof result?.deep_link === 'string' ? result.deep_link : null,
    };
  });
}

/** Scenario IDs a turn can link: those its tools returned plus the seeded ones. */
export function knownScenarios(cards: ToolCard[]): string[] {
  const ids = new Set<string>(SEEDED_SCENARIOS);
  for (const c of cards) {
    if (c.scenarioId) ids.add(c.scenarioId);
    const base = isRecord(c.result?.base) ? c.result.base.scenario_id : null;
    if (typeof base === 'string') ids.add(base);
  }
  return [...ids];
}

export function linkScenarios(text: string, ids: string[]): Array<{ text: string; scenarioId?: string }> {
  if (!ids.length) return [{ text }];
  const escaped = [...ids].sort((a, b) => b.length - a.length).map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp(`(?<![A-Za-z0-9._-])(${escaped.join('|')})(?![A-Za-z0-9_-])`, 'g');
  const out: Array<{ text: string; scenarioId?: string }> = [];
  let at = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > at) out.push({ text: text.slice(at, m.index) });
    out.push({ text: m[0], scenarioId: m[0] });
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}
