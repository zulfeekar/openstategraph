import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import {
  claimSession,
  newWriteGuard,
  readWorkflow,
  saveWorkflow,
  type KeyValueStore,
  type WriteGuard,
} from '@app/workflowStore';
import {
  DRAFT_SESSION_KEY,
  draftIdForSlug,
  followOpenSubjectWithDraftKey,
} from '@app/workflowDrafts';
import { clearOpenSlug, setOpenSlug } from '@app/openWorkflow';
import { abandonDeletedWorkflow, forgetDiskDocument } from '@app/diskAutosave';

/**
 * `launch-readiness/169` — the panel's own delete asked who owns the draft one
 * step too late.
 *
 * `147` made the Workflows panel and the file watch share one spelling of
 * *"this package is gone"*, and that call **releases the slug** — which
 * re-keys this tab, synchronously, inside the call. The discard that followed
 * it read `currentDraftId()` afterwards, so it compared the freshly minted
 * `wf-<timestamp>` against `slug-<slug>`, found them different, and read this
 * tab's own live claim as another tab's. `95`'s orphan survived the delete and
 * the user was told about a window that did not exist.
 *
 * ## Why this test is a composition and `148`'s are not
 *
 * `148`'s tests pass `thisTabsDraftId` in by hand — deliberately, because a
 * test that reads it from `sessionStorage` inside one storage context cannot
 * fail against `148`'s defect. Every rule they state was, and stayed, correct:
 * the only thing wrong here is the **order** of two correct functions at one
 * call site. So this file drives the whole gesture through real storage, with
 * the re-key listener the editor really registers.
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

describe('deleting the open workflow from this tab s own panel', () => {
  let local: SharedOrigin;
  let session: SharedOrigin;
  let writer: WriteGuard;
  let stop: () => void;

  beforeEach(() => {
    local = new SharedOrigin();
    session = new SharedOrigin();
    (globalThis as Record<string, unknown>)['localStorage'] = local;
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
    writer = newWriteGuard();
    stop = followOpenSubjectWithDraftKey(writer, () => {}, local);
  });

  afterEach(() => {
    stop();
    clearOpenSlug();
    forgetDiskDocument('probe-169');
  });

  /** This tab, open on `slug`, with a draft and a live claim of its own. */
  function thisTabEditing(slug: string): Workbench {
    const workbench = new Workbench();
    workbench.model.setName('Probe 169');
    addNode(workbench, TYPE.markdownFile, { at: { x: 40, y: 40 } });
    setOpenSlug(slug);
    session.setItem(DRAFT_SESSION_KEY, draftIdForSlug(slug));
    claimSession(local, draftIdForSlug(slug), writer);
    saveWorkflow(local, draftIdForSlug(slug), workbench.model, workbench.serializer, writer);
    return workbench;
  }

  it('drops its own draft, so 95 s orphan does not survive the delete', () => {
    thisTabEditing('probe-169');
    expect(readWorkflow(local, draftIdForSlug('probe-169')).status).toBe('ok');

    const outcome = abandonDeletedWorkflow('probe-169', 'deleted-here');

    // Before the order was fixed this was `kept-for-another-tab`: the draft
    // stayed under `slug-probe-169`, ready for the next workflow minted with
    // that slug to inherit, and the toast named a tab that did not exist.
    expect(outcome.draft).toBe('discarded');
    expect(readWorkflow(local, draftIdForSlug('probe-169')).status).toBe('missing');
  });

  it('still keeps a draft a genuinely different live tab is editing', () => {
    // Tab B is the one holding the work; this tab is elsewhere and never
    // opened it, which is exactly `148`'s case.
    const other = newWriteGuard();
    const editing = new Workbench();
    editing.model.setName('Probe 169 in tab B');
    addNode(editing, TYPE.markdownFile, { at: { x: 0, y: 0 } });
    claimSession(local, draftIdForSlug('probe-169'), other);
    saveWorkflow(local, draftIdForSlug('probe-169'), editing.model, editing.serializer, other);
    session.setItem(DRAFT_SESSION_KEY, 'wf-1700000000000');

    const outcome = abandonDeletedWorkflow('probe-169', 'deleted-here');

    expect(outcome.draft).toBe('kept-for-another-tab');
    expect(readWorkflow(local, draftIdForSlug('probe-169')).status).toBe('ok');
  });
});
