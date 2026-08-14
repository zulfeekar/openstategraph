import { afterEach, describe, expect, it, vi } from 'vitest';
import { Err, Ok } from '@core/kernel/Result';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import { Workbench } from '@app/Workbench';
import {
  diskAutosaveTarget,
  forgetDiskDocument,
  rememberDiskDocument,
  writeOpenWorkflowToDisk,
} from './diskAutosave';
import { CURRENT_SLUG_KEY, getKnownSavedAt, recordKnownSavedAt } from './workflowFileWatch';
import { OPEN_ADDRESS_KEY } from './openAddress';

/**
 * the-editor-makes-a-real-package ticket 02.
 *
 * The owner, three times: *"when a workflow is created, edited, modified, as a
 * developer I would expect to see the immediate result on the workflow folder
 * or package inside the codebase."* It did not. The editor autosaved to
 * `localStorage` and only an explicit Save — in a panel most people never
 * found — ever touched disk.
 *
 * The sharpest edge was not the missing write but the disagreement it caused:
 * loading prefers the browser draft over the file, so a developer could edit
 * the canvas, see `git diff` report nothing, reopen, and find the editor
 * showing something the file did not contain.
 */
const storageWith = (slug: string | null): Pick<Storage, 'getItem'> => ({
  getItem: (key: string) => (key === CURRENT_SLUG_KEY ? slug : null),
});

// The suite runs in node, so there is no DOM storage — the same stub
// `openAddress.test.ts` uses, for the same reason.
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
  // The baseline is module state, so it outlives a test unless dropped.
  forgetDiskDocument('demo');
});

describe('what disk autosave will and will not write', () => {
  it('writes the open slug', () => {
    expect(diskAutosaveTarget(storageWith('chinook-assistant'))).toBe('chinook-assistant');
  });

  it('writes nothing for a workflow that has never been saved', () => {
    // The backend mints the slug on first save, because a client that invents
    // one from a name silently overwrites somebody else's package. So a new
    // canvas still needs one deliberate Save, and everything after it is
    // automatic.
    expect(diskAutosaveTarget(storageWith(null))).toBeNull();
    expect(diskAutosaveTarget(storageWith('   '))).toBeNull();
  });

  it('writes nothing while a mount instance is open', () => {
    // What is on screen is a *derived* document — the package plus this
    // mount's overrides — so writing it back to the package would burn those
    // overrides into the shared definition and hit every other mount.
    sessionStorage.setItem(OPEN_ADDRESS_KEY, 'concierge/wf-music');
    expect(diskAutosaveTarget(storageWith('chinook-assistant'))).toBeNull();
  });
});

describe('writing the open workflow to its package', () => {
  const workbench = () => new Workbench();

  it('sends the slug, the name and the document', async () => {
    const save = vi.fn(async (_slug: string, _name: string, _document: unknown) => Ok(undefined));
    const bench = workbench();
    // A baseline means "this page opened this package"; without one nothing is
    // written at all. An empty document stands in for whatever was on disk.
    rememberDiskDocument('demo', 'whatever was on disk', {});

    const outcome = await writeOpenWorkflowToDisk(
      { save } as unknown as Pick<IWorkflowFileClient, 'save'>,
      bench.model,
      bench.serializer,
      storageWith('demo'),
    );

    expect(outcome).toEqual({ kind: 'saved' });
    expect(save).toHaveBeenCalledOnce();
    const [slug, name, document] = save.mock.calls[0]!;
    expect(slug).toBe('demo');
    expect(name).toBe(bench.model.name);
    expect(document).toHaveProperty('nodes');
  });

  it('does not call the backend when there is nowhere to write', async () => {
    const save = vi.fn(async () => Ok(undefined));
    const bench = workbench();

    const outcome = await writeOpenWorkflowToDisk(
      { save },
      bench.model,
      bench.serializer,
      storageWith(null),
    );

    expect(outcome).toEqual({ kind: 'skipped' });
    expect(save).not.toHaveBeenCalled();
  });

  it('attributes its own write, so the file watch does not warn about it', async () => {
    // Without this the watcher compares the file's new `savedAt` against a
    // stale baseline and reports "changed underneath you" — once per edit,
    // about the editor's own writes.
    recordKnownSavedAt('demo', '2026-08-13T00:00:00Z');
    const bench = workbench();
    rememberDiskDocument('demo', 'whatever was on disk', {});

    await writeOpenWorkflowToDisk(
      { save: async () => Ok(undefined) },
      bench.model,
      bench.serializer,
      storageWith('demo'),
    );

    // Undefined means "no baseline", which the watcher adopts silently on its
    // next poll rather than treating as an external change.
    expect(getKnownSavedAt('demo')).toBeUndefined();
  });

  it('reports a failure instead of throwing, and keeps the baseline', async () => {
    // A failed write must not look like a successful one to the watcher.
    recordKnownSavedAt('demo', '2026-08-13T00:00:00Z');
    const bench = workbench();
    rememberDiskDocument('demo', 'whatever was on disk', {});

    const outcome = await writeOpenWorkflowToDisk(
      { save: async () => Err('the disk is full') },
      bench.model,
      bench.serializer,
      storageWith('demo'),
    );

    expect(outcome).toEqual({ kind: 'failed', reason: 'the disk is full' });
    expect(getKnownSavedAt('demo')).toBe('2026-08-13T00:00:00Z');
  });
});

describe('never write a package this page has not opened', () => {
  it('skips a slug with no baseline, however loudly sessionStorage names it', async () => {
    // The race this closes, which is the dangerous one. `getOpenSlug()` reads
    // sessionStorage, which survives a reload — so on a deep link the open
    // slug names the target package from the first paint, while the document
    // itself arrives over the network some time later. In between, the model
    // holds the seeded demo. A load slower than the autosave debounce would
    // have written that demo straight into somebody's workflow.
    const save = vi.fn(async () => Ok(undefined));
    const bench = new Workbench();

    const outcome = await writeOpenWorkflowToDisk(
      { save } as unknown as Pick<IWorkflowFileClient, 'save'>,
      bench.model,
      bench.serializer,
      storageWith('someone-elses-package'),
    );

    expect(outcome).toEqual({ kind: 'skipped' });
    expect(save).not.toHaveBeenCalled();
  });

  it('writes once the load has said what is on disk', async () => {
    const save = vi.fn(async () => Ok(undefined));
    const client = { save } as unknown as Pick<IWorkflowFileClient, 'save'>;
    const bench = new Workbench();
    const storage = storageWith('demo');

    expect(await writeOpenWorkflowToDisk(client, bench.model, bench.serializer, storage)).toEqual({
      kind: 'skipped',
    });

    rememberDiskDocument('demo', 'whatever was on disk', {});
    expect(await writeOpenWorkflowToDisk(client, bench.model, bench.serializer, storage)).toEqual({
      kind: 'saved',
    });
  });
});

describe('opening a workflow is not an edit', () => {
  // The defect this guards, found in the browser: autosave listens to
  // `controller.onChange`, and a *load* fires that too — so merely opening a
  // package rewrote its file with an identical document and a fresh
  // `savedAt`. Browsing three workflows left three modified files in
  // `git status`, and a diff that is pure noise stops being read.
  it('does not write a document identical to the one just loaded', async () => {
    const save = vi.fn(async () => Ok(undefined));
    const bench = new Workbench();
    rememberDiskDocument('demo', bench.model.name, bench.serializer.serialize(bench.model));

    const outcome = await writeOpenWorkflowToDisk(
      { save } as unknown as Pick<IWorkflowFileClient, 'save'>,
      bench.model,
      bench.serializer,
      storageWith('demo'),
    );

    expect(outcome).toEqual({ kind: 'unchanged' });
    expect(save).not.toHaveBeenCalled();
  });

  it('writes once a real edit lands, and not again until the next one', async () => {
    const save = vi.fn(async () => Ok(undefined));
    const client = { save } as unknown as Pick<IWorkflowFileClient, 'save'>;
    const bench = new Workbench();
    rememberDiskDocument('demo', bench.model.name, bench.serializer.serialize(bench.model));

    bench.model.setName('Renamed');
    expect(
      await writeOpenWorkflowToDisk(client, bench.model, bench.serializer, storageWith('demo')),
    ).toEqual({ kind: 'saved' });

    // A second autosave tick with nothing further changed must stay silent —
    // otherwise every keystroke anywhere in the app rewrites the package.
    expect(
      await writeOpenWorkflowToDisk(client, bench.model, bench.serializer, storageWith('demo')),
    ).toEqual({ kind: 'unchanged' });
    expect(save).toHaveBeenCalledOnce();
  });

  it('counts a rename as a change, though no node moved', async () => {
    // The name is stored beside the document, not inside it, so comparing
    // documents alone would have missed this entirely.
    const save = vi.fn(async (_slug: string, _name: string, _document: unknown) => Ok(undefined));
    const bench = new Workbench();
    rememberDiskDocument('demo', bench.model.name, bench.serializer.serialize(bench.model));
    bench.model.setName('A different name');

    const outcome = await writeOpenWorkflowToDisk(
      { save } as unknown as Pick<IWorkflowFileClient, 'save'>,
      bench.model,
      bench.serializer,
      storageWith('demo'),
    );

    expect(outcome).toEqual({ kind: 'saved' });
    expect(save.mock.calls[0]![1]).toBe('A different name');
  });
});

describe('the write loop', () => {
  // Found in the browser, not in a test: with an idle editor and nothing
  // touched, `workflows/chinook-assistant/workflow.json` was rewritten every
  // few seconds for as long as the tab stayed open. The documents were
  // byte-identical; only `savedAt` moved. The cause was comparing
  // `JSON.stringify` output, which encodes *insertion* order — so two equal
  // documents assembled by different code paths compared unequal, every
  // autosave wrote, and the file watch's poll kept the cycle turning.
  it('does not write because a card re-measured itself', async () => {
    // The loop as actually observed: the Get Table Schema card's height
    // alternated between 118 and 200 as its schema list settled. Height is
    // written back by a ResizeObserver — nobody authored it — so it must not
    // be able to dirty a package file.
    const save = vi.fn(async () => Ok(undefined));
    const client = { save } as unknown as Pick<IWorkflowFileClient, 'save'>;
    const bench = new Workbench();

    let tall = false;
    const remeasuring = {
      serialize: (model: WorkflowModel) => {
        tall = !tall;
        const doc = bench.serializer.serialize(model) as unknown as {
          nodes: Record<string, unknown>[];
        };
        return {
          ...doc,
          nodes: doc.nodes.map((node) => ({
            ...node,
            size: { width: 252, height: tall ? 200 : 118 },
          })),
        } as unknown as ReturnType<WorkflowSerializer['serialize']>;
      },
    } as unknown as WorkflowSerializer;

    rememberDiskDocument('demo', bench.model.name, remeasuring.serialize(bench.model));
    for (let tick = 0; tick < 4; tick += 1) {
      expect(
        await writeOpenWorkflowToDisk(client, bench.model, remeasuring, storageWith('demo')),
      ).toEqual({ kind: 'unchanged' });
    }
    expect(save).not.toHaveBeenCalled();
  });

  it('treats two equal documents with different key order as unchanged', async () => {
    const save = vi.fn(async () => Ok(undefined));
    const client = { save } as unknown as Pick<IWorkflowFileClient, 'save'>;
    const bench = new Workbench();

    // A serializer whose key order differs between calls, which is precisely
    // what the real one does not promise.
    let flip = false;
    const shuffling = {
      serialize: (model: WorkflowModel) => {
        flip = !flip;
        const doc = bench.serializer.serialize(model) as unknown as Record<string, unknown>;
        const keys = Object.keys(doc);
        return Object.fromEntries(
          (flip ? keys : [...keys].reverse()).map((k) => [k, doc[k]]),
        ) as unknown as ReturnType<WorkflowSerializer['serialize']>;
      },
    } as unknown as WorkflowSerializer;

    rememberDiskDocument('demo', bench.model.name, shuffling.serialize(bench.model));
    for (let tick = 0; tick < 4; tick += 1) {
      expect(
        await writeOpenWorkflowToDisk(client, bench.model, shuffling, storageWith('demo')),
      ).toEqual({ kind: 'unchanged' });
    }
    expect(save).not.toHaveBeenCalled();
  });
});
