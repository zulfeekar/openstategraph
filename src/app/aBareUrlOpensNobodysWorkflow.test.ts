import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import {
  mostRecentWorkflowId,
  newWriteGuard,
  resolveSession,
  saveWorkflow,
  type KeyValueStore,
} from '@app/workflowStore';
import { DRAFT_SESSION_KEY, hasDraftFor, restoreSessionDraft } from '@app/workflowDrafts';
import { getOpenSlug, readSlugFromSearch, resolveOpenRequest } from '@app/openWorkflow';
import { listRecentDrafts } from '@app/recentDrafts';

/**
 * `install-experience` 23 — **a bare URL opened somebody else's workflow.**
 *
 * `http://localhost:5273/` with no `?w=` of any kind came up holding Chinook
 * Assistant, 13 nodes, `Draft` badge. The documented promise, and the one a
 * stranger arriving at the repository's first screen is owed, is a blank
 * canvas with nothing selected.
 *
 * ## The layer
 *
 * A page load makes **two** decisions, not one. `resolveOpenRequest` decides
 * whether the URL names a document; with no parameter and no open slug it
 * answers `restore`, and it is right to. The second decision is
 * `resolveSession`, and *that* is where "restore" was being spelled **"put
 * this origin's newest draft on screen, whoever left it"** — `mostRecentId`,
 * adopted with `shouldRestore: true`, for any tab whose own `sessionStorage`
 * held no draft id. Every genuinely new tab is such a tab, and so is the first
 * visit after a browser restart.
 *
 * The adoption was not careless: it was written against a defect where each
 * tab open minted a fresh id and left a second full copy of one graph in
 * storage. What was true then and is not true now is that a minted id was
 * followed by an unconditional initial save *and* an import over the top. With
 * no import there is no copy — a fresh tab that mints and restores nothing
 * writes nothing until the user edits, and what it then writes is their new
 * blank document, not a duplicate of anybody's graph.
 *
 * ## Why the test next door is green
 *
 * `aBlankCanvasNeverOwnsAPackage.test.ts` runs the same two decisions in the
 * same order, and its fixture writes `DRAFT_SESSION_KEY` into `sessionStorage`
 * before every page load — because it is about a **reload**, where restoring
 * is correct. `resolveSession` therefore returns on its *first* branch every
 * time and the adoption limb is never entered by that file at all.
 *
 * The two are different questions and both are worth having: what a canvas
 * may *claim* once it is on screen, and whether a bare URL puts a previous
 * session's document there in the first place.
 *
 * ## Nothing is thrown away
 *
 * The draft is not deleted, not swept, and not rewritten. It stops being
 * adopted, and it becomes reachable on purpose instead — `listRecentDrafts`,
 * surfaced as *Unsaved in this browser* in the Workflows panel.
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
}

const DRAFT_ID = 'wf-1788075804900';

describe('install-experience 23 — a bare URL opens nobody’s workflow', () => {
  let local: FakeStore;
  let session: FakeStore;

  beforeEach(() => {
    local = new FakeStore();
    session = new FakeStore();
    (globalThis as Record<string, unknown>)['localStorage'] = local;
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
  });

  /** The 13-node draft the owner found on screen, left in this browser. */
  function aPreviousSessionsDraft(): string {
    const authored = new Workbench();
    authored.model.setName('Chinook Assistant');
    for (let i = 0; i < 13; i += 1) addNode(authored, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    const written = saveWorkflow(
      local,
      DRAFT_ID,
      authored.model,
      authored.serializer,
      newWriteGuard(),
    );
    expect(written.ok).toBe(true);
    return local.getItem(`openstategraph-workflow-${DRAFT_ID}`) ?? '';
  }

  /**
   * The two decisions `WorkbenchContext` runs on a page load, in its order —
   * and nothing else. `search` is the query string; the tab's own
   * `sessionStorage` is whatever the test left in it.
   */
  function pageLoad(search: string): { workbench: Workbench; notice: string | undefined } {
    const workbench = new Workbench();
    const request = resolveOpenRequest({
      urlSlug: readSlugFromSearch(search),
      openSlug: getOpenSlug(),
      hasDraft: hasDraftFor(getOpenSlug(), local),
    });
    expect(request.action).toBe('restore');

    const plan = resolveSession({
      sessionId: session.getItem(DRAFT_SESSION_KEY),
      mostRecentId: mostRecentWorkflowId(local),
      mintId: () => 'wf-minted',
    });
    restoreSessionDraft(plan, workbench, newWriteGuard(), local);
    session.setItem(DRAFT_SESSION_KEY, plan.id);
    return { workbench, notice: plan.notice };
  }

  it('leaves the canvas blank when the tab never opened anything', () => {
    const bytes = aPreviousSessionsDraft();

    const { workbench } = pageLoad('');

    expect(workbench.model.nodes().length).toBe(0);
    // …and the draft is exactly where its author left it.
    expect(local.getItem(`openstategraph-workflow-${DRAFT_ID}`)).toBe(bytes);
  });

  it('says where the unsaved work went, rather than leaving it silent', () => {
    aPreviousSessionsDraft();

    const { notice } = pageLoad('');

    expect(notice).toMatch(/unsaved/i);
    expect(notice).toMatch(/workflows/i);
  });

  it('says nothing at all when this browser holds no draft', () => {
    const { workbench, notice } = pageLoad('');

    expect(workbench.model.nodes().length).toBe(0);
    expect(notice).toBeUndefined();
  });

  it('still restores when the same tab reloads', () => {
    // The case the adoption was confused with, and the one that must not
    // regress: ⌘R keeps `sessionStorage`, so the tab is still holding its own
    // document and gets it back.
    aPreviousSessionsDraft();
    session.setItem(DRAFT_SESSION_KEY, DRAFT_ID);

    const { workbench } = pageLoad('');

    expect(workbench.model.nodes().length).toBe(13);
  });

  it('offers the draft back by name, deliberately', () => {
    aPreviousSessionsDraft();
    pageLoad('');

    const recent = listRecentDrafts(local);
    expect(recent.map((draft) => draft.id)).toContain(DRAFT_ID);
    const draft = recent.find((entry) => entry.id === DRAFT_ID);
    expect(draft?.name).toBe('Chinook Assistant');
    // A scratch draft, so there is no package to open instead of it — which is
    // exactly why an affordance had to exist before the adoption could go.
    expect(draft?.slug).toBeNull();

    const workbench = new Workbench();
    const report = restoreSessionDraft(
      { id: DRAFT_ID, shouldRestore: true },
      workbench,
      newWriteGuard(),
      local,
    );
    expect(report.restored).toBe(true);
    expect(workbench.model.nodes().length).toBe(13);
  });

  it('lists a package’s draft with the slug that reopens it', () => {
    const authored = new Workbench();
    authored.model.setName('Chinook Assistant');
    addNode(authored, TYPE.textInput, { at: { x: 0, y: 0 } });
    saveWorkflow(
      local,
      'slug-chinook-assistant',
      authored.model,
      authored.serializer,
      newWriteGuard(),
    );

    const draft = listRecentDrafts(local).find((entry) => entry.id === 'slug-chinook-assistant');
    expect(draft?.slug).toBe('chinook-assistant');
  });
});
