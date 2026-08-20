import { afterEach, describe, expect, it, vi } from 'vitest';
import { Err, Ok } from '@core/kernel/Result';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import {
  diskAutosaveTarget,
  forgetDiskDocument,
  forgetMountHostDocument,
  rememberDiskDocument,
  rememberMountHostDocument,
  writeOpenMountHostToDisk,
  writeOpenWorkflowToDisk,
} from './diskAutosave';
import { MountContext } from '@core/model/MountContext';
import type { MountAddress } from '@core/model/MountAddress';
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
    rememberDiskDocument('demo', 'whatever was on disk', {}, bench.serializer);

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
    rememberDiskDocument('demo', 'whatever was on disk', {}, bench.serializer);

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
    rememberDiskDocument('demo', 'whatever was on disk', {}, bench.serializer);

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

    rememberDiskDocument('demo', 'whatever was on disk', {}, bench.serializer);
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
    rememberDiskDocument(
      'demo',
      bench.model.name,
      bench.serializer.serialize(bench.model),
      bench.serializer,
    );

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
    rememberDiskDocument(
      'demo',
      bench.model.name,
      bench.serializer.serialize(bench.model),
      bench.serializer,
    );

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
    rememberDiskDocument(
      'demo',
      bench.model.name,
      bench.serializer.serialize(bench.model),
      bench.serializer,
    );
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
    // A node, because the injection below rewrites `doc.nodes` — and on an
    // empty model that maps over nothing. The test was green for years
    // without one and would have stayed green with the strip removed
    // (`production-ready` 69).
    addNode(bench as unknown as Parameters<typeof addNode>[0], TYPE.agent, {
      at: { x: 40, y: 200 },
    });

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

    // The fake serializer stays on the *write* side, where its instability is
    // the point; the baseline is canonicalised by the real one.
    rememberDiskDocument(
      'demo',
      bench.model.name,
      remeasuring.serialize(bench.model),
      bench.serializer,
    );
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

    rememberDiskDocument(
      'demo',
      bench.model.name,
      shuffling.serialize(bench.model),
      bench.serializer,
    );
    for (let tick = 0; tick < 4; tick += 1) {
      expect(
        await writeOpenWorkflowToDisk(client, bench.model, shuffling, storageWith('demo')),
      ).toEqual({ kind: 'unchanged' });
    }
    expect(save).not.toHaveBeenCalled();
  });
});

/**
 * organisms-first-class ticket 44 — the override that was badged and thrown away.
 *
 * Everything upstream of persistence already worked: `SetMountOverrideCommand`
 * wrote `data.overrides` on the retained host document, the card and the
 * inspector badged the field `overridden`, and the model change fired
 * `controller.onChange`. Both sinks that listen to it take `workbench.model`
 * — the *derived child* — and `diskAutosaveTarget` correctly refuses to write
 * that back to the package. So the edit had a signal and no destination: the
 * host was never written, `Back` re-fetched it from disk unchanged, and the
 * override was gone with nothing having said so.
 */
describe('writing an open mount’s host package', () => {
  const address = { root: 'host', mountPath: ['wf-child'] } as const;
  const hostDocument = (overrides?: string) => ({
    name: 'Host',
    nodes: [
      {
        id: 'wf-child',
        type: 'compose.subgraph',
        data: { workflow: 'child', ...(overrides ? { overrides } : {}) },
      },
    ],
  });
  const context = (document: Record<string, unknown>) =>
    new MountContext(address as unknown as MountAddress, document);

  afterEach(() => forgetMountHostDocument('host'));

  it('writes the host, under the host’s slug, when an override lands on it', async () => {
    const save = vi.fn(async (_slug: string, _name: string, _document: unknown) => Ok(undefined));
    const summary = vi.fn(async () => Ok(null));
    const document = hostDocument();
    const mounts = context(document);
    rememberMountHostDocument('host', document);

    mounts.writeOverride('question', 'prompt', 'OVERRIDE TEST');
    const outcome = await writeOpenMountHostToDisk({ save, summary }, mounts);

    expect(outcome).toEqual({ kind: 'saved' });
    const [slug, name, written] = save.mock.calls[0]!;
    expect(slug).toBe('host');
    expect(name).toBe('Host');
    // The value the reload has to find. Not `""`, which is what the mount
    // node's schema default left on disk for as long as this was broken.
    const node = (written as { nodes: Array<{ data: Record<string, unknown> }> }).nodes[0]!;
    expect(JSON.parse(node.data['overrides'] as string)).toEqual({
      question: { prompt: 'OVERRIDE TEST' },
    });
  });

  it('never writes the package the mount points at', async () => {
    const save = vi.fn(async (_slug: string, _name: string, _document: unknown) => Ok(undefined));
    const document = hostDocument();
    const mounts = context(document);
    rememberMountHostDocument('host', document);

    mounts.writeOverride('question', 'prompt', 'OVERRIDE TEST');
    await writeOpenMountHostToDisk({ save, summary: async () => Ok(null) }, mounts);

    // Mount-by-reference is the whole design: the child on disk keeps its own
    // prompt, and every other mount of it is untouched.
    expect(save.mock.calls.map(([slug]) => slug)).toEqual(['host']);
  });

  it('is quiet while the host is not changing', async () => {
    // The child's canvas fires `onChange` for a drag, a selection, a resize —
    // none of which touch the host. Without this the editor would rewrite an
    // unchanged host file every second for as long as the drill-in stayed
    // open, which is the write loop `comparable` exists to prevent.
    const save = vi.fn(async () => Ok(undefined));
    const document = hostDocument();
    const mounts = context(document);
    rememberMountHostDocument('host', document);

    for (let tick = 0; tick < 4; tick += 1) {
      expect(
        await writeOpenMountHostToDisk({ save, summary: async () => Ok(null) }, mounts),
      ).toEqual({ kind: 'unchanged' });
    }
    expect(save).not.toHaveBeenCalled();
  });

  it('carries two mounts of one package with different values', async () => {
    // The `same-package-twice` shape, which is the whole point of an instance:
    // both rows point at `child` by reference, and what differs is stored per
    // mount on the host. One write carries both, because both live in the one
    // document this function writes.
    const save = vi.fn(async (_slug: string, _name: string, _document: unknown) => Ok(undefined));
    const document = {
      name: 'Host',
      nodes: [
        { id: 'm1', type: 'workflow.subgraph', data: { workflow: 'child' } },
        { id: 'm2', type: 'workflow.subgraph', data: { workflow: 'child' } },
      ],
    };
    rememberMountHostDocument('host', document);

    new MountContext({ root: 'host', mountPath: ['m1'] } as MountAddress, document).writeOverride(
      'q',
      'prompt',
      'FIRST',
    );
    const second = new MountContext({ root: 'host', mountPath: ['m2'] } as MountAddress, document);
    second.writeOverride('q', 'prompt', 'SECOND');

    await writeOpenMountHostToDisk({ save, summary: async () => Ok(null) }, second);

    const written = save.mock.calls[0]![2] as { nodes: Array<{ data: Record<string, string> }> };
    expect(JSON.parse(written.nodes[0]!.data['overrides']!)).toEqual({ q: { prompt: 'FIRST' } });
    expect(JSON.parse(written.nodes[1]!.data['overrides']!)).toEqual({ q: { prompt: 'SECOND' } });
  });

  it('writes nothing when no mount is open', async () => {
    const save = vi.fn(async () => Ok(undefined));
    expect(await writeOpenMountHostToDisk({ save, summary: async () => Ok(null) }, null)).toEqual({
      kind: 'skipped',
    });
    expect(save).not.toHaveBeenCalled();
  });

  it('writes nothing before the host has been baselined', async () => {
    // Same rule as the class path: without a baseline the document in memory
    // is not known to have come from this slug, and a blind write of a whole
    // retained document is how somebody else's package gets reverted.
    const save = vi.fn(async () => Ok(undefined));
    const mounts = context(hostDocument());
    mounts.writeOverride('question', 'prompt', 'x');

    expect(await writeOpenMountHostToDisk({ save, summary: async () => Ok(null) }, mounts)).toEqual(
      {
        kind: 'skipped',
      },
    );
    expect(save).not.toHaveBeenCalled();
  });

  it('refuses rather than reverting a host somebody else moved', async () => {
    // The explicit Save has compare-and-set for this; autosave writes the same
    // whole retained document far more often, and silently, so it needs it
    // more rather than less.
    const save = vi.fn(async () => Ok(undefined));
    const summary = vi.fn(async () => Ok({ slug: 'host', name: 'Host', savedAt: 'later' }));
    const document = hostDocument();
    const mounts = context(document);
    rememberMountHostDocument('host', document);
    recordKnownSavedAt('host', 'when-we-opened-it');

    mounts.writeOverride('question', 'prompt', 'OVERRIDE TEST');
    const outcome = await writeOpenMountHostToDisk({ save, summary } as never, mounts);

    expect(outcome.kind).toBe('failed');
    expect(save).not.toHaveBeenCalled();
  });

  it('keeps the compare-and-set baseline current after its own write', async () => {
    // Otherwise autosave's own write looks like somebody else's to the next
    // one, and the drill-in refuses to save anything ever again.
    let writes = 0;
    // A backend that stamps a new `savedAt` on every PUT, which is what one
    // does. Every write therefore moves the file underneath us; only the
    // adoption below stops the *next* one reading that as a stranger's edit.
    const save = vi.fn(async () => {
      writes += 1;
      return Ok(undefined);
    });
    const summary = vi.fn(async () =>
      Ok({ slug: 'host', name: 'Host', savedAt: `stamp-${writes}` }),
    );
    const document = hostDocument();
    const mounts = context(document);
    rememberMountHostDocument('host', document);
    recordKnownSavedAt('host', 'stamp-0');

    mounts.writeOverride('question', 'prompt', 'first');
    expect((await writeOpenMountHostToDisk({ save, summary } as never, mounts)).kind).toBe('saved');
    expect(getKnownSavedAt('host')).toBe('stamp-1');

    mounts.writeOverride('question', 'prompt', 'second');
    expect((await writeOpenMountHostToDisk({ save, summary } as never, mounts)).kind).toBe('saved');
    expect(save).toHaveBeenCalledTimes(2);
  });
});
