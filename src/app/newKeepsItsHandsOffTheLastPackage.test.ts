import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import {
  claimSession,
  newWriteGuard,
  readWorkflow,
  saveWorkflow,
  type KeyValueStore,
} from '@app/workflowStore';
import {
  DRAFT_SESSION_KEY,
  draftIdForSlug,
  followOpenSubjectWithDraftKey,
} from '@app/workflowDrafts';
import { clearOpenSlug, setOpenSlug } from '@app/openWorkflow';

/**
 * `production-ready` 77 — **`New` hands its draft to the package you just
 * left.** The other half of 71, and the same data loss by the other road.
 *
 * Reproduced in the browser after 71 shipped:
 *
 *     ?w=chinook-assistant          13 nodes on screen
 *     press New                     0 nodes, URL drops to /
 *     place one node
 *       localStorage  openstategraph-workflow-slug-chinook-assistant -> 1 node
 *       sessionStorage openstategraph-current-workflow-id = slug-chinook-assistant
 *     open ?w=chinook-assistant     canvas reads "Workflow 2026", 1 node
 *
 * and `workflows/chinook-assistant/workflow.json` was then overwritten with
 * it — through the ordinary restore-then-autosave path, with every guard 71
 * added working exactly as intended. 71 stopped a *blank* canvas owning a
 * package; this is a **new** document owning one.
 *
 * ## Where it lived
 *
 * `createNewWorkflow` calls `clearOpenSlug()`, which announces `null` to the
 * channel the draft key follows. The listener began:
 *
 *     if (slug == null) return;
 *
 * — so on the one announcement that means *this document has no identity any
 * more*, the key kept the identity of the last one. Every other branch of that
 * listener was right; the null case had simply never been given an answer.
 *
 * ## What the fix must not do
 *
 * **Not move the old draft, and not delete it.** `adoptSlugForDraft` carries
 * the warning in full — re-filing a scratch document as an opened workflow's
 * unsaved edits is ticket 23's data loss with the arrow reversed. The previous
 * package's draft is somebody's work and stays exactly where it is. The new
 * document simply stops writing into it.
 */

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

const SLUG = 'chinook-assistant';

describe('production-ready 77 — New must not write into the last package', () => {
  let local: FakeStore;
  let session: FakeStore;
  let ids: string[];
  let stop: () => void;

  beforeEach(() => {
    local = new FakeStore();
    session = new FakeStore();
    ids = [];
    (globalThis as Record<string, unknown>)['localStorage'] = local;
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
  });

  /**
   * The listener as the editor registers it — the real channel, driven by the
   * real `setOpenSlug`/`clearOpenSlug`, with only React left out.
   */
  function tabIsListening(): void {
    stop = followOpenSubjectWithDraftKey(newWriteGuard(), (id) => ids.push(id), local);
  }

  /** A package open, with this browser holding unsaved edits to it. */
  function openPackageWithADraft(slug: string, nodes: number): string {
    const bench = new Workbench();
    bench.model.setName('Chinook Assistant');
    for (let i = 0; i < nodes; i += 1) addNode(bench, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    const writer = newWriteGuard();
    claimSession(local, draftIdForSlug(slug), writer);
    expect(saveWorkflow(local, draftIdForSlug(slug), bench.model, bench.serializer, writer).ok).toBe(
      true,
    );
    setOpenSlug(slug);
    return local.getItem(`openstategraph-workflow-${draftIdForSlug(slug)}`) ?? '';
  }

  it('gives the new document an identity of its own', () => {
    tabIsListening();
    openPackageWithADraft(SLUG, 13);
    expect(session.getItem(DRAFT_SESSION_KEY)).toBe(draftIdForSlug(SLUG));

    clearOpenSlug(); // what `createNewWorkflow` does

    const now = session.getItem(DRAFT_SESSION_KEY);
    expect(now).not.toBe(draftIdForSlug(SLUG));
    expect(now?.startsWith('slug-')).toBe(false);
    expect(ids.at(-1)).toBe(now);
    stop();
  });

  it('leaves the package draft exactly where it was', () => {
    tabIsListening();
    const before = openPackageWithADraft(SLUG, 13);

    clearOpenSlug();
    // The user draws something in the new document; it autosaves.
    const fresh = new Workbench();
    fresh.model.setName('Workflow 2026');
    addNode(fresh, TYPE.textInput, { at: { x: 0, y: 0 } });
    const writer = newWriteGuard();
    const id = session.getItem(DRAFT_SESSION_KEY) ?? '';
    claimSession(local, id, writer);
    expect(saveWorkflow(local, id, fresh.model, fresh.serializer, writer).ok).toBe(true);

    // Not moved, not emptied, not overwritten — someone's unsaved work.
    const after = local.getItem(`openstategraph-workflow-${draftIdForSlug(SLUG)}`);
    expect(after).toBe(before);
    const draft = readWorkflow(local, draftIdForSlug(SLUG));
    expect(draft.status).toBe('ok');
    stop();
  });

  it('still follows the slug when a workflow is opened', () => {
    // The behaviour ticket 23 added, which this must not cost: opening a
    // second workflow re-keys the draft so B's edits never land on A.
    tabIsListening();
    openPackageWithADraft(SLUG, 13);
    setOpenSlug('support-triage');

    expect(session.getItem(DRAFT_SESSION_KEY)).toBe(draftIdForSlug('support-triage'));
    stop();
  });
});
