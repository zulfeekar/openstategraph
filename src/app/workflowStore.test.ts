import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import {
  claimSession,
  CLAIM_PREFIX,
  CORRUPT_PREFIX,
  deleteWorkflow,
  isClaimedByAnother,
  listWorkflows,
  MAX_PAYLOAD_BYTES,
  mostRecentWorkflowId,
  newWriteGuard,
  readWorkflow,
  resolveSession,
  saveWorkflow,
  STORAGE_PREFIX,
  type KeyValueStore,
  type WriteGuard,
} from '@app/workflowStore';

/** An in-memory `Storage`, so this runs in the node environment like `core/`. */
class FakeStore implements KeyValueStore {
  private readonly map = new Map<string, string>();
  /** Set to simulate the ~5MB quota, the one failure that really happens. */
  full = false;
  /** Set to simulate storage being unavailable entirely (Safari private mode). */
  broken = false;

  get length(): number {
    return this.map.size;
  }
  key(index: number): string | null {
    return [...this.map.keys()][index] ?? null;
  }
  getItem(key: string): string | null {
    if (this.broken) throw new DOMException('storage is disabled', 'SecurityError');
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    if (this.broken) throw new DOMException('storage is disabled', 'SecurityError');
    if (this.full) throw new DOMException('quota exceeded', 'QuotaExceededError');
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    if (this.broken) throw new DOMException('storage is disabled', 'SecurityError');
    this.map.delete(key);
  }
  /** Test-only: plant a corrupt entry. */
  poison(key: string, value: string): void {
    this.map.set(key, value);
  }
  /** Test-only: every key currently held. */
  keys(): string[] {
    return [...this.map.keys()];
  }
}

/**
 * Browser-local workflow persistence.
 *
 * This layer shipped with **no tests at all**, in a repo whose CLAUDE.md mandates
 * TDD, and its job is not losing the user's work. These tests exist because the
 * failure modes are all silent: a corrupt entry, an exhausted quota, or a
 * mis-resolved id all look exactly like "it saved fine" from the UI.
 */
describe('workflowStore', () => {
  let workbench: Workbench;
  let store: FakeStore;
  let guard: WriteGuard;

  beforeEach(() => {
    workbench = makeWorkbench();
    store = new FakeStore();
    guard = newWriteGuard('tab-a');
    addNode(workbench, TYPE.agent);
  });

  const saveAs = (writer: WriteGuard, id: string, at: string) =>
    saveWorkflow(store, id, workbench.model, workbench.serializer, writer, { now: () => at });
  const save = (id: string, at: string) => saveAs(guard, id, at);

  describe('round trip', () => {
    it('saves and reloads a workflow', () => {
      workbench.model.setName('Chinook explorer');
      expect(save('wf-1', '2026-08-05T10:00:00Z').ok).toBe(true);

      const outcome = readWorkflow(store, 'wf-1');
      expect(outcome.status).toBe('ok');
      if (outcome.status !== 'ok') return;
      expect(outcome.savedAt).toBe('2026-08-05T10:00:00Z');

      const reloaded = makeWorkbench();
      const imported = reloaded.controller.document.importJSON(outcome.json);
      expect(imported.ok).toBe(true);
      expect(reloaded.model.name).toBe('Chinook explorer');
      expect(reloaded.model.nodeCount).toBe(1);
    });

    it('reports a workflow that was never saved as missing, not as an error', () => {
      expect(readWorkflow(store, 'wf-missing')).toEqual({ status: 'missing' });
    });

    it('stores under a namespaced key, so it cannot collide with other app state', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      expect(store.key(0)).toBe(`${STORAGE_PREFIX}wf-1`);
    });

    it('still reads a pre-envelope entry, which is the document itself', () => {
      store.poison(`${STORAGE_PREFIX}wf-old`, '{"nodes":[],"edges":[]}');
      const outcome = readWorkflow(store, 'wf-old');
      expect(outcome.status).toBe('ok');
    });
  });

  /* ================================================================ *
   * UX-04, failure 1: a write that fails must fail LOUDLY.
   * ================================================================ */

  describe('a failed write is reported, never swallowed', () => {
    it('reports a quota failure instead of pretending to succeed', () => {
      store.full = true;
      const outcome = save('wf-1', '2026-08-05T10:00:00Z');

      // Silently failing here is the worst case for a feature whose entire
      // purpose is not losing work: the user keeps editing, believing it saved.
      expect(outcome.ok).toBe(false);
      expect(outcome.kind).toBe('quota');
      expect(outcome.reason).toMatch(/quota|space/i);
    });

    it('refuses an oversized payload before it can half-write, and says so', () => {
      workbench.model.setName('x'.repeat(MAX_PAYLOAD_BYTES + 1));
      const outcome = save('wf-1', '2026-08-05T10:00:00Z');

      expect(outcome.ok).toBe(false);
      expect(outcome.kind).toBe('too-large');
      // Nothing was written: a rejected save must not destroy the last good one.
      expect(store.getItem(`${STORAGE_PREFIX}wf-1`)).toBeNull();
    });

    it('leaves the previous good save intact when the new one is rejected', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      store.full = true;
      expect(save('wf-1', '2026-08-05T11:00:00Z').ok).toBe(false);

      const outcome = readWorkflow(store, 'wf-1');
      expect(outcome.status).toBe('ok');
      if (outcome.status === 'ok') expect(outcome.savedAt).toBe('2026-08-05T10:00:00Z');
    });

    it('reports storage being unavailable entirely rather than throwing', () => {
      store.broken = true;
      const outcome = save('wf-1', '2026-08-05T10:00:00Z');
      expect(outcome.ok).toBe(false);
      expect(outcome.kind).toBe('error');
    });
  });

  /* ================================================================ *
   * UX-04, failure 2: a corrupt payload must not brick the next load.
   * ================================================================ */

  describe('a corrupt entry recovers to a working state and says what happened', () => {
    it('reports corruption rather than a bare null, so the user can be told', () => {
      store.poison(`${STORAGE_PREFIX}wf-bad`, '{ not json');
      const outcome = readWorkflow(store, 'wf-bad');

      expect(outcome.status).toBe('corrupt');
      if (outcome.status === 'corrupt') expect(outcome.reason).toBeTruthy();
    });

    it('treats an entry that parses but holds no document as corrupt', () => {
      store.poison(`${STORAGE_PREFIX}wf-bad`, '{"version":2,"savedAt":"x"}');
      expect(readWorkflow(store, 'wf-bad').status).toBe('corrupt');
    });

    it('quarantines the bad bytes instead of leaving them to fail every load', () => {
      store.poison(`${STORAGE_PREFIX}wf-bad`, '{ not json');
      readWorkflow(store, 'wf-bad');

      // Gone from the live key — the next load starts clean...
      expect(store.getItem(`${STORAGE_PREFIX}wf-bad`)).toBeNull();
      expect(readWorkflow(store, 'wf-bad')).toEqual({ status: 'missing' });
      // ...but kept, because they are the only copy of that user's work.
      const quarantined = store.keys().filter((key) => key.startsWith(CORRUPT_PREFIX));
      expect(quarantined).toHaveLength(1);
      expect(store.getItem(quarantined[0] as string)).toBe('{ not json');
    });

    it('does not list a quarantined entry as a workflow', () => {
      save('wf-good', '2026-08-05T10:00:00Z');
      store.poison(`${STORAGE_PREFIX}wf-bad`, '{ not json');
      readWorkflow(store, 'wf-bad');

      expect(listWorkflows(store).map((w) => w.id)).toEqual(['wf-good']);
    });

    it('can still save over a key whose old entry was corrupt', () => {
      store.poison(`${STORAGE_PREFIX}wf-1`, '{ not json');
      readWorkflow(store, 'wf-1');
      expect(save('wf-1', '2026-08-05T10:00:00Z').ok).toBe(true);
    });

    it('skips a corrupt entry when listing rather than failing the whole list', () => {
      save('wf-good', '2026-08-05T10:00:00Z');
      store.poison(`${STORAGE_PREFIX}wf-bad`, 'not json at all');

      expect(listWorkflows(store).map((w) => w.id)).toEqual(['wf-good']);
    });

    it('ignores keys belonging to other features', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      store.poison('some-other-app-key', 'whatever');
      expect(listWorkflows(store)).toHaveLength(1);
    });
  });

  /* ================================================================ *
   * UX-04, failure 3: a second tab must not silently clobber the first.
   * ================================================================ */

  describe('a second tab cannot silently clobber the first', () => {
    it('refuses to overwrite a save this tab has never seen', () => {
      const tabB = newWriteGuard('tab-b');
      // Tab A restores the entry it wrote, so it knows that version.
      save('wf-1', '2026-08-05T10:00:00Z');
      guard.lastSeenAt = '2026-08-05T10:00:00Z';

      // Tab B writes underneath it.
      tabB.lastSeenAt = '2026-08-05T10:00:00Z';
      expect(saveAs(tabB, 'wf-1', '2026-08-05T10:05:00Z').ok).toBe(true);

      // Tab A's next autosave would have destroyed tab B's work.
      const outcome = save('wf-1', '2026-08-05T10:06:00Z');
      expect(outcome.ok).toBe(false);
      expect(outcome.kind).toBe('conflict');

      const stored = readWorkflow(store, 'wf-1');
      expect(stored.status === 'ok' && stored.savedAt).toBe('2026-08-05T10:05:00Z');
    });

    it('lets a tab keep saving over its own writes', () => {
      expect(save('wf-1', '2026-08-05T10:00:00Z').ok).toBe(true);
      expect(save('wf-1', '2026-08-05T10:01:00Z').ok).toBe(true);
      expect(save('wf-1', '2026-08-05T10:02:00Z').ok).toBe(true);
    });

    it('lets a NEW tab adopt an entry left by a closed one', () => {
      // The legitimate case a naive "different writer means conflict" rule
      // would break forever: the first tab is gone, and nobody else can write.
      save('wf-1', '2026-08-05T10:00:00Z');

      const later = newWriteGuard('tab-later');
      const restored = readWorkflow(store, 'wf-1');
      expect(restored.status).toBe('ok');
      if (restored.status === 'ok') later.lastSeenAt = restored.savedAt;

      expect(saveAs(later, 'wf-1', '2026-08-06T09:00:00Z').ok).toBe(true);
    });

    it('never opens a workflow another live tab holds, claim or no claim', () => {
      // Two cases that used to differ and no longer can: a live claim made
      // `resolveSession` mint instead of adopt, and a stale one let it adopt
      // again. Since `install-experience` 23 a tab with no session id of its
      // own adopts nothing at all, so the claim has nothing left to gate here.
      // The claim itself is untouched and still does its real job — see
      // `saveWorkflow`'s compare-and-set below.
      claimSession(store, 'wf-1', newWriteGuard('tab-a'), () => 1_000);
      expect(isClaimedByAnother(store, 'wf-1', newWriteGuard('tab-b'), () => 2_000)).toBe(true);
      expect(isClaimedByAnother(store, 'wf-1', newWriteGuard('tab-b'), () => 10_000_000)).toBe(
        false,
      );

      for (const _ of [1, 2]) {
        const session = resolveSession({
          sessionId: null,
          mostRecentId: 'wf-1',
          mintId: () => 'wf-minted',
        });
        expect(session.id).toBe('wf-minted');
        expect(session.shouldRestore).toBe(false);
      }
    });

    it('does not treat a tab’s own claim as somebody else’s', () => {
      const tabA = newWriteGuard('tab-a');
      claimSession(store, 'wf-1', tabA, () => 1_000);
      expect(isClaimedByAnother(store, 'wf-1', tabA, () => 2_000)).toBe(false);
    });

    it('keeps claims out of the workflow listing', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      claimSession(store, 'wf-1', guard, () => 1_000);

      expect(store.keys().some((key) => key.startsWith(CLAIM_PREFIX))).toBe(true);
      expect(listWorkflows(store)).toHaveLength(1);
    });

    it('never throws when the claim cannot be written', () => {
      store.full = true;
      expect(() => claimSession(store, 'wf-1', guard, () => 1_000)).not.toThrow();
      expect(isClaimedByAnother(store, 'wf-1', newWriteGuard('tab-b'), () => 2_000)).toBe(false);
    });
  });

  describe('listing', () => {
    it('orders newest first', () => {
      save('wf-old', '2026-08-01T10:00:00Z');
      save('wf-new', '2026-08-05T10:00:00Z');
      save('wf-mid', '2026-08-03T10:00:00Z');

      expect(listWorkflows(store).map((w) => w.id)).toEqual(['wf-new', 'wf-mid', 'wf-old']);
      expect(mostRecentWorkflowId(store)).toBe('wf-new');
    });

    it('reports the workflow name, so the manager can show something meaningful', () => {
      workbench.model.setName('Chinook explorer');
      save('wf-1', '2026-08-05T10:00:00Z');
      expect(listWorkflows(store)[0]?.name).toBe('Chinook explorer');
    });

    it('has no most-recent id when nothing is saved', () => {
      expect(mostRecentWorkflowId(store)).toBeNull();
    });

    it('survives storage being unavailable entirely', () => {
      store.broken = true;
      expect(listWorkflows(store)).toEqual([]);
      expect(mostRecentWorkflowId(store)).toBeNull();
    });

    it('drops a deleted workflow', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      deleteWorkflow(store, 'wf-1');
      expect(listWorkflows(store)).toHaveLength(0);
      expect(readWorkflow(store, 'wf-1')).toEqual({ status: 'missing' });
    });
  });

  /**
   * The defect that made this refactor necessary.
   *
   * The old hooks minted a fresh `wf-<timestamp>` whenever the session had no id,
   * then saved unconditionally on mount, while a separate hook imported the most
   * recent workflow. Every new tab therefore left another complete copy of the
   * graph in storage under a brand-new key — unbounded growth, and the user's
   * workflow list filling with duplicates of itself.
   */
  describe('session resolution', () => {
    it('keeps editing the workflow this tab already had', () => {
      const session = resolveSession({
        sessionId: 'wf-current',
        mostRecentId: 'wf-other',
        mintId: () => 'wf-minted',
      });
      expect(session).toEqual({ id: 'wf-current', shouldRestore: true });
    });

    it('starts a tab that has never had a document on a blank one', () => {
      const session = resolveSession({
        sessionId: null,
        mostRecentId: 'wf-recent',
        mintId: () => 'wf-minted',
      });

      // This used to adopt `wf-recent` and restore it, which is how a bare URL
      // came to open a previous session's workflow (`install-experience` 23).
      // Minting duplicated the graph back when a minted id was followed by an
      // unconditional initial save *and* an import over the top; neither
      // survives, so a minted id now writes nothing until the user edits.
      expect(session.id).toBe('wf-minted');
      expect(session.shouldRestore).toBe(false);
      // …and the draft is mentioned rather than opened, because it is still
      // there and the user has no other way to know that.
      expect(session.notice).toMatch(/unsaved/i);
    });

    it('mints only when there is genuinely nothing saved, and does not restore', () => {
      const session = resolveSession({
        sessionId: null,
        mostRecentId: null,
        mintId: () => 'wf-minted',
      });

      // Nothing to restore, so importing would clear the undo stack for no gain.
      expect(session).toEqual({ id: 'wf-minted', shouldRestore: false });
    });

    it('treats an empty-string id as absent', () => {
      const session = resolveSession({
        sessionId: '',
        mostRecentId: '',
        mintId: () => 'wf-minted',
      });
      expect(session).toEqual({ id: 'wf-minted', shouldRestore: false });
    });

    it('never copies an existing graph into a second entry, however many tabs open', () => {
      // The defect this resolver was written for, stated as what it actually
      // was: three tab opens each *restored* the newest workflow and then
      // autosaved it under a fresh key, so storage filled with copies of one
      // graph. What is asserted is that copying — not the entry count, which
      // was only ever a proxy for it and stopped being one when adoption went.
      save('wf-1', '2026-08-05T10:00:00Z');
      const original = readWorkflow(store, 'wf-1');
      expect(original.status).toBe('ok');

      let sessionId: string | null = null;
      for (let i = 0; i < 3; i += 1) {
        const session = resolveSession({
          sessionId,
          mostRecentId: mostRecentWorkflowId(store),
          mintId: () => `wf-minted-${i}`,
        });
        expect(session.shouldRestore).toBe(false);
        sessionId = null; // a fresh tab each time
      }

      // Nothing restored means nothing to write back, so the one graph in
      // storage is still the one graph in storage.
      expect(listWorkflows(store).map((wf) => wf.id)).toEqual(['wf-1']);
    });
  });
});
