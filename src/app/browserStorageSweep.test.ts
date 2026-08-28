import { describe, expect, it } from 'vitest';
import {
  CORRUPT_SNAPSHOT_CAP,
  DAY_MS,
  ORPHAN_TTL_MS,
  decideStorageSweep,
  readStorageEntries,
  sweepBrowserStorage,
  type StoredEntry,
} from '@app/browserStorageSweep';
import { CLAIM_STALE_MS, type KeyValueStore } from '@app/workflowStore';

const NOW = Date.parse('2026-08-28T12:00:00.000Z');
const iso = (msAgo: number): string => new Date(NOW - msAgo).toISOString();

const draft = (slug: string, msAgo: number): StoredEntry => ({
  key: `openstategraph-workflow-slug-${slug}`,
  savedAt: iso(msAgo),
  claimedAtMs: null,
  bytes: 900,
});
const scratch = (id: string, msAgo: number): StoredEntry => ({
  key: `openstategraph-workflow-${id}`,
  savedAt: iso(msAgo),
  claimedAtMs: null,
  bytes: 900,
});
const corrupt = (id: string, msAgo: number): StoredEntry => ({
  key: `openstategraph-corrupt-workflow-${id}-${NOW - msAgo}`,
  savedAt: null,
  claimedAtMs: null,
  bytes: 700,
});
const claim = (draftId: string, msAgo: number): StoredEntry => ({
  key: `openstategraph-claim-${draftId}`,
  savedAt: null,
  claimedAtMs: NOW - msAgo,
  bytes: 60,
});

const plan = (entries: readonly StoredEntry[], knownSlugs: readonly string[] | null) =>
  decideStorageSweep(entries, { nowMs: NOW, knownSlugs: knownSlugs && new Set(knownSlugs) });

/**
 * `launch-readiness/96` — nothing ever shrank. Three families grew forever and
 * the only reader of any of them was a quota error with the wrong sentence.
 *
 * The tests are written around the ticket's own hesitation: *"it may be the
 * only copy of someone's work"*. Every rule here therefore has a matching test
 * for the case where it must **not** fire.
 */
describe('bounded browser-storage sweep', () => {
  describe('orphaned drafts', () => {
    it('retires a draft whose slug the backend no longer holds, once it is old', () => {
      const entries = [draft('gone', ORPHAN_TTL_MS + DAY_MS)];
      expect(plan(entries, ['chinook-assistant']).drop).toEqual([entries[0]!.key]);
    });

    it('keeps an orphaned draft that is still young — the delete may be a mistake', () => {
      const entries = [draft('gone', DAY_MS)];
      expect(plan(entries, ['chinook-assistant']).drop).toEqual([]);
    });

    it('keeps an old draft whose workflow still exists — that is unsaved work', () => {
      const entries = [draft('chinook-assistant', ORPHAN_TTL_MS * 4)];
      expect(plan(entries, ['chinook-assistant']).drop).toEqual([]);
    });

    it('keeps everything when the backend could not be asked', () => {
      const entries = [draft('gone', ORPHAN_TTL_MS * 4)];
      expect(plan(entries, null).drop).toEqual([]);
    });

    it('keeps an old orphan a live tab is still editing', () => {
      const entries = [draft('gone', ORPHAN_TTL_MS * 4), claim('slug-gone', CLAIM_STALE_MS / 2)];
      expect(plan(entries, ['chinook-assistant']).drop).toEqual([]);
    });

    it('keeps a draft whose age cannot be told', () => {
      const entries: StoredEntry[] = [
        { key: 'openstategraph-workflow-slug-gone', savedAt: null, claimedAtMs: null, bytes: 900 },
      ];
      expect(plan(entries, ['chinook-assistant']).drop).toEqual([]);
    });
  });

  describe('never-saved scratch drafts', () => {
    it('retires a wf-<timestamp> draft nobody has touched in a long time', () => {
      const entries = [scratch('wf-1', ORPHAN_TTL_MS + DAY_MS)];
      expect(plan(entries, ['chinook-assistant']).drop).toEqual([entries[0]!.key]);
    });

    it('keeps one a live tab is editing, however old', () => {
      const entries = [scratch('wf-1', ORPHAN_TTL_MS * 4), claim('wf-1', CLAIM_STALE_MS / 2)];
      expect(plan(entries, ['chinook-assistant']).drop).toEqual([]);
    });

    it('retires it even when the backend could not be asked — it has no slug to orphan', () => {
      const entries = [scratch('wf-1', ORPHAN_TTL_MS + DAY_MS)];
      expect(plan(entries, null).drop).toEqual([entries[0]!.key]);
    });
  });

  describe('corrupt snapshots', () => {
    it('retires one older than the window', () => {
      const entries = [corrupt('slug-a', ORPHAN_TTL_MS + DAY_MS)];
      expect(plan(entries, []).drop).toEqual([entries[0]!.key]);
    });

    it('caps how many recent ones are kept, newest first', () => {
      const entries = Array.from({ length: CORRUPT_SNAPSHOT_CAP + 3 }, (_, i) =>
        corrupt(`slug-${i}`, (i + 1) * 1000),
      );
      const dropped = plan(entries, []).drop;
      expect(dropped).toHaveLength(3);
      // The three oldest of the recent ones.
      expect(dropped).toEqual(entries.slice(CORRUPT_SNAPSHOT_CAP).map((e) => e.key));
    });

    it('keeps a recent one under the cap', () => {
      expect(plan([corrupt('slug-a', DAY_MS)], []).drop).toEqual([]);
    });
  });

  describe('claims', () => {
    it('removes a claim past its staleness window — it is already ignored', () => {
      const entries = [claim('slug-a', CLAIM_STALE_MS * 10)];
      expect(plan(entries, ['a']).drop).toEqual([entries[0]!.key]);
    });

    it('leaves a live claim alone', () => {
      expect(plan([claim('slug-a', 1000)], ['a']).drop).toEqual([]);
    });
  });

  it('reports what it is holding, so the panel can say it', () => {
    const report = plan(
      [draft('chinook-assistant', DAY_MS), corrupt('slug-a', DAY_MS), claim('slug-a', 1000)],
      ['chinook-assistant'],
    );
    expect(report.bytesHeld).toBeGreaterThan(0);
    expect(report.draftsHeld).toBe(1);
    expect(report.corruptHeld).toBe(1);
  });

  it('touches nothing outside the three families', () => {
    const entries: StoredEntry[] = [
      { key: 'openstategraph-theme', savedAt: null, claimedAtMs: null, bytes: 10 },
      { key: 'unrelated-app-key', savedAt: null, claimedAtMs: null, bytes: 10 },
    ];
    expect(plan(entries, []).drop).toEqual([]);
  });
});

/** An in-memory `Storage`, as everywhere else in `app/`. */
class FakeStore implements KeyValueStore {
  readonly map = new Map<string, string>();
  get length(): number {
    return this.map.size;
  }
  key(index: number): string | null {
    return [...this.map.keys()][index] ?? null;
  }
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
}

describe('the sweep against a real store', () => {
  it('reads envelopes and claims back out of storage, and removes what it planned', () => {
    const store = new FakeStore();
    store.setItem(
      'openstategraph-workflow-slug-gone',
      JSON.stringify({ version: 2, savedAt: iso(ORPHAN_TTL_MS + DAY_MS), workflow: {} }),
    );
    store.setItem(
      'openstategraph-workflow-slug-kept',
      JSON.stringify({ version: 2, savedAt: iso(DAY_MS), workflow: {} }),
    );
    store.setItem(`openstategraph-corrupt-workflow-x-${NOW - ORPHAN_TTL_MS - DAY_MS}`, '{oops');
    store.setItem(
      'openstategraph-claim-slug-kept',
      JSON.stringify({ writerId: 'w-1', at: NOW - CLAIM_STALE_MS * 10 }),
    );

    const entries = readStorageEntries(store);
    expect(entries.find((e) => e.key === 'openstategraph-workflow-slug-kept')?.savedAt).not.toBe(
      null,
    );
    expect(entries.find((e) => e.key === 'openstategraph-claim-slug-kept')?.claimedAtMs).toBe(
      NOW - CLAIM_STALE_MS * 10,
    );

    const report = sweepBrowserStorage(store, { nowMs: NOW, knownSlugs: new Set(['kept']) });

    expect(report.drop).toHaveLength(3);
    expect(store.getItem('openstategraph-workflow-slug-kept')).not.toBe(null);
    expect(store.getItem('openstategraph-workflow-slug-gone')).toBe(null);
  });

  it('is a no-op on a store that throws, rather than stopping the panel', () => {
    const throwing: KeyValueStore = {
      length: 1,
      key: () => {
        throw new Error('denied');
      },
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
      removeItem: () => {
        throw new Error('denied');
      },
    };
    expect(() =>
      sweepBrowserStorage(throwing, { nowMs: NOW, knownSlugs: new Set() }),
    ).not.toThrow();
  });
});
