import { describe, expect, test } from 'vitest';
import { pollTurn, slimMessages, startTurn, type AgentFetch } from './agentProxy';

const AGENT = 'https://agent-bricks-crop-plan-agent-1.aws.databricksapps.com';
const SID = '6f1c1e0e-4b8e-4e0f-9a51-3d2f5f1d2a10';
const ID = '29b7f429-058e-4913-b04b-182d5e179a62';

function fakeFetch(status: number, body: unknown) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const f: AgentFetch = async (url, init) => {
    calls.push({ url, init });
    return { ok: status < 400, status, text: async () => (typeof body === 'string' ? body : JSON.stringify(body)) };
  };
  return { f, calls };
}

describe('startTurn', () => {
  test('forwards the user message as a background invocation with the signed-in user token', async () => {
    const { f, calls } = fakeFetch(202, { id: ID, status: 'queued', status_url: `/api/invocations/${ID}` });
    const r = await startTurn({ agentUrl: AGENT, fetch: f, newId: () => ID }, 'user-token', { session_id: SID, message: '  What if IA W1 halves?  ' });
    expect(r).toEqual({ id: ID, status: 'queued' });
    expect(calls[0].url).toBe(`${AGENT}/api/invocations`);
    expect(calls[0].init.method).toBe('POST');
    expect(calls[0].init.headers).toEqual({ Authorization: 'Bearer user-token', 'Content-Type': 'application/json', 'X-Routing-Key': SID });
    expect(JSON.parse(calls[0].init.body as string)).toEqual({
      id: ID, session_id: SID, background: true, input: { messages: [{ role: 'user', content: 'What if IA W1 halves?' }] } });
  });

  test.each([
    [{ session_id: SID, message: '' }, 'message'],
    [{ session_id: SID, message: 'x'.repeat(4001) }, 'message'],
    [{ session_id: 'not a uuid', message: 'hi' }, 'session_id'],
  ])('a bad request is a 400 naming %s and calls nothing', async (body, path) => {
    const { f, calls } = fakeFetch(202, {});
    await expect(startTurn({ agentUrl: AGENT, fetch: f }, 'tok', body)).rejects.toMatchObject({ status: 400, path });
    expect(calls).toEqual([]);
  });

  test('no agent configured is a 503; no user token is a 401', async () => {
    const { f } = fakeFetch(202, {});
    await expect(startTurn({ agentUrl: null, fetch: f }, 'tok', { session_id: SID, message: 'hi' })).rejects.toMatchObject({ status: 503 });
    await expect(startTurn({ agentUrl: AGENT, fetch: f }, undefined, { session_id: SID, message: 'hi' })).rejects.toMatchObject({ status: 401 });
  });

  test('the agent refusing the user (no CAN_USE) is a 403 that says so', async () => {
    const { f } = fakeFetch(403, 'Forbidden');
    const p = startTurn({ agentUrl: AGENT, fetch: f }, 'tok', { session_id: SID, message: 'hi' });
    await expect(p).rejects.toMatchObject({ status: 403 });
    await expect(p).rejects.toThrow(/permission to use the planning agent/);
  });
});

test('a redirect to sign-in (no CAN_USE) is the same permission message, and redirects are not followed', async () => {
  const { f, calls } = fakeFetch(302, '<html>login</html>');
  const p = startTurn({ agentUrl: AGENT, fetch: f }, 'tok', { session_id: SID, message: 'hi' });
  await expect(p).rejects.toMatchObject({ status: 403 });
  await expect(p).rejects.toThrow(/permission to use the planning agent/);
  expect(calls[0].init.redirect).toBe('manual');
});

describe('pollTurn', () => {
  test('a completed turn returns slim messages', async () => {
    const { f, calls } = fakeFetch(200, { id: ID, status: 'completed', output: { status: 'completed', output: [
      { type: 'ai', content: '', tool_calls: [{ id: 't1', name: 'solve_scenario', args: { name: 'x' }, type: 'tool_call' }], usage_metadata: { input_tokens: 9 } },
      { type: 'tool', name: 'solve_scenario', tool_call_id: 't1', status: 'success', content: '{"run_id":"agent-1"}' },
      { type: 'ai', content: 'Done.', tool_calls: [] },
    ] } });
    expect(await pollTurn({ agentUrl: AGENT, fetch: f }, 'tok', ID)).toEqual({ id: ID, status: 'completed', error: null, messages: [
      { type: 'ai', content: '', tool_calls: [{ id: 't1', name: 'solve_scenario', args: { name: 'x' } }] },
      { type: 'tool', content: '{"run_id":"agent-1"}', name: 'solve_scenario', tool_call_id: 't1', status: 'success' },
      { type: 'ai', content: 'Done.', tool_calls: [] },
    ] });
    expect(calls[0]).toMatchObject({ url: `${AGENT}/api/invocations/${ID}`, init: { method: 'GET' } });
  });

  test('a running turn has no messages; a failed one carries its error text', async () => {
    expect(await pollTurn({ agentUrl: AGENT, fetch: fakeFetch(200, { id: ID, status: 'active' }).f }, 'tok', ID))
      .toEqual({ id: ID, status: 'active', error: null, messages: [] });
    expect(await pollTurn({ agentUrl: AGENT, fetch: fakeFetch(200, { id: ID, status: 'failed', error: { code: 'X', message: 'model overloaded' } }).f }, 'tok', ID))
      .toMatchObject({ status: 'failed', error: 'model overloaded' });
    expect(await pollTurn({ agentUrl: AGENT, fetch: fakeFetch(200, { id: ID, status: 'failed', error: 'agent invocation failed' }).f }, 'tok', ID))
      .toMatchObject({ status: 'failed', error: 'agent invocation failed' });
  });

  test('a malformed invocation id is a 400', async () => {
    await expect(pollTurn({ agentUrl: AGENT, fetch: fakeFetch(200, {}).f }, 'tok', '../../admin')).rejects.toMatchObject({ status: 400 });
  });
});

test('slimMessages drops token counts and provider metadata but keeps content blocks', () => {
  expect(slimMessages([{ type: 'ai', content: [{ type: 'text', text: 'hi' }], additional_kwargs: { x: 1 }, response_metadata: {} }, 'junk']))
    .toEqual([{ type: 'ai', content: [{ type: 'text', text: 'hi' }], tool_calls: [] }]);
});

describe('agent call timeout', () => {
  test('an agent that never answers is a 504 after the timeout, not a hung request', async () => {
    const hang: AgentFetch = (_url, init) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('The operation timed out.', 'TimeoutError')));
    });
    const start = startTurn({ agentUrl: AGENT, fetch: hang, timeoutMs: 20 }, 'tok', { session_id: SID, message: 'hi' });
    await expect(start).rejects.toMatchObject({ status: 504 });
    await expect(start).rejects.toThrow(/did not answer within/);
    await expect(pollTurn({ agentUrl: AGENT, fetch: hang, timeoutMs: 20 }, 'tok', ID)).rejects.toMatchObject({ status: 504 });
  });
  test('every call carries an abort signal (default 30 s)', async () => {
    const { f, calls } = fakeFetch(200, { id: ID, status: 'active' });
    await pollTurn({ agentUrl: AGENT, fetch: f }, 'tok', ID);
    expect(calls[0].init.signal).toBeInstanceOf(AbortSignal);
  });
});
