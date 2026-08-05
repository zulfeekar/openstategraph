import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import {
  deleteWorkflow,
  listWorkflows,
  loadWorkflow,
  mostRecentWorkflowId,
  resolveSession,
  saveWorkflow,
  STORAGE_PREFIX,
  type KeyValueStore,
} from '@app/workflowStore';

/** An in-memory `Storage`, so this runs in the node environment like `core/`. */
class FakeStore implements KeyValueStore {
  private readonly map = new Map<string, string>();
  /** Set to simulate the ~5MB quota, the one failure that really happens. */
  full = false;

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
    if (this.full) throw new DOMException('quota exceeded', 'QuotaExceededError');
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
  /** Test-only: plant a corrupt entry. */
  poison(key: string, value: string): void {
    this.map.set(key, value);
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

  beforeEach(() => {
    workbench = makeWorkbench();
    store = new FakeStore();
    addNode(workbench, TYPE.agent);
  });

  const save = (id: string, at: string) =>
    saveWorkflow(store, id, workbench.model, workbench.serializer, () => at);

  describe('round trip', () => {
    it('saves and reloads a workflow', () => {
      workbench.model.setName('Chinook explorer');
      expect(save('wf-1', '2026-08-05T10:00:00Z').ok).toBe(true);

      const json = loadWorkflow(store, 'wf-1');
      expect(json).not.toBeNull();

      const reloaded = makeWorkbench();
      const outcome = reloaded.controller.document.importJSON(json as string);
      expect(outcome.ok).toBe(true);
      expect(reloaded.model.name).toBe('Chinook explorer');
      expect(reloaded.model.nodeCount).toBe(1);
    });

    it('returns null for a workflow that was never saved', () => {
      expect(loadWorkflow(store, 'wf-missing')).toBeNull();
    });

    it('stores under a namespaced key, so it cannot collide with other app state', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      expect(store.key(0)).toBe(`${STORAGE_PREFIX}wf-1`);
    });
  });

  describe('failure is reported, not swallowed', () => {
    it('reports a quota failure instead of pretending to succeed', () => {
      store.full = true;
      const outcome = save('wf-1', '2026-08-05T10:00:00Z');

      // Silently failing here is the worst case for a feature whose entire
      // purpose is not losing work: the user keeps editing, believing it saved.
      expect(outcome.ok).toBe(false);
      expect(outcome.reason).toMatch(/quota/i);
    });

    it('survives a corrupt entry when loading', () => {
      store.poison(`${STORAGE_PREFIX}wf-bad`, '{ not json');
      expect(loadWorkflow(store, 'wf-bad')).toBeNull();
    });

    it('skips a corrupt entry when listing rather than failing the whole list', () => {
      save('wf-good', '2026-08-05T10:00:00Z');
      store.poison(`${STORAGE_PREFIX}wf-bad`, 'not json at all');

      const listed = listWorkflows(store);
      expect(listed.map((w) => w.id)).toEqual(['wf-good']);
    });

    it('ignores keys belonging to other features', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      store.poison('some-other-app-key', 'whatever');
      expect(listWorkflows(store)).toHaveLength(1);
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

    it('drops a deleted workflow', () => {
      save('wf-1', '2026-08-05T10:00:00Z');
      deleteWorkflow(store, 'wf-1');
      expect(listWorkflows(store)).toHaveLength(0);
      expect(loadWorkflow(store, 'wf-1')).toBeNull();
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

    it('adopts the most recent id rather than minting a new one', () => {
      const session = resolveSession({
        sessionId: null,
        mostRecentId: 'wf-recent',
        mintId: () => 'wf-minted',
      });

      // Minting here is what duplicated the graph on every tab open.
      expect(session.id).toBe('wf-recent');
      expect(session.shouldRestore).toBe(true);
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

    it('does not accumulate entries across repeated tab opens', () => {
      // Simulate three tab opens against the same storage.
      let sessionId: string | null = null;
      for (let i = 0; i < 3; i += 1) {
        const session = resolveSession({
          sessionId,
          mostRecentId: mostRecentWorkflowId(store),
          mintId: () => 'wf-minted',
        });
        save(session.id, `2026-08-0${i + 1}T10:00:00Z`);
        sessionId = null; // a fresh tab each time
      }

      expect(listWorkflows(store)).toHaveLength(1);
    });
  });
});
