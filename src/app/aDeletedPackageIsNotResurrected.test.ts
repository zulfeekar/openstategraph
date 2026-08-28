import { afterEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import { WorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import {
  abandonDeletedWorkflow,
  forgetDiskDocument,
  rememberDiskDocument,
  writeOpenWorkflowToDisk,
} from './diskAutosave';
import { CURRENT_SLUG_KEY } from './workflowFileWatch';
import { clearOpenSlug, getOpenSlug, setOpenSlug } from './openWorkflow';

/**
 * launch-readiness ticket 147 — **a data-loss blocker, reproduced live twice.**
 *
 * Two tabs, one workflow. Tab A deletes it and the directory goes. Tab B does
 * not refresh, and somebody types **one character**. Disk autosave fires,
 * `PUT /api/workflows/<slug>` re-creates the directory, and the package comes
 * back holding `workflow.json` and `AGENTS.md` and nothing else: `tools/`,
 * `functions/`, `tests/`, `skills/`, `middlewares/` and `data/` — the user's
 * own Python — are gone for good, and `published` is reset to `False`. No
 * prompt, no toast, no error. The tab looked like it saved successfully,
 * because it did.
 *
 * ## Why the test drives the real client against a store-shaped fake
 *
 * The guard is a flag on the request, and a test asserting the flag is sent
 * would stay green against a backend that ignored it — while a test of the
 * backend alone (there is one:
 * `backend/tests/test_a_deleted_package_stays_deleted.py`, real store, real
 * directory, real `tools/probe_tool.py`) stays green against a writer that
 * never sets it. The defect lives *between* them, so this half drives the
 * editor's own writer through the real `WorkflowFileClient` against a fake
 * that behaves the way the documented route does: **a `PUT` at a free slug
 * creates a package, unless the body asks it not to.**
 *
 * That is what makes the first test a reproduction rather than an assertion
 * about an implementation: delete the package out from under the open writer,
 * type, and ask what the store holds.
 */

/** A backend, reduced to the one behaviour this ticket is about. */
class StoreShapedBackend {
  /** slug → the package's files. A deleted package is an absent key. */
  readonly packages = new Map<string, Set<string>>();

  create(slug: string): void {
    this.packages.set(slug, new Set(['workflow.json', 'AGENTS.md', 'tools/probe_tool.py']));
  }

  delete(slug: string): void {
    this.packages.delete(slug);
  }

  readonly fetch = async (url: string, init?: RequestInit): Promise<Response> => {
    const slug = decodeURIComponent(url.split('/api/workflows/')[1] ?? '');
    if (init?.method !== 'PUT') return new Response(null, { status: 405 });
    const body = JSON.parse(String(init.body)) as { must_exist?: boolean };
    if (!this.packages.has(slug)) {
      // The route's own words: *"It still creates one if the slug is free"* —
      // and what it creates is a package with a document and nothing else.
      if (body.must_exist === true) {
        return new Response(JSON.stringify({ detail: `No workflow named '${slug}'` }), {
          status: 404,
        });
      }
      this.packages.set(slug, new Set(['workflow.json', 'AGENTS.md']));
    }
    return new Response(JSON.stringify({ slug, name: 'Probe', document: {} }), { status: 200 });
  };
}

// The suite runs in node, so there is no DOM storage.
const store = new Map<string, string>();
(globalThis as { sessionStorage?: unknown }).sessionStorage = {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
  key: () => null,
  length: 0,
} satisfies Storage;

afterEach(() => {
  store.clear();
  forgetDiskDocument('probe');
});

/** A tab with `probe` open, edited once since it was loaded. */
function anOpenTabEditing(slug: string): Workbench {
  const workbench = new Workbench();
  workbench.model.setName('Probe');
  store.set(CURRENT_SLUG_KEY, slug);
  rememberDiskDocument(
    slug,
    'Probe',
    JSON.parse(workbench.serializer.toJSONString(workbench.model)) as unknown,
    workbench.serializer,
  );
  addNode(workbench, TYPE.agent);
  return workbench;
}

describe('a stale tab writing to a slug it has been told is gone', () => {
  it('does not re-create the package, so nothing comes back hollow', async () => {
    const backend = new StoreShapedBackend();
    backend.create('probe');
    const client = new WorkflowFileClient('', backend.fetch, null);
    const workbench = anOpenTabEditing('probe');

    backend.delete('probe'); // the other tab's delete

    const outcome = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      sessionStorage,
    );

    expect(outcome.kind).toBe('failed');
    // The whole harm in one assertion. Before the guard this read
    // `['workflow.json', 'AGENTS.md']` — the package back in every listing,
    // carrying a live workflow's slug, with the Python that made it work gone.
    expect(backend.packages.has('probe')).toBe(false);
  });

  it('still writes a package that is there', async () => {
    const backend = new StoreShapedBackend();
    backend.create('probe');
    const client = new WorkflowFileClient('', backend.fetch, null);
    const workbench = anOpenTabEditing('probe');

    const outcome = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      sessionStorage,
    );

    expect(outcome).toEqual({ kind: 'saved' });
    expect(backend.packages.get('probe')).toContain('tools/probe_tool.py');
  });
});

describe('what the tab does once it knows', () => {
  afterEach(() => clearOpenSlug());

  it('disarms the writer, so the next keystroke writes nothing at all', async () => {
    const backend = new StoreShapedBackend();
    backend.create('probe');
    const client = new WorkflowFileClient('', backend.fetch, null);
    const workbench = anOpenTabEditing('probe');
    backend.delete('probe');

    abandonDeletedWorkflow('probe');

    const outcome = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      sessionStorage,
    );
    // Not `failed` — nothing was even attempted. The refusal above is the
    // safety net for the seconds before the watch notices; this is the tab
    // acting on what it was told.
    expect(outcome).toEqual({ kind: 'skipped' });
    expect(backend.packages.has('probe')).toBe(false);
  });

  it('releases the identity, so the document on screen can become a new package', () => {
    setOpenSlug('probe');
    const workbench = anOpenTabEditing('probe');

    abandonDeletedWorkflow('probe');

    // A slug is minted at first save and frozen, because a slug that moves
    // renames a directory — so the path forward for a document whose package
    // is gone is a *new* slug, which is exactly what `saveWorkflow` does when
    // nothing is open. The document itself is untouched: dropping it would be
    // this ticket's data loss with the arrow reversed.
    expect(getOpenSlug()).toBeNull();
    expect(workbench.model.nodes().length).toBe(1);
  });

  it('leaves other packages alone', async () => {
    const backend = new StoreShapedBackend();
    backend.create('probe');
    backend.create('other');
    const client = new WorkflowFileClient('', backend.fetch, null);

    abandonDeletedWorkflow('other');

    const workbench = anOpenTabEditing('probe');
    const outcome = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      sessionStorage,
    );
    expect(outcome).toEqual({ kind: 'saved' });
  });
});
