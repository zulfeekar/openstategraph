import { describe, expect, it } from 'vitest';
import {
  OPENED_AT_KEY,
  OPENED_AT_LIMIT,
  readOpenedStamps,
  recordOpened,
  type StampStore,
} from './lastOpened';

/**
 * `install-experience` 28 — the half of "most recently opened or edited" that
 * only this browser knows.
 *
 * `savedAt` is on disk and shared. *Opened* is not a fact about the project at
 * all, it is a fact about this person's browser, so it is stored the way every
 * other browser-local answer in this codebase is: one namespaced key, an
 * injectable store so the decision tests without a DOM, and a failure that
 * costs an ordering rather than an arrival.
 */

function memory(initial: Record<string, string> = {}): StampStore & { seen: Map<string, string> } {
  const seen = new Map(Object.entries(initial));
  return {
    seen,
    getItem: (key) => seen.get(key) ?? null,
    setItem: (key, value) => void seen.set(key, value),
  };
}

const throwing: StampStore = {
  getItem() {
    throw new Error('storage is disabled in this context');
  },
  setItem() {
    throw new Error('storage is disabled in this context');
  },
};

describe('lastOpened', () => {
  it('remembers when a workflow was opened, under one namespaced key', () => {
    const store = memory();
    recordOpened('lens-qa', store, () => new Date('2026-08-31T10:00:00Z'));

    expect(readOpenedStamps(store)).toEqual({ 'lens-qa': '2026-08-31T10:00:00.000Z' });
    expect([...store.seen.keys()]).toEqual([OPENED_AT_KEY]);
  });

  it('moves a stamp forward when the same workflow is opened again', () => {
    const store = memory();
    recordOpened('lens-qa', store, () => new Date('2026-08-30T10:00:00Z'));
    recordOpened('lens-qa', store, () => new Date('2026-08-31T10:00:00Z'));

    expect(readOpenedStamps(store)['lens-qa']).toBe('2026-08-31T10:00:00.000Z');
  });

  it('reads nothing rather than throwing when the store is unavailable', () => {
    // A private window, a sandboxed frame, site data blocked. The arrival list
    // is then ordered by the disk clock alone, which is still an order.
    expect(readOpenedStamps(throwing)).toEqual({});
  });

  it('records nothing rather than throwing when the store refuses a write', () => {
    expect(() => recordOpened('lens-qa', throwing)).not.toThrow();
  });

  it('treats bytes it cannot parse as no stamps at all', () => {
    expect(readOpenedStamps(memory({ [OPENED_AT_KEY]: '{not json' }))).toEqual({});
    // Valid JSON of the wrong shape is the same answer: an array is not a map
    // of slugs, and half-reading one would order the list by nonsense.
    expect(readOpenedStamps(memory({ [OPENED_AT_KEY]: '["lens-qa"]' }))).toEqual({});
  });

  it('drops entries that are not a slug pointing at a string', () => {
    const store = memory({
      [OPENED_AT_KEY]: JSON.stringify({ good: '2026-08-31T10:00:00.000Z', bad: 17 }),
    });
    expect(readOpenedStamps(store)).toEqual({ good: '2026-08-31T10:00:00.000Z' });
  });

  it('keeps only the newest stamps, so one key cannot grow without bound', () => {
    // `localStorage` is ~5MB for the whole origin and `workflowStore` already
    // budgets against it. A stamp per package ever opened is small and
    // unbounded, which is the combination that eventually costs somebody a
    // save rather than a list.
    const store = memory();
    for (let index = 0; index < OPENED_AT_LIMIT + 10; index += 1) {
      recordOpened(
        `pkg-${String(index).padStart(3, '0')}`,
        store,
        () => new Date(Date.UTC(2026, 0, 1, 0, index)),
      );
    }

    const stamps = readOpenedStamps(store);
    expect(Object.keys(stamps)).toHaveLength(OPENED_AT_LIMIT);
    // The ones evicted are the oldest, never the newest.
    expect(stamps['pkg-000']).toBeUndefined();
    expect(stamps[`pkg-${String(OPENED_AT_LIMIT + 9).padStart(3, '0')}`]).toBeDefined();
  });

  it('is written by the one seam every open passes through', async () => {
    // `setOpenSlug` is called by the panel's load, by a save that mints a
    // slug, and by a deep link — and by nothing else. Recording the stamp at
    // each of those call sites instead would be three copies of one fact, and
    // the fourth caller would forget.
    const source = await import('node:fs').then(({ readFileSync }) =>
      readFileSync(new URL('./openWorkflow.ts', import.meta.url), 'utf8'),
    );
    expect(source).toContain('recordOpened');
  });
});
