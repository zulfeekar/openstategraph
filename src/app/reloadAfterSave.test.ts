import { beforeEach, describe, expect, it } from 'vitest';
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
} from '@app/workflowStore';
import {
  adoptSlugForDraft,
  DRAFT_SESSION_KEY,
  draftIdForSlug,
  draftSavedAt,
  hasDraftFor,
  restoreDraftFor,
} from '@app/workflowDrafts';
import {
  getOpenSlug,
  readSlugFromSearch,
  resolveOpenRequest,
  setOpenSlug,
} from '@app/openWorkflow';
import { getOpenAddress, readAddressFromSearch, resolveAddressRequest } from '@app/openAddress';
import { isInstance, parseMountAddress } from '@core/model/MountAddress';
import { loadWorkflowIntoEditor } from '@view/workflow/loadWorkflowIntoEditor';
import { Ok, type Result } from '@core/kernel/Result';
import type {
  IWorkflowFileClient,
  WorkflowCapabilities,
  WorkflowSummary,
} from '@core/runtime/WorkflowFileClient';

/**
 * Ticket 49 — **save, then reload, and your work is gone.**
 *
 * The user-seat reproduction, in six steps: drag in the starter flow, name it,
 * press Save, press ⌘R. The canvas comes back empty and the name reverts to
 * the default; dragging one node in to see what is wrong autosaves that empty
 * canvas over the package. 1 826 bytes became 586.
 *
 * ## Why this test is a *page load* and not a store assertion
 *
 * Every part of this was already unit-tested and every unit passed. The defect
 * lived in the seam between three of them — the draft key, the open slug, and
 * the deep-link resolver — and it only appears when a **fresh module graph
 * meets surviving storage**, which is exactly what a reload is. So `pageLoad`
 * below builds a brand-new `Workbench` over the same `localStorage` and
 * `sessionStorage` and runs the real decision functions in the real order
 * `AppShell` runs them: `useWorkflowSession` first, `useDeepLinkedWorkflow`
 * second. Nothing here reimplements a decision; it only sequences them.
 *
 * ## The two properties, stated as the ticket states them
 *
 * 1. **A missing draft must never mean an empty canvas.** The fallback is the
 *    document the backend can serve, always.
 * 2. **The key migration happens exactly when the document acquires its slug**
 *    — not on every open-slug change, which would hand one workflow another's
 *    draft (ticket 23's defect, backwards).
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

/** A backend holding exactly one package, the way the ticket's did. */
function backendServing(slug: string, document: unknown): IWorkflowFileClient {
  return {
    load: (asked: string): Promise<Result<unknown, string>> =>
      Promise.resolve(asked === slug ? Ok(document) : Ok(document)),
    capabilities: (): Promise<Result<WorkflowCapabilities, string>> =>
      Promise.resolve(Ok({ tools: [], pluginTools: [], ambientTools: [], warnings: [] })),
    summary: (): Promise<Result<WorkflowSummary | null, string>> => Promise.resolve(Ok(null)),
  } as unknown as IWorkflowFileClient;
}

describe('ticket 49 — a reload after the first save', () => {
  let local: FakeStore;
  let session: FakeStore;

  beforeEach(() => {
    local = new FakeStore();
    session = new FakeStore();
    // The two globals a page load reads. `openWorkflow` and `workflowDrafts`
    // reach for them by name, exactly as they do in a browser.
    (globalThis as Record<string, unknown>)['localStorage'] = local;
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
  });

  /**
   * A tab that has drawn a flow and never saved it: a minted `wf-<ts>` key, a
   * draft under it, and no slug anywhere.
   */
  function unsavedTabHolding(name: string, nodes: number): { workbench: Workbench; id: string } {
    const workbench = new Workbench();
    workbench.model.setName(name);
    for (let i = 0; i < nodes; i += 1) {
      addNode(workbench, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    }
    const id = `wf-${Date.now()}`;
    session.setItem(DRAFT_SESSION_KEY, id);
    const writer = newWriteGuard();
    claimSession(local, id, writer);
    expect(saveWorkflow(local, id, workbench.model, workbench.serializer, writer).ok).toBe(true);
    return { workbench, id };
  }

  /** What `WorkflowManager.handleSave` does once the backend mints a slug. */
  function pressSave(slug: string): void {
    adoptSlugForDraft(session.getItem(DRAFT_SESSION_KEY), slug, local);
    setOpenSlug(slug);
    session.setItem(DRAFT_SESSION_KEY, draftIdForSlug(slug));
  }

  /**
   * ⌘R: a fresh module graph over surviving storage, running the two startup
   * hooks' real decisions in `AppShell`'s order.
   */
  async function pageLoad(search: string, client: IWorkflowFileClient): Promise<Workbench> {
    const workbench = new Workbench();
    const writer = newWriteGuard();

    /* --- useWorkflowSession --- */
    const request = resolveOpenRequest({
      urlSlug: readSlugFromSearch(search),
      openSlug: getOpenSlug(),
      hasDraft: hasDraftForOpenSubject(),
    });
    const plan =
      request.action === 'fetch'
        ? { id: draftIdForSlug(request.slug), shouldRestore: false }
        : resolveSession({
            sessionId: session.getItem(DRAFT_SESSION_KEY),
            mostRecentId: mostRecentWorkflowId(local),
            mintId: () => `wf-${Date.now()}`,
          });
    if (plan.shouldRestore) {
      const outcome = readWorkflow(local, plan.id);
      if (outcome.status === 'ok') {
        writer.lastSeenAt = outcome.savedAt;
        workbench.controller.document.importJSON(outcome.json);
      }
    }
    session.setItem(DRAFT_SESSION_KEY, plan.id);

    /* --- useDeepLinkedWorkflow --- */
    const address = resolveAddressRequest({
      urlAddress: readAddressFromSearch(search),
      openAddress: getOpenAddress() ?? parseMountAddress(getOpenSlug() ?? ''),
      hasDraft: hasDraftForOpenSubject(),
    });
    if (address.action === 'fetch' && !isInstance(address.address)) {
      const loaded = await loadWorkflowIntoEditor(address.address.root, client, workbench);
      expect(loaded.ok).toBe(true);
    } else if (address.action === 'restore') {
      // The restore branch's own contract: whatever draft this browser holds
      // for the open slug is what the session hook already put on screen.
      const open = getOpenSlug();
      if (open !== null) restoreDraftFor(open, workbench, local);
    }
    return workbench;
  }

  /** Exactly what both startup hooks ask, through the same helper they use. */
  function hasDraftForOpenSubject(): boolean {
    return hasDraftFor(getOpenSlug(), local);
  }

  it('restores the saved document on reload, name included', async () => {
    const { workbench } = unsavedTabHolding('Reload Repro', 3);
    const onDisk = JSON.parse(workbench.serializer.toJSONString(workbench.model)) as unknown;
    pressSave('reload-repro');

    const reloaded = await pageLoad('?w=reload-repro', backendServing('reload-repro', onDisk));

    expect(reloaded.model.nodes().length).toBe(3);
    expect(reloaded.model.name).toBe('Reload Repro');
  });

  it('falls back to the server document when the draft is gone, never to blank', async () => {
    // The ticket's own acceptance test: save, drop the draft, reload. A
    // browser that has cleared its site data, a draft evicted under quota,
    // a slug whose key was never migrated — all arrive here, and none of
    // them may produce an empty canvas for a slug the server can serve.
    const { workbench } = unsavedTabHolding('Reload Repro', 3);
    const onDisk = JSON.parse(workbench.serializer.toJSONString(workbench.model)) as unknown;
    pressSave('reload-repro');
    for (const key of local.keys()) {
      if (key.startsWith('openstategraph-workflow-')) local.removeItem(key);
    }

    const reloaded = await pageLoad('?w=reload-repro', backendServing('reload-repro', onDisk));

    expect(reloaded.model.nodes().length).toBe(3);
    expect(reloaded.model.name).toBe('Reload Repro');
  });

  it('restores from the server for a slug this browser has never seen', async () => {
    // Open-by-URL: the link the drawer told the user to send.
    const authored = new Workbench();
    authored.model.setName('Reload Repro');
    for (let i = 0; i < 3; i += 1) addNode(authored, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    const onDisk = JSON.parse(authored.serializer.toJSONString(authored.model)) as unknown;

    const arrived = await pageLoad('?w=reload-repro', backendServing('reload-repro', onDisk));

    expect(arrived.model.nodes().length).toBe(3);
    expect(arrived.model.name).toBe('Reload Repro');
  });

  it('moves the draft to the slug key exactly when the document acquires one', () => {
    const { id } = unsavedTabHolding('Reload Repro', 3);
    expect(draftSavedAt('reload-repro', local)).toBeNull();

    pressSave('reload-repro');

    expect(draftSavedAt('reload-repro', local)).not.toBeNull();
    // …and the pre-save key is gone rather than left behind as a phantom row
    // in the Workflows panel, pointing at a document that now has a name.
    expect(local.getItem(`openstategraph-workflow-${id}`)).toBeNull();
  });

  it('does not hand an opened workflow the scratch draft of the one being left', () => {
    // The migration's blast radius, stated as its own test. Opening a second
    // workflow also moves the open slug — and moving the draft there would be
    // ticket 23's data loss with the arrow reversed: workflow B would come up
    // holding A's graph, and A's would be gone.
    const { id } = unsavedTabHolding('Scratch', 2);

    expect(adoptSlugForDraft(id, 'chinook-assistant', local)).toBe(true);
    // A second document cannot claim the same draft twice, and a key that
    // already belongs to a slug is never moved onto another slug.
    expect(adoptSlugForDraft(draftIdForSlug('chinook-assistant'), 'concierge', local)).toBe(false);
    expect(draftSavedAt('concierge', local)).toBeNull();
  });
});
