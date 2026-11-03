import { describe, expect, test } from 'vitest';
import type { SlimMessage } from '../../../server/studio/agentProxy';
import { ApiError } from '../studio/api';
import type { TurnState } from '../../../server/studio/agentProxy';
import { AGENT_SAMPLES, elapsedSeconds, GIVE_UP_MS, linkScenarios, nextPollStep, POLL_RETRIES, pollRetryable, textOf, toolCards, turnReply } from './agentModel';

const SOLVE_RESULT = {
  run_id: 'agent-20261102101500-abcdef', scenario_id: 'ia-w1-half-abcdef', status: 'done',
  kpis: { gross_margin: 18512345.5 }, delta_vs_base: { gross_margin: -297654.5 },
  base: { scenario_id: 'baseline-2027', run_id: 'run-1', kpis: { gross_margin: 18810000 } },
};
const GENIE_RESULT = {
  status: 'COMPLETED', deep_link: 'https://my-workspace.cloud.databricks.com/genie/spaces/x/conversations/y',
  attachments: [{ attachment_id: 'a1', query: { description: 'Hybrids at the limit', query: 'SELECT hybrid_id FROM seed_utilization' } }],
};

const TURN: SlimMessage[] = [
  { type: 'ai', content: '', tool_calls: [
    { id: 't1', name: 'solve_scenario', args: { name: 'IA W1 half', assumptions: 'half of IA W1 lost to rain' } },
    { id: 't2', name: 'genie_agent_ask', args: { question: 'Which hybrids hit their limit?' } }] },
  { type: 'tool', name: 'solve_scenario', tool_call_id: 't1', status: 'success', content: JSON.stringify(SOLVE_RESULT) },
  { type: 'tool', name: 'genie_agent_ask', tool_call_id: 't2', status: 'success', content: JSON.stringify(GENIE_RESULT) },
  { type: 'ai', content: [{ type: 'text', text: 'Scenario ia-w1-half-abcdef earns $18.51M, ' }, { type: 'text', text: '$297.7K less than baseline-2027.' }], tool_calls: [] },
];

describe('agent transcript', () => {
  test('the reply is the last AI message, text blocks joined', () => {
    expect(turnReply(TURN)).toBe('Scenario ia-w1-half-abcdef earns $18.51M, $297.7K less than baseline-2027.');
    expect(textOf('plain')).toBe('plain');
    expect(textOf([{ type: 'tool_use', id: 'x' }])).toBe('');
  });

  test('every tool call becomes a card with its parsed result, scenario link, and Genie SQL', () => {
    const [solve, genie] = toolCards(TURN);
    expect(solve).toMatchObject({ id: 't1', name: 'solve_scenario', label: 'Solved a what-if', state: 'done',
      scenarioId: 'ia-w1-half-abcdef', sql: null, assumptions: 'half of IA W1 lost to rain' });
    expect(genie).toMatchObject({ name: 'genie_agent_ask', label: 'Asked Genie', state: 'done',
      sql: 'SELECT hybrid_id FROM seed_utilization', sqlTitle: 'Hybrids at the limit', link: GENIE_RESULT.deep_link });
  });

  test('a rejected, failed, or unanswered tool call is shown as such, not as success', () => {
    const cards = toolCards([
      { type: 'ai', content: '', tool_calls: [{ id: 'a', name: 'solve_scenario', args: {} }, { id: 'b', name: 'get_stress_test', args: {} },
        { id: 'c', name: 'stress_test_plan', args: {} }] },
      { type: 'tool', name: 'solve_scenario', tool_call_id: 'a', status: 'success', content: '{"status":"rejected","error":"diversity_cap must be a finite number"}' },
      { type: 'tool', name: 'get_stress_test', tool_call_id: 'b', status: 'error', content: 'Error: boom' },
    ]);
    expect(cards.map((c) => [c.state, c.detail])).toEqual([
      ['rejected', 'diversity_cap must be a finite number'], ['error', 'Error: boom'], ['pending', null]]);
  });

  test('a solve that timed out says it is still running', () => {
    const [card] = toolCards([
      { type: 'ai', content: '', tool_calls: [{ id: 'a', name: 'solve_scenario', args: {} }] },
      { type: 'tool', name: 'solve_scenario', tool_call_id: 'a', status: 'success',
        content: '{"status":"solving","timed_out":true,"scenario_id":"s-1","message":"Still solving after 240 s"}' },
    ]);
    expect([card.state, card.scenarioId, card.detail]).toEqual(['running', 's-1', 'Still solving after 240 s']);
  });

  test('scenario IDs the turn knows about become Results links; other words stay text', () => {
    expect(linkScenarios('Open ia-w1-half-abcdef or baseline-2027, not baseline-2026.', ['ia-w1-half-abcdef', 'baseline-2027']))
      .toEqual([{ text: 'Open ' }, { text: 'ia-w1-half-abcdef', scenarioId: 'ia-w1-half-abcdef' }, { text: ' or ' },
        { text: 'baseline-2027', scenarioId: 'baseline-2027' }, { text: ', not baseline-2026.' }]);
    expect(linkScenarios('nothing here', [])).toEqual([{ text: 'nothing here' }]);
  });

  test('the sample prompts are the spec demo questions', () => {
    expect(AGENT_SAMPLES[0]).toBe('What if Iowa loses half its W1 planting capacity to rain?');
    expect(AGENT_SAMPLES[1]).toBe("Across today's scenarios, which hybrids always hit their supply limit?");
  });

  test('a solve whose job failed is an error card, and an infeasible one says so', () => {
    const cards = toolCards([
      { type: 'ai', content: '', tool_calls: [{ id: 'a', name: 'solve_scenario', args: {} }, { id: 'b', name: 'solve_scenario', args: {} },
        { id: 'c', name: 'solve_scenario', args: {} }] },
      { type: 'tool', name: 'solve_scenario', tool_call_id: 'a', status: 'success', content: '{"status":"failed","error":"ImportError: no module cropplan"}' },
      { type: 'tool', name: 'solve_scenario', tool_call_id: 'b', status: 'success',
        content: '{"status":"infeasible","infeasibility_reason":"Planting capacity IA/W1 short by 290 acres"}' },
      { type: 'tool', name: 'solve_scenario', tool_call_id: 'c', status: 'success', content: '{"status":"unknown","message":"check Runs"}' },
    ]);
    expect(cards.map((c) => [c.state, c.detail])).toEqual([
      ['error', 'ImportError: no module cropplan'], ['done', 'Planting capacity IA/W1 short by 290 acres'], ['running', 'check Runs']]);
  });

  test('only server and network failures of a poll are retried', () => {
    expect(pollRetryable(new ApiError(502, 'bad gateway', null))).toBe(true);
    expect(pollRetryable(new TypeError('Failed to fetch'))).toBe(true);
    expect(pollRetryable(new ApiError(403, 'no permission', null))).toBe(false);
    expect(pollRetryable(new ApiError(400, 'bad id', null))).toBe(false);
  });
});


describe('agent turn polling', () => {
  const START = 1_000_000;
  const state = (status: TurnState['status'], messages: SlimMessage[] = []): { state: TurnState } =>
    ({ state: { id: 'turn-1', status, error: null, messages } });
  const bad = (status: number) => ({ error: new ApiError(status, `HTTP ${status}`, null) });

  test('three 502s in a row are retried, then a completed turn finishes', () => {
    let failures = 0;
    for (let i = 1; i <= POLL_RETRIES; i++) {
      const step = nextPollStep(bad(502), failures, START, START + 1000);
      expect(step).toEqual({ kind: 'again', failures: i });
      failures = i;
    }
    expect(nextPollStep(state('completed', TURN), failures, START, START + 5000)).toEqual({ kind: 'done', bump: true });
  });
  test('a fourth consecutive 502 shows the error', () => {
    expect(nextPollStep(bad(502), POLL_RETRIES, START, START + 1000)).toEqual({ kind: 'error', message: 'HTTP 502' });
  });
  test('a 4xx is not retried', () => {
    expect(nextPollStep(bad(403), 0, START, START + 1000)).toEqual({ kind: 'error', message: 'HTTP 403' });
  });
  test('a network error (no HTTP status) is retried', () => {
    expect(nextPollStep({ error: new TypeError('fetch failed') }, 0, START, START + 1000)).toEqual({ kind: 'again', failures: 1 });
  });
  test('a successful poll resets the failure count', () => {
    expect(nextPollStep(state('active'), 2, START, START + 1000)).toEqual({ kind: 'again', failures: 0 });
  });
  test('a turn still running after ten minutes gives up with guidance', () => {
    const step = nextPollStep(state('active'), 0, START, START + GIVE_UP_MS + 1);
    expect(step).toMatchObject({ kind: 'error' });
    expect(step.kind === 'error' && step.message).toMatch(/10 minutes/);
    expect(nextPollStep(state('active'), 0, START, START + GIVE_UP_MS)).toEqual({ kind: 'again', failures: 0 });
  });
  test('completed turns bump the Studio data only when a tool created a scenario; failed turns just stop', () => {
    const noScenario: SlimMessage[] = [{ type: 'ai', content: 'Off topic.', tool_calls: [] }];
    expect(nextPollStep(state('completed', noScenario), 0, START, START)).toEqual({ kind: 'done', bump: false });
    expect(nextPollStep(state('failed'), 0, START, START)).toEqual({ kind: 'stop' });
  });
});

describe('working timer', () => {
  test('never shows negative seconds when the clock tick is older than the turn', () => {
    expect(elapsedSeconds(1_000, 13_000)).toBe(0);
    expect(elapsedSeconds(13_400, 1_000)).toBe(12);
  });
});
