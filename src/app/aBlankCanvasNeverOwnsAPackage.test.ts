import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import {
  claimSession,
  mostRecentWorkflowId,
  newWriteGuard,
  resolveSession,
  saveWorkflow,
  type KeyValueStore,
} from '@app/workflowStore';
import {
  DRAFT_SESSION_KEY,
  draftIdForSlug,
  hasDraftFor,
  restoreSessionDraft,
} from '@app/workflowDrafts';
import {
  getOpenSlug,
  readSlugFromSearch,
  resolveOpenRequest,
  setOpenSlug,
} from '@app/openWorkflow';
import {
  baselineSlugAfterRestore,
  ensureDiskBaseline,
  forgetDiskDocument,
  writeOpenWorkflowToDisk,
} from '@app/diskAutosave';
import { loadWorkflowIntoEditor } from '@view/workflow/loadWorkflowIntoEditor';
import { Ok, type Result } from '@core/kernel/Result';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';

/**
 * `production-ready` 71 — **a blank document overwrote a package, and nobody
 * pressed Save.**
 *
 * Found in a user-seat walk. `workflows/chinook-assistant/workflow.json` — 13
 * nodes — was replaced on disk by a 1-node document called `AI Workflow` — the
 * editor's default name at the time, which `say-it-on-the-surface/09`
 * has since made `Untitled` so that a document nobody named cannot look
 * like one somebody did. The
 * server log carried the write and no Save had been pressed:
 *
 *     INFO: "PUT /api/workflows/chinook-assistant HTTP/1.1" 200 OK
 *
 * ## The seam, and why the guard that should have caught it did not
 *
 * Disk autosave already has the right rule, stated at `writeOpenWorkflowToDisk`:
 * **never write a package this page has not opened.** It is enforced by
 * requiring a `lastWritten` baseline, which only the load path records — and
 * `ensureDiskBaseline` adds the one honest exception, a *reload of the
 * workflow already open*, where nothing re-fetches and so nothing would ever
 * baseline.
 *
 * `WorkbenchContext` gates that exception on having restored a document, and
 * the comment there names this exact hazard:
 *
 * > A page that seeds the demo instead — no draft to restore — can still find
 * > a slug in `sessionStorage` from a previous visit. Baselining there would
 * > hand autosave a package it is allowed to write while the model holds a
 * > demo, and the next tick would write the demo into that package.
 *
 * The comment is right and the gate did not implement it. It read
 * `session.shouldRestore` — the *intent* to restore — not whether a document
 * actually arrived. With a slug in `sessionStorage` and the draft gone,
 * `shouldRestore` is true, `readWorkflow` returns `missing`, nothing is
 * imported, the canvas stays blank, and the baseline is seeded anyway.
 *
 * **`shouldRestore` is not `restored`**, and that one word is the whole defect.
 *
 * ## The page load this reproduces
 *
 * No `?w=` in the URL — `resolveOpenRequest`'s documented "no parameter →
 * restore" branch, whose `hasDraft` escape hatch (ticket 49) is gated on
 * `urlSlug !== null` and therefore does not apply. `sessionStorage` survives
 * from the previous visit and still names the package.
 *
 * Sibling of ticket 49, which was the same shape one layer up: *"dragging one
 * node in to see what is wrong autosaves that empty canvas over the package.
 * 1 826 bytes became 586."*
 *
 * ## What this file does **not** reach, and why it was green while a bare URL
 * opened somebody else's workflow (`install-experience` 23)
 *
 * A page load makes two decisions and this file runs both. It is honest about
 * the first — no `?w=`, `resolveOpenRequest` answers `restore` — and silent
 * about the second, which is `resolveSession`, and which is where "restore"
 * was being spelled *"open this origin's newest draft, whoever left it"*.
 *
 * `aPreviousVisitTo` writes `DRAFT_SESSION_KEY` into `sessionStorage` before
 * every page load here, and it is right to: this file is about a **reload**,
 * where the tab genuinely had a document and restoring it is correct. But
 * `resolveSession` returns on its *first* branch whenever a session id is
 * present, so the adoption limb below it was never entered by this file at
 * all. The reported defect is a **fresh** tab — empty `sessionStorage`, which
 * is every new tab and every first visit after a browser restart.
 *
 * Two different questions, and both are worth having: what a canvas may
 * *claim* once it is on screen (here), and whether a bare URL puts a previous
 * session's document there in the first place
 * (`aBareUrlOpensNobodysWorkflow.test.ts`).
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

describe('production-ready 71 — a blank canvas must not own a package', () => {
  let local: FakeStore;
  let session: FakeStore;
  /** Every document the fake backend was asked to write, in order. */
  let written: { slug: string; nodes: number }[];

  beforeEach(() => {
    local = new FakeStore();
    session = new FakeStore();
    written = [];
    (globalThis as Record<string, unknown>)['localStorage'] = local;
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
    forgetDiskDocument(SLUG);
  });

  /** A backend holding one package, and recording anything written to it. */
  function backend(document: unknown): IWorkflowFileClient {
    return {
      load: (): Promise<Result<unknown, string>> => Promise.resolve(Ok(document)),
      capabilities: () =>
        Promise.resolve(
          Ok({ tools: [], functions: [], pluginTools: [], ambientTools: [], warnings: [] }),
        ),
      summary: () => Promise.resolve(Ok(null)),
      save: (slug: string, _name: string, doc: unknown): Promise<Result<unknown, string>> => {
        const nodes = (doc as { nodes?: unknown[] })?.nodes?.length ?? 0;
        written.push({ slug, nodes });
        return Promise.resolve(Ok(doc));
      },
    } as unknown as IWorkflowFileClient;
  }

  /** The package as the user left it, and the storage a previous visit left. */
  function aPreviousVisitTo(slug: string, nodes: number): unknown {
    const authored = new Workbench();
    authored.model.setName('Chinook Assistant');
    for (let i = 0; i < nodes; i += 1) {
      addNode(authored, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    }
    const onDisk = JSON.parse(authored.serializer.toJSONString(authored.model)) as unknown;
    setOpenSlug(slug);
    session.setItem(DRAFT_SESSION_KEY, draftIdForSlug(slug));
    return onDisk;
  }

  /**
   * A page load with **no `?w=`**, running the two decisions `WorkbenchContext`
   * runs, in its order — and nothing else. Returns what reached the canvas.
   */
  async function pageLoadWithNoParameter(client: IWorkflowFileClient): Promise<Workbench> {
    const workbench = new Workbench();
    const writer = newWriteGuard();

    const request = resolveOpenRequest({
      urlSlug: readSlugFromSearch(''),
      openSlug: getOpenSlug(),
      hasDraft: hasDraftFor(getOpenSlug(), local),
    });
    if (request.action === 'fetch') {
      const loaded = await loadWorkflowIntoEditor(request.slug, client, workbench);
      expect(loaded.ok).toBe(true);
      return workbench;
    }
    const plan = resolveSession({
      sessionId: session.getItem(DRAFT_SESSION_KEY),
      mostRecentId: mostRecentWorkflowId(local),
      mintId: () => `wf-${Date.now()}`,
    });

    // The line under test, and the only one this test reimplements nothing of:
    // `restoreSessionDraft` reports what actually reached the canvas, and the
    // baseline is gated on that rather than on the plan.
    const outcome = restoreSessionDraft(plan, workbench, writer, local);
    session.setItem(DRAFT_SESSION_KEY, plan.id);

    // The gate itself, called rather than restated — a test that reimplements
    // the decision it is checking proves only that the test agrees with
    // itself. Verified by mutation: blanking the guard inside
    // `baselineSlugAfterRestore` turns the first case below red.
    const baseline = baselineSlugAfterRestore(outcome, getOpenSlug());
    if (baseline !== null)
      await ensureDiskBaseline(baseline, client, workbench.serializer, workbench.model);
    return workbench;
  }

  it('shows the package rather than a blank canvas when the draft is gone', async () => {
    // Ticket 49's rule — **a missing draft is never an empty canvas** — applied
    // to the branch it did not cover. The user is looking at their workflow, so
    // there is no blank document for anything downstream to write or to draft.
    const onDisk = aPreviousVisitTo(SLUG, 13);
    const client = backend(onDisk);

    const workbench = await pageLoadWithNoParameter(client);

    expect(workbench.model.nodes().length).toBe(13);
    expect(written).toEqual([]); // opening a workflow never writes it
  });

  it('does not write a blank canvas over the package whose slug survived', async () => {
    // The second guard, and it earns its place: the first stops the blank
    // canvas appearing, this stops a blank canvas *that appeared some other
    // way* from being written. A live re-run of the fix is what showed one
    // layer alone was not enough.
    const onDisk = aPreviousVisitTo(SLUG, 13);
    const client = backend(onDisk);
    const workbench = new Workbench();

    const report = restoreSessionDraft(
      { id: draftIdForSlug(SLUG), shouldRestore: true },
      workbench,
      newWriteGuard(),
      local,
    );
    const baseline = baselineSlugAfterRestore(report, getOpenSlug());
    if (baseline !== null)
      await ensureDiskBaseline(baseline, client, workbench.serializer, workbench.model);

    // The user, seeing a blank canvas, drags one node in to find out why.
    addNode(workbench, TYPE.textInput, { at: { x: 0, y: 0 } });
    const result = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      session,
    );

    expect(result.kind).toBe('skipped');
    expect(written).toEqual([]);
  });

  it('still writes when a draft really was restored', async () => {
    // The exception `ensureDiskBaseline` exists for must survive the fix: a
    // reload that genuinely restores this browser's edits still autosaves.
    //
    // **The draft is the file here, and since `osg-agent-experience/68` that
    // is load-bearing rather than incidental.** It used to be a second
    // thirteen-node Workbench, which reads as the same document and is not
    // one — the node ids are minted per model — so this case was silently
    // exercising a draft that differed from disk. That is now the conflict
    // path, which writes nothing until the user chooses, and it is covered by
    // `aReloadedTabAsksBeforeItOverwritesTheFile.test.ts`. What belongs here
    // is the ordinary reload: a tab whose last edit was autosaved, whose draft
    // and file agree, and which must go on saving in silence.
    const drafted = new Workbench();
    drafted.model.setName('Chinook Assistant');
    for (let i = 0; i < 13; i += 1) addNode(drafted, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    const onDisk = JSON.parse(drafted.serializer.toJSONString(drafted.model)) as unknown;
    setOpenSlug(SLUG);
    session.setItem(DRAFT_SESSION_KEY, draftIdForSlug(SLUG));
    const writer = newWriteGuard();
    claimSession(local, draftIdForSlug(SLUG), writer);
    expect(
      saveWorkflow(local, draftIdForSlug(SLUG), drafted.model, drafted.serializer, writer).ok,
    ).toBe(true);

    const client = backend(onDisk);
    const workbench = await pageLoadWithNoParameter(client);
    expect(workbench.model.nodes().length).toBe(13);

    addNode(workbench, TYPE.textInput, { at: { x: 99, y: 99 } });
    const result = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      session,
    );

    expect(result.kind).toBe('saved');
    expect(written.map((w) => w.slug)).toEqual([SLUG]);
  });

  it('reports the missing draft honestly rather than as a restore', () => {
    aPreviousVisitTo(SLUG, 13);
    const workbench = new Workbench();
    const outcome = restoreSessionDraft(
      { id: draftIdForSlug(SLUG), shouldRestore: true },
      workbench,
      newWriteGuard(),
      local,
    );
    expect(outcome.restored).toBe(false);
    expect(outcome.notice).toBeUndefined();
  });
});
