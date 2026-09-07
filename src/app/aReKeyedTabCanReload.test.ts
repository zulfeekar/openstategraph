import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import {
  claimSession,
  mostRecentWorkflowId,
  newWriteGuard,
  readWorkflow,
  resolveSession,
  saveWorkflow,
  type KeyValueStore,
  type WriteGuard,
} from '@app/workflowStore';
import {
  DRAFT_SESSION_KEY,
  currentDraftId,
  decideDraftCarry,
  draftIdForSlug,
  draftSavedAt,
  followOpenSubjectWithDraftKey,
} from '@app/workflowDrafts';
import { clearOpenSlug, getOpenSlug, setOpenSlug } from '@app/openWorkflow';
import { abandonDeletedWorkflow, forgetDiskDocument } from '@app/diskAutosave';

/**
 * launch-readiness 153 — **a re-keyed tab holds its document nowhere.**
 *
 * `147` gave a tab told its workflow was deleted elsewhere the right
 * behaviour: drop the disk baseline, forget the `savedAt`, and **release the
 * slug** — a slug is frozen, so a document whose package is gone cannot have
 * that identity back, and the honest offer is a new package.
 *
 * Releasing it re-keys the tab's autosave to a fresh `wf-<timestamp>`
 * (`followOpenSubjectWithDraftKey`). But autosave takes *"no initial save"* as
 * a rule, so **nothing is written under the new key until the next edit**. In
 * between, the tab's document exists only in memory: the old `slug-<slug>`
 * draft is not this tab's any more, the new key holds nothing, and a reload
 * lands on a blank canvas. Observed live on 2026-08-28 on a throwaway
 * `probe-148`, with the work still sitting in `localStorage` under the slug
 * key nobody would ask for again.
 *
 * ## Why the test is a reload
 *
 * Because that is the only thing that fails. Every unit here passed: the
 * abandon released the slug correctly, the re-key minted correctly, and the
 * draft was never destroyed. The defect is the *seam* — a fresh module graph
 * meeting surviving storage, which is what `reloadAfterSave.test.ts` says at
 * length and is why this file borrows its shape.
 */

/** An in-memory `Storage`, so this runs in the node environment like `core/`. */
class FakeStore implements KeyValueStore {
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
  keys(): readonly string[] {
    return [...this.map.keys()];
  }
}

describe('a tab whose workflow was deleted elsewhere', () => {
  let local: FakeStore;
  let session: FakeStore;
  let writer: WriteGuard;
  let stop: () => void;

  beforeEach(() => {
    local = new FakeStore();
    session = new FakeStore();
    (globalThis as Record<string, unknown>)['localStorage'] = local;
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
    writer = newWriteGuard();
    // The listener the editor really registers (`WorkbenchContext`): it is what
    // turns `clearOpenSlug` into a fresh autosave key, so a test without it
    // cannot see this defect at all.
    stop = followOpenSubjectWithDraftKey(writer, () => {}, local);
  });

  afterEach(() => {
    stop();
    clearOpenSlug();
    forgetDiskDocument('probe-153');
  });

  /** A tab with `slug` open, holding unsaved edits in this browser's draft. */
  function aTabEditing(slug: string, name: string, nodes: number): Workbench {
    const workbench = new Workbench();
    workbench.model.setName(name);
    for (let i = 0; i < nodes; i += 1) {
      addNode(workbench, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    }
    setOpenSlug(slug);
    session.setItem(DRAFT_SESSION_KEY, draftIdForSlug(slug));
    claimSession(local, draftIdForSlug(slug), writer);
    expect(
      saveWorkflow(local, draftIdForSlug(slug), workbench.model, workbench.serializer, writer).ok,
    ).toBe(true);
    return workbench;
  }

  /** ⌘R — a fresh module graph over the storage this tab left behind. */
  function reload(): Workbench {
    const reloaded = new Workbench();
    const plan = resolveSession({
      sessionId: session.getItem(DRAFT_SESSION_KEY),
      mostRecentId: mostRecentWorkflowId(local),
      mintId: () => `wf-${Date.now()}`,
    });
    if (plan.shouldRestore) {
      const outcome = readWorkflow(local, plan.id);
      if (outcome.status === 'ok') reloaded.controller.document.importJSON(outcome.json);
    }
    return reloaded;
  }

  it('can reload before its next edit and still be holding its document', () => {
    aTabEditing('probe-153', 'Probe 153 UNSAVED WORK IN TAB B', 3);

    // The watch's verdict, five seconds after another tab pressed Delete.
    abandonDeletedWorkflow('probe-153', 'deleted-elsewhere');

    const reloaded = reload();
    expect(reloaded.model.name).toBe('Probe 153 UNSAVED WORK IN TAB B');
    expect(reloaded.model.nodes().length).toBe(3);
  });

  it('carries the draft rather than copying it, so one key holds the work', () => {
    aTabEditing('probe-153', 'Probe 153', 2);

    abandonDeletedWorkflow('probe-153', 'deleted-elsewhere');

    const carried = currentDraftId();
    expect(carried).not.toBeNull();
    expect(carried).not.toBe(draftIdForSlug('probe-153'));
    expect(readWorkflow(local, carried as string).status).toBe('ok');
    // The slug key is released, not duplicated: two keys holding one document
    // is `96`'s growth and a second answer to "who owns this draft now".
    expect(readWorkflow(local, draftIdForSlug('probe-153')).status).toBe('missing');
  });

  it('does not give the released document its package back', () => {
    aTabEditing('probe-153', 'Probe 153', 1);

    abandonDeletedWorkflow('probe-153', 'deleted-elsewhere');

    // `147`'s whole point. The carry moves a *browser draft* under a key that
    // names no package; nothing about it re-opens the slug or re-arms the
    // disk writer.
    expect(getOpenSlug()).toBeNull();
    const carried = currentDraftId() as string;
    expect(carried.startsWith('slug-')).toBe(false);
  });

  it('leaves the carried draft writable, so the next keystroke is not a conflict', () => {
    const workbench = aTabEditing('probe-153', 'Probe 153', 1);
    // A tab that loaded the workflow and had not typed since: the draft in
    // storage was written by an earlier page load, under a writer id this
    // tab's guard does not have.
    const stranger = newWriteGuard();
    stranger.lastSeenAt = draftSavedAt('probe-153', local);
    expect(
      saveWorkflow(
        local,
        draftIdForSlug('probe-153'),
        workbench.model,
        workbench.serializer,
        stranger,
      ).ok,
    ).toBe(true);
    writer.lastSeenAt = null;

    abandonDeletedWorkflow('probe-153', 'deleted-elsewhere');

    addNode(workbench, TYPE.agent);
    const outcome = saveWorkflow(
      local,
      currentDraftId() as string,
      workbench.model,
      workbench.serializer,
      writer,
    );
    // Before the hand-over disowned the carried bytes this was `conflict` —
    // *"another browser tab saved this workflow more recently"* — about a tab
    // that does not exist, on a key only this tab can name.
    expect(outcome).toEqual({ ok: true });
  });

  it('carries nothing when the draft is not the one this tab is writing', () => {
    // Two tabs, one origin. A tab editing something else must not walk off
    // with the deleted workflow's draft — `148`'s rule, in the other
    // direction.
    expect(
      decideDraftCarry({
        draftId: draftIdForSlug('probe-153'),
        thisTabsDraftId: draftIdForSlug('other'),
      }).carried,
    ).toBe(false);
    expect(
      decideDraftCarry({
        draftId: draftIdForSlug('probe-153'),
        thisTabsDraftId: draftIdForSlug('probe-153'),
      }).carried,
    ).toBe(true);
  });
});
