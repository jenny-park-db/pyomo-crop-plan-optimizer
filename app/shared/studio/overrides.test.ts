import { describe, expect, test } from 'vitest';
import cases from './parity/overrides_cases.json';
import { OverridesError, parseOverrides, parseOverridesText, stableJson } from './overrides';

type Case = { payload: unknown; ok: boolean; overrides?: unknown; path?: string };

describe('parity with cropplan.overrides.parse_overrides', () => {
  test.each((cases as Case[]).map((c) => [JSON.stringify(c.payload), c] as const))('%s', (_label, c) => {
    if (c.ok) {
      expect(parseOverrides(c.payload)).toEqual(c.overrides);
    } else {
      let caught: unknown;
      try {
        parseOverrides(c.payload);
      } catch (e) {
        caught = e;
      }
      expect(caught).toBeInstanceOf(OverridesError);
      expect((caught as OverridesError).path).toBe(c.path);
    }
  });
});

describe('the "Edit as JSON" box', () => {
  test('malformed JSON is rejected with a readable message', () => {
    const r = parseOverridesText('{"diversity_cap": 0.45,}');
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.path).toBe('json');
      expect(r.error).toMatch(/^Overrides JSON is malformed: /);
    }
  });
  test('a string where a number belongs names the field', () => {
    expect(parseOverridesText('{"diversity_cap": "0.4"}')).toMatchObject({ ok: false, path: 'diversity_cap' });
  });
  test('a JSON array or number is not an overrides object', () => {
    expect(parseOverridesText('[1]')).toMatchObject({ ok: false, path: 'overrides' });
    expect(parseOverridesText('7')).toMatchObject({ ok: false, path: 'overrides' });
  });
  test('empty text means defaults', () => {
    expect(parseOverridesText('  ')).toMatchObject({ ok: true, overrides: { diversity_cap: 0.4 } });
  });
  test('stableJson sorts keys at every level', () => {
    expect(stableJson({ b: 1, a: { d: 1, c: 2 } })).toBe('{"a":{"c":2,"d":1},"b":1}');
  });
});
