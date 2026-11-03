import { describe, expect, test } from 'vitest';
import fixture from './parity/validation_cases.json';
import { parseOverrides } from './overrides';
import type { Issue, ScenarioInputs } from './types';
import { errorsOf, validateScenario } from './validate';

type Fixture = { inputs: Record<string, ScenarioInputs>; cases: Array<{ inputs: string; overrides: unknown; issues: Issue[] }> };
const data = fixture as Fixture;
const key = (i: Issue) => `${i.severity}|${i.rule}|${i.entity}|${i.detail}`;

describe('parity with cropplan.validate.validate', () => {
  test.each(data.cases.map((c) => [`${c.inputs} ${JSON.stringify(c.overrides)}`, c] as const))('%s', (_label, c) => {
    const got = validateScenario(data.inputs[c.inputs], parseOverrides(c.overrides));
    expect(got.map(key).sort()).toEqual(c.issues.map(key).sort());
  });
});

test('the grower-commitments scenario passes with only the capacity warning (demo step 4)', () => {
  const issues = validateScenario(data.inputs.commitments, parseOverrides({}));
  expect(errorsOf(issues)).toEqual([]);
  expect(issues.map((i) => i.rule)).toEqual(['capacity_below_fixed']);
});
