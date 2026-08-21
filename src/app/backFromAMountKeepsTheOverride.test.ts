import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Ok } from '@core/kernel/Result';
import { Workbench } from '@app/Workbench';
import { MountContext } from '@core/model/MountContext';
import type { MountAddress } from '@core/model/MountAddress';
import {
  forgetMountHostDocument,
  rememberMountHostDocument,
  writeOpenMountHostToDisk,
} from '@app/diskAutosave';
import { draftIdForSlug, restoreDraftFor } from '@app/workflowDrafts';
import {
  newWriteGuard,
  saveWorkflow as writeDraft,
  type KeyValueStore,
} from '@app/workflowStore';
import { recordKnownSavedAt } from '@app/workflowFileWatch';
import { setOpenAddress } from '@app/openAddress';
import { saveWorkflow as saveMountOverrides } from '@view/workflow/saveWorkflow';

/**
 * `production-ready` 101 — **Back from a mount threw away the override it had
 * just saved, and disk autosave then deleted it from the file.**
 *
 * Measured in a scratch project with md5 at every step. `front-desk` mounts
 * `music-analyst` twice. Drill into `m2`, change the child agent's system
 * prompt, **Save mount**: the parent file correctly carries both overrides
 * (`ed8e43bc…` → `ea2c8af9…`) and the child package stays byte-identical.
 * Press **← Back to front-desk** and, ten seconds later, the file reads
 * `7263177c…` with `m2`'s override back to `''`.
 *
 * **Back re-reads the parent from disk** — `loadWorkflowIntoEditor` fetches
 * it — so the stale document is not `mounts.rootDocument`. It is this
 * browser's **draft** of the parent, written by the very act of opening the
 * parent before the drill-in, and restored over the freshly-fetched file by
 * `restoreDraftFor`. `writeOpenWorkflowToDisk` then writes documents *whole*,
 * so an absence in memory became a deletion on disk.
 *
 * The rule the code was missing: a draft is *this browser's unsaved edits to a
 * package*, and it stops being that the moment this same browser writes that
 * package's file from somewhere else. Both host writers — the drill-in's
 * autosave here, and the explicit **Save mount** in `saveWorkflow` — supersede
 * it.
 *
 * Deliberately **not** a timestamp comparison inside `restoreDraftFor`: that
 * function documents at length why it compares canonical bytes rather than
 * clocks, and a browser clock against a backend clock is exactly the
 * comparison it refuses. Which package this browser just wrote is a fact it
 * knows with no clock at all.
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

const ADDRESS: MountAddress = { root: 'front-desk', mountPath: ['m2'] };

/** The parent as it sits on disk before anybody drills in. */
function parentDocument(): Record<string, unknown> {
  return {
    version: 3,
    name: 'Front Desk',
    nodes: [
      {
        id: 'm1',
        type: 'workflow.subgraph',
        position: { x: 300, y: 40 },
        data: { workflow: 'music-analyst', overrides: '{"agent1":{"systemPrompt":"m1 pinned"}}' },
      },
      {
        id: 'm2',
        type: 'workflow.subgraph',
        position: { x: 300, y: 300 },
        data: { workflow: 'music-analyst' },
      },
    ],
    edges: [],
  };
}

/** A Workbench holding that document, exactly as a load leaves one. */
function editorHoldingTheParent(): Workbench {
  const workbench = new Workbench();
  workbench.model.setName('Front Desk');
  workbench.controller.document.importJSON(JSON.stringify(parentDocument()));
  return workbench;
}

/** The `m2` override, as the *canvas* would read it back. */
function m2Override(workbench: Workbench): string {
  const document = JSON.parse(workbench.controller.document.exportJSON()) as {
    nodes: Array<{ id: string; data?: Record<string, unknown> }>;
  };
  const node = document.nodes.find((entry) => entry.id === 'm2');
  return String(node?.data?.['overrides'] ?? '');
}

describe('back from a mount keeps the override it just saved', () => {
  let store: FakeStore;

  beforeEach(() => {
    store = new FakeStore();
    vi.stubGlobal('localStorage', store);
    forgetMountHostDocument('front-desk');
    recordKnownSavedAt('front-desk', undefined);
  });

  /**
   * The whole chain, at the layer the defect lives: the parent's draft is
   * written by opening it, the host write happens from inside the drill-in,
   * and then Back re-reads the file and offers the draft over it.
   *
   * The assertion is on **what the canvas holds after Back**, because that is
   * what `writeOpenWorkflowToDisk` serialises whole into the file. A test that
   * only asked whether a draft was dropped would stay green against a fix that
   * dropped the wrong one.
   */
  it('does not let the pre-drill-in draft undo the override on the way back', async () => {
    // 1. Opening the parent writes this browser's draft of it — no override on
    //    `m2`, because there is not one yet.
    const beforeDrillIn = editorHoldingTheParent();
    expect(
      writeDraft(
        store,
        draftIdForSlug('front-desk'),
        beforeDrillIn.model,
        beforeDrillIn.serializer,
        newWriteGuard(),
      ).ok,
    ).toBe(true);

    // 2. Drill into `m2`, change the child's prompt, and let the host write
    //    reach the file. The parent document now carries both overrides.
    const host = parentDocument();
    rememberMountHostDocument('front-desk', host);
    const mounts = new MountContext(ADDRESS, host);
    mounts.writeOverride('agent1', 'systemPrompt', 'M2 OVERRIDE PROMPT 101');

    let onDisk: unknown = null;
    const outcome = await writeOpenMountHostToDisk(
      {
        save: async (_slug: string, _name: string, document: unknown) => {
          onDisk = document;
          return Ok(undefined);
        },
        summary: async () => Ok(null),
      },
      mounts,
    );
    expect(outcome).toEqual({ kind: 'saved' });

    // 3. **Back.** `loadWorkflowIntoEditor` fetches the parent from disk and
    //    then offers this browser's draft over it.
    const afterBack = new Workbench();
    afterBack.model.setName('Front Desk');
    afterBack.controller.document.importJSON(JSON.stringify(onDisk));
    const restored = restoreDraftFor('front-desk', afterBack, store);

    // The override survives the round trip — this is the file's next contents.
    expect(m2Override(afterBack)).toContain('M2 OVERRIDE PROMPT 101');
    // …and nothing was announced as a restored draft, because there was no
    // unsaved parent edit to restore.
    expect(restored.restored).toBe(false);
  });

  /**
   * The same claim about the **explicit** gesture, driven through the real
   * `saveWorkflow` rather than through the rule it calls.
   *
   * This is the shape `production-ready` 71's first test got wrong: asserting
   * that `supersedeDraftAfterHostWrite` deletes a draft proves only that the
   * function agrees with itself, and would stay green with the call site
   * missing. So the Save mount button's own path is what runs here, and the
   * assertion is again on what a subsequent Back would put on the canvas.
   */
  it('survives the Save mount button too, not only the drill-in autosave', async () => {
    vi.stubGlobal('sessionStorage', new FakeStore());
    setOpenAddress(ADDRESS, 'music-analyst');

    const beforeDrillIn = editorHoldingTheParent();
    expect(
      writeDraft(
        store,
        draftIdForSlug('front-desk'),
        beforeDrillIn.model,
        beforeDrillIn.serializer,
        newWriteGuard(),
      ).ok,
    ).toBe(true);

    const host = parentDocument();
    const mounts = new MountContext(ADDRESS, host);
    mounts.writeOverride('agent1', 'systemPrompt', 'M2 OVERRIDE PROMPT 101');

    let onDisk: unknown = null;
    const outcome = await saveMountOverrides({
      client: {
        list: async () => Ok([]),
        summary: async () => Ok(null),
        save: async (_slug: string, _name: string, document: unknown) => {
          onDisk = document;
          return Ok(undefined);
        },
        create: async () => Ok('unused'),
      },
      workbench: {
        model: { name: 'Music Analyst' },
        serializer: {
          toJSONString: () => '{}',
          canonicalise: (document: unknown) => document,
          sizeIsMeasured: () => true,
        },
        controller: { document: { mountContext: () => mounts } },
      },
      confirm: () => true,
    });
    expect(outcome).toEqual({ kind: 'overrides', root: 'front-desk' });

    const afterBack = new Workbench();
    afterBack.model.setName('Front Desk');
    afterBack.controller.document.importJSON(JSON.stringify(onDisk));
    const restored = restoreDraftFor('front-desk', afterBack, store);

    expect(m2Override(afterBack)).toContain('M2 OVERRIDE PROMPT 101');
    expect(restored.restored).toBe(false);
  });
});
