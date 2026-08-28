import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import {
  claimSession,
  newWriteGuard,
  saveWorkflow,
  type KeyValueStore,
  type WriteGuard,
} from '@app/workflowStore';
import { discardDraftAfterDelete, draftIdForSlug, restoreDraftFor } from '@app/workflowDrafts';

/**
 * `launch-readiness/148` — a delete in one tab destroyed another tab's draft.
 *
 * The whole defect lives in the gap between two storage areas: a draft is
 * keyed per **slug** in `localStorage`, which every tab of the origin shares,
 * while "which draft am I editing" is per **tab**. `discardDraftAfterDelete`
 * only knew the slug, so it reached across that boundary every time.
 *
 * A test that drives one tab cannot see this: with a single tab the draft
 * being discarded really is that tab's own. So every case here runs **two**
 * tabs against **one** store, exactly as two browser tabs share one origin.
 */
class SharedOrigin implements KeyValueStore {
  private readonly map = new Map<string, string>();
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

/** One browser tab: its own write identity and its own current draft key. */
interface Tab {
  readonly guard: WriteGuard;
  readonly draftId: string | null;
}

describe('a delete in one tab keeps another tab s draft', () => {
  let store: SharedOrigin;

  beforeEach(() => {
    store = new SharedOrigin();
  });

  const editorHolding = (name: string): Workbench => {
    const workbench = new Workbench();
    workbench.model.setName(name);
    return workbench;
  };

  /** Tab `tab` types into `slug` and lets autosave write it. */
  const typeInto = (tab: Tab, slug: string): void => {
    const editing = editorHolding('Probe 148');
    addNode(editing, TYPE.markdownFile, { at: { x: 40, y: 40 } });
    saveWorkflow(store, draftIdForSlug(slug), editing.model, editing.serializer, tab.guard);
  };

  /** A tab that is live on `slug`, heartbeat and all. */
  const tabEditing = (slug: string, atMs: number): Tab => {
    const guard = newWriteGuard();
    const tab: Tab = { guard, draftId: draftIdForSlug(slug) };
    claimSession(store, draftIdForSlug(slug), guard, () => atMs);
    return tab;
  };

  const draftKeyFor = (slug: string): string => `openstategraph-workflow-${draftIdForSlug(slug)}`;

  it('leaves the draft alone when another live tab is editing it, and says so', () => {
    const now = 1_000_000;
    const tabB = tabEditing('probe-148', now);
    typeInto(tabB, 'probe-148');
    expect(store.getItem(draftKeyFor('probe-148'))).not.toBe(null);

    // Tab A is elsewhere — its own draft key names a different document.
    const tabA: Tab = { guard: newWriteGuard(), draftId: 'wf-1700000000000' };

    const decision = discardDraftAfterDelete('probe-148', store, tabA.draftId, () => now + 1_000);

    expect(decision.discarded).toBe(false);
    expect(decision.reason).toBe('another-tab-is-editing');
    expect(store.getItem(draftKeyFor('probe-148'))).not.toBe(null);
  });

  it('the surviving draft is still restorable in the tab that owns it', () => {
    const now = 2_000_000;
    const tabB = tabEditing('probe-148', now);
    typeInto(tabB, 'probe-148');
    const tabA: Tab = { guard: newWriteGuard(), draftId: 'wf-1700000000000' };

    discardDraftAfterDelete('probe-148', store, tabA.draftId, () => now + 1_000);

    // What tab B would do on its next render: the work is still there.
    const stillOpen = editorHolding('Probe 148');
    expect(restoreDraftFor('probe-148', stillOpen, store).restored).toBe(true);
  });

  it('still discards the deleting tab s own draft — 95 is not re-opened', () => {
    const now = 3_000_000;
    const tabA = tabEditing('probe-148', now);
    typeInto(tabA, 'probe-148');

    // A holds the only live claim, and the draft being deleted is A's own.
    const decision = discardDraftAfterDelete('probe-148', store, tabA.draftId, () => now + 1_000);

    expect(decision.discarded).toBe(true);
    expect(store.getItem(draftKeyFor('probe-148'))).toBe(null);
  });

  it('still discards a leftover draft no live tab holds — 95 is not re-opened', () => {
    const now = 4_000_000;
    // A tab that has since gone: its claim is older than the staleness window.
    const gone = tabEditing('probe-148', now);
    typeInto(gone, 'probe-148');

    const decision = discardDraftAfterDelete(
      'probe-148',
      store,
      'wf-1700000000000',
      () => now + 60_000,
    );

    expect(decision.discarded).toBe(true);
    expect(store.getItem(draftKeyFor('probe-148'))).toBe(null);
  });

  it('discards when there is no draft at all, and reports nothing kept', () => {
    const decision = discardDraftAfterDelete('probe-148', store, null, () => 5_000_000);
    expect(decision.discarded).toBe(true);
  });
});
