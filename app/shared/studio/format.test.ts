import { describe, expect, test } from 'vitest';
import { duration, jsonValue, money, moneyDelta, num, numOrNull, pct, pyFixed0, toMs } from './format';

describe('numbers from the Statement Execution API', () => {
  test('strings, numbers, and blanks', () => {
    expect(num('18811018.0')).toBe(18811018);
    expect(num(7)).toBe(7);
    expect(numOrNull(null)).toBeNull();
    expect(numOrNull('')).toBeNull();
    expect(numOrNull('NaN')).toBeNull();
    expect(numOrNull('abc')).toBeNull();
    expect(num(undefined, -1)).toBe(-1);
  });
  test('toMs reads unix_millis strings', () => {
    expect(toMs('1793382515153')).toBe(1793382515153);
    expect(toMs(null)).toBeNull();
  });
  test('string numbers sort numerically once parsed', () => {
    expect(['10', '9', '100'].map(num).sort((a, b) => a - b)).toEqual([9, 10, 100]);
  });
});

describe('display', () => {
  test('money is compact and never NaN', () => {
    expect(money(18811018)).toBe('$18.81M');
    expect(money(28254)).toBe('$28.3K');
    expect(money(930)).toBe('$930');
    expect(money(null)).toBe('–');
    expect(moneyDelta(28254)).toBe('+$28.3K');
    expect(moneyDelta(-1200000)).toBe('-$1.20M');
    expect(moneyDelta(0.2)).toBe('±$0');
  });
  test('pct and duration', () => {
    expect(pct(0.9730906)).toBe('97.3%');
    expect(pct(null)).toBe('–');
    expect(duration(42_000)).toBe('42 s');
    expect(duration(185_000)).toBe('3 min 05 s');
    expect(duration(3_720_000)).toBe('1 h 02 min');
    expect(duration(null)).toBe('–');
  });
  test("pyFixed0 matches Python's f'{x:,.0f}' (round half to even)", () => {
    expect(pyFixed0(2810)).toBe('2,810');
    expect(pyFixed0(2.5)).toBe('2');
    expect(pyFixed0(3.5)).toBe('4');
    expect(pyFixed0(1234567.49)).toBe('1,234,567');
    expect(pyFixed0(-0.4)).toBe('0');
  });
});

test('booleans and nullable strings from the API', async () => {
  const { bool, strOrNull } = await import('./format');
  expect([bool('true'), bool(true), bool('false'), bool(null)]).toEqual([true, true, false, false]);
  expect([strOrNull(''), strOrNull(null), strOrNull('W1'), strOrNull(7)]).toEqual([null, null, 'W1', '7']);
});

test('JSON columns: AppKit decodes JSON-looking strings before the browser sees them, so accept both', () => {
  expect(jsonValue('[1,2]')).toEqual([1, 2]);
  expect(jsonValue([1, 2])).toEqual([1, 2]);
  expect(jsonValue({ a: 1 })).toEqual({ a: 1 });
  expect(jsonValue('{bad')).toBeNull();
  expect(jsonValue('')).toBeNull();
  expect(jsonValue(null)).toBeNull();
});
