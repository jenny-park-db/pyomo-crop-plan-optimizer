/** Pure helpers for the Genie panel's trust surface (generated SQL, status text, empty answers). */
import type { GenieChatStatus, GenieMessageItem } from '@databricks/appkit-ui/react';

export interface SqlAttachment {
  title: string;
  description: string | null;
  query: string;
}

/** The generated SQL of the newest assistant answer that has one. */
export function lastSql(messages: GenieMessageItem[]): SqlAttachment | null {
  for (const m of [...messages].reverse()) {
    if (m.role !== 'assistant') continue;
    for (const a of m.attachments ?? []) {
      if (a.query?.query) return { title: a.query.title ?? 'Generated SQL', description: a.query.description ?? null, query: a.query.query };
    }
  }
  return null;
}

/** Plain-language status for useGenieChat().status plus the newest message's Genie status. */
export function statusLabel(status: GenieChatStatus, messages: GenieMessageItem[]): string | null {
  if (status === 'loading-history' || status === 'loading-older') return 'Loading the conversation…';
  if (status !== 'streaming') return null;
  const latest = [...messages].reverse().find((m) => m.role === 'assistant');
  switch (latest?.status) {
    case 'FETCHING_METADATA': return 'Reading the table definitions…';
    case 'EXECUTING_QUERY': return 'Running the generated SQL on the warehouse…';
    case 'ASKING_AI':
    case 'PENDING_WAREHOUSE':
    case 'FILTERING_CONTEXT':
      return 'Writing SQL for your question…';
    default: return 'Working on it…';
  }
}

/** An assistant answer with neither text nor a query: say so instead of rendering an empty bubble. */
export function isEmptyAnswer(m: GenieMessageItem): boolean {
  return m.role === 'assistant' && m.status === 'COMPLETED' && !m.content?.trim()
    && !(m.attachments ?? []).some((a) => a.query?.query || a.text?.content);
}

export const SAMPLE_QUESTIONS = [
  "Across today's scenarios, which hybrids always hit their supply limit?",
  'Compare gross margin, net margin, and planted % across scenarios',
  'Why is the 2027 Grower Commitments scenario infeasible?',
];
