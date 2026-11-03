import { describe, expect, test } from 'vitest';
import type { GenieMessageItem } from '@databricks/appkit-ui/react';
import { isEmptyAnswer, lastSql, statusLabel } from './genieModel';

const msg = (over: Partial<GenieMessageItem>): GenieMessageItem => ({
  id: 'm', role: 'assistant', content: '', status: 'COMPLETED', attachments: [], queryResults: new Map(), ...over,
});

describe('genieModel', () => {
  test('lastSql finds the newest assistant query', () => {
    const messages = [
      msg({ id: '1', attachments: [{ attachmentId: 'a', query: { title: 'Old', query: 'SELECT 1' } }] }),
      msg({ id: '2', role: 'user', content: 'next?' }),
      msg({ id: '3', attachments: [{ attachmentId: 'b', text: { content: 'hi' } }, { attachmentId: 'c', query: { query: 'SELECT 2', description: 'why' } }] }),
    ];
    expect(lastSql(messages)).toEqual({ title: 'Generated SQL', description: 'why', query: 'SELECT 2' });
    expect(lastSql([msg({ role: 'user' })])).toBeNull();
  });
  test('statusLabel reflects streaming progress and is silent when idle', () => {
    expect(statusLabel('idle', [])).toBeNull();
    expect(statusLabel('streaming', [msg({ status: 'EXECUTING_QUERY' })])).toBe('Running the generated SQL on the warehouse…');
    expect(statusLabel('streaming', [msg({ status: 'ASKING_AI' })])).toBe('Writing SQL for your question…');
    expect(statusLabel('streaming', [])).toBe('Working on it…');
    expect(statusLabel('loading-history', [])).toBe('Loading the conversation…');
  });
  test('an answer with no text and no SQL is flagged', () => {
    expect(isEmptyAnswer(msg({}))).toBe(true);
    expect(isEmptyAnswer(msg({ content: 'Four hybrids.' }))).toBe(false);
    expect(isEmptyAnswer(msg({ status: 'EXECUTING_QUERY' }))).toBe(false);
  });
});
