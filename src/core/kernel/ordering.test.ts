import { describe, expect, it } from 'vitest';
import { compareNatural, withSortedKeys } from '@core/kernel/ordering';

/**
 * Canonical ordering.
 *
 * These look like trivia, but they are the difference between a `workflow.json`
 * diff a reviewer can read and one they cannot. A lexical sort would be equally
 * *deterministic* while ordering `-10` before `-2` — passing a naive
 * determinism check and still producing a file that looks wrong to a human.
 */
describe('compareNatural', () => {
  const sorted = (ids: string[]) => [...ids].sort(compareNatural);

  it('orders numeric suffixes by value, not by digit', () => {
    expect(sorted(['node:agent-10', 'node:agent-2', 'node:agent-1'])).toEqual([
      'node:agent-1',
      'node:agent-2',
      'node:agent-10',
    ]);
  });

  it('groups by the text part before comparing numbers', () => {
    expect(sorted(['node:output-1', 'node:agent-2', 'node:agent-1'])).toEqual([
      'node:agent-1',
      'node:agent-2',
      'node:output-1',
    ]);
  });

  it('handles multi-digit runs in the middle of a string', () => {
    expect(sorted(['a-10-b', 'a-9-b'])).toEqual(['a-9-b', 'a-10-b']);
  });

  it('treats a prefix as smaller than the string extending it', () => {
    expect(sorted(['node:agent-1-inner', 'node:agent-1'])).toEqual([
      'node:agent-1',
      'node:agent-1-inner',
    ]);
  });

  it('is a total order — equal-value different-text ids never compare equal', () => {
    // "02" and "2" parse to the same number. Returning 0 would make the sort
    // unstable across engines, which is exactly the bug being avoided.
    expect(compareNatural('n-02', 'n-2')).not.toBe(0);
    expect(compareNatural('n-2', 'n-02')).toBe(-compareNatural('n-02', 'n-2'));
  });

  it('is symmetric and reflexive', () => {
    expect(compareNatural('node:agent-1', 'node:agent-1')).toBe(0);
    expect(compareNatural('a-1', 'a-2')).toBeLessThan(0);
    expect(compareNatural('a-2', 'a-1')).toBeGreaterThan(0);
  });

  it('does not reorder ids that only differ in case inconsistently', () => {
    const once = sorted(['B-1', 'a-1']);
    const twice = sorted(['a-1', 'B-1']);
    expect(once).toEqual(twice);
  });
});

describe('withSortedKeys', () => {
  it('emits keys in sorted order regardless of insertion order', () => {
    const built: Record<string, number> = {};
    built['zebra'] = 1;
    built['alpha'] = 2;

    expect(Object.keys(withSortedKeys(built))).toEqual(['alpha', 'zebra']);
  });

  it('preserves every value', () => {
    expect(withSortedKeys({ b: 2, a: 1 })).toEqual({ a: 1, b: 2 });
  });

  it('serialises identically for two records built in opposite orders', () => {
    const forward: Record<string, string> = {};
    forward['prompt'] = 'x';
    forward['model'] = 'y';
    const backward: Record<string, string> = {};
    backward['model'] = 'y';
    backward['prompt'] = 'x';

    // This is the whole point: `JSON.stringify` follows insertion order.
    expect(JSON.stringify(withSortedKeys(forward))).toBe(JSON.stringify(withSortedKeys(backward)));
  });

  it('tolerates an empty record', () => {
    expect(withSortedKeys({})).toEqual({});
  });
});
