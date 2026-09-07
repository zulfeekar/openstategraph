import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import { setOpenSlug } from '@app/openWorkflow';
import { ensureDiskBaseline, forgetDiskDocument, writeOpenWorkflowToDisk } from '@app/diskAutosave';
import {
  clearRestoredDraftChoice,
  decideRestoredDraft,
  pendingRestoredDraftChoice,
} from '@app/restoredDraftConflict';
import { forgetKnownDigest, getKnownDigest } from '@app/workflowFileWatch';
import { Ok, type Result } from '@core/kernel/Result';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import type { KeyValueStore } from '@app/workflowStore';

/**
 * `osg-agent-experience/68` — **a reloaded tab wrote its old draft over a
 * newer file on disk, and nobody pressed anything.**
 *
 * Reproduced in the browser on 2026-09-05 against a throwaway package: open
 * it, edit it (disk autosave writes that edit, so draft and file agree),
 * rewrite `workflow.json` from the shell, reload the tab. The reload alone —
 * no drag, no keystroke, no Save — put the pre-rewrite document back on disk.
 *
 * ## Why the two guards that exist did not fire
 *
 * - **`writeOpenWorkflowToDisk`'s "never write a package this page has not
 *   opened"** is enforced by requiring a `lastWritten` baseline, and
 *   `ensureDiskBaseline` is the one honest exception: a reload restores the
 *   browser draft instead of re-fetching, so nothing else would ever say what
 *   is on disk. It seeded that baseline from the file **unconditionally**, and
 *   `importJSON` on the restore fires `controller.onChange`. Baseline plus a
 *   change is a write, so the exception was the delivery mechanism.
 * - **The 409 content-digest guard** (`osg-agent-experience/45` and 47) quotes
 *   `getKnownDigest(slug)` as `base_digest`. That map is in-memory, so after a
 *   reload it is empty, the save quotes nothing, and the backend — correctly,
 *   having been asked for an unconditional write — answers 200.
 *
 * So the fix is one seam and two halves, and this file asserts both:
 *
 * 1. `ensureDiskBaseline` **compares before it baselines**. Equal is the
 *    ordinary case and stays silent; different means the file moved under a
 *    draft this browser is about to resurrect, and nothing is baselined — so
 *    the existing "no baseline, no write" rule does the refusing, rather than
 *    a second copy of it.
 * 2. It **arms the existing 409 guard** by recording the digest the file
 *    actually has, so whichever way the user answers, the write that follows
 *    quotes a version instead of nothing.
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

const SLUG = 'reload-draft-probe';

describe('osg-agent-experience 68 — a reload never writes a draft it has not offered', () => {
  let session: FakeStore;
  let written: { slug: string; baseDigest: string | undefined }[];

  beforeEach(() => {
    session = new FakeStore();
    written = [];
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
    forgetDiskDocument(SLUG);
    forgetKnownDigest(SLUG);
    clearRestoredDraftChoice();
    setOpenSlug(SLUG);
  });

  /** A backend holding one package at one digest, recording every write. */
  function backend(document: unknown, digest: string): IWorkflowFileClient {
    return {
      load: (): Promise<Result<unknown, string>> => Promise.resolve(Ok(document)),
      summary: () =>
        Promise.resolve(Ok({ slug: SLUG, savedAt: '2026-09-05T10:10:00+00:00', digest })),
      save: (
        slug: string,
        _name: string,
        _doc: unknown,
        baseDigest?: string,
      ): Promise<Result<unknown, string>> => {
        written.push({ slug, baseDigest });
        return Promise.resolve(Ok({ digest: 'after' }));
      },
    } as unknown as IWorkflowFileClient;
  }

  /** A document of `nodes` nodes, named `name`, in the file's authored form. */
  function aDocument(name: string, nodes: number): { model: Workbench; onDisk: unknown } {
    const authored = new Workbench();
    authored.model.setName(name);
    for (let i = 0; i < nodes; i += 1) {
      addNode(authored, TYPE.textInput, { at: { x: i * 200, y: 0 } });
    }
    return {
      model: authored,
      onDisk: JSON.parse(authored.serializer.toJSONString(authored.model)) as unknown,
    };
  }

  it('writes nothing, and offers the choice, when the file moved under the draft', async () => {
    // The reproduction, at the layer it lives: the canvas holds the restored
    // draft (two nodes, the name the user typed) and the file on disk holds
    // what a CLI session wrote in the meantime (five nodes, its own name).
    const { onDisk } = aDocument('CLI Rewrote The File', 5);
    const { model: restored } = aDocument('Probe DRAFT EDIT', 2);
    const client = backend(onDisk, 'file-digest');

    const outcome = await ensureDiskBaseline(SLUG, client, restored.serializer, restored.model);

    expect(outcome.kind).toBe('ask');

    // Nothing is written before the user answers — and it is the *existing*
    // rule that refuses, because no baseline was recorded.
    const result = await writeOpenWorkflowToDisk(
      client,
      restored.model,
      restored.serializer,
      session,
    );
    expect(result.kind).toBe('skipped');
    expect(written).toEqual([]);

    // …and the choice is on offer rather than merely withheld. A refusal with
    // no way out is this ticket's data loss with the arrow reversed: the draft
    // would be unsaveable for the life of the tab.
    const offer = pendingRestoredDraftChoice();
    expect(offer?.slug).toBe(SLUG);
    expect(offer?.fileName).toBe('CLI Rewrote The File');
  });

  it('arms the 409 guard for the restore path rather than keeping a second copy', async () => {
    // The half the ticket names: the digest the file actually has is adopted
    // here, so the save that eventually happens quotes a version. Without it
    // the reload path is the one place `base_digest` is `undefined` and the
    // backend is asked for an unconditional write.
    const { onDisk } = aDocument('CLI Rewrote The File', 5);
    const { model: restored } = aDocument('Probe DRAFT EDIT', 2);

    await ensureDiskBaseline(
      SLUG,
      backend(onDisk, 'file-digest'),
      restored.serializer,
      restored.model,
    );

    expect(getKnownDigest(SLUG)).toBe('file-digest');
  });

  it('baselines silently when the draft is the file, which is the ordinary reload', async () => {
    // The exception `ensureDiskBaseline` exists for must survive the fix. A
    // tab that reloads onto a draft matching disk — every tab whose last edit
    // was autosaved — keeps autosaving, and says nothing.
    const { model: restored, onDisk } = aDocument('Reload Draft Probe', 3);
    const client = backend(onDisk, 'file-digest');

    const outcome = await ensureDiskBaseline(SLUG, client, restored.serializer, restored.model);

    expect(outcome.kind).toBe('baselined');
    expect(pendingRestoredDraftChoice()).toBeNull();

    addNode(restored, TYPE.textInput, { at: { x: 99, y: 99 } });
    const result = await writeOpenWorkflowToDisk(
      client,
      restored.model,
      restored.serializer,
      session,
    );
    expect(result.kind).toBe('saved');
    // …quoting the file's version, which is what makes the 409 guard cover
    // this path too.
    expect(written).toEqual([{ slug: SLUG, baseDigest: 'file-digest' }]);
  });

  it('never writes when the file could not be read at all', async () => {
    // A failed read must not become a blind write — the rule
    // `ensureDiskBaseline` already had, restated as an outcome rather than an
    // early return, so a caller cannot mistake it for a baseline.
    const { model: restored } = aDocument('Probe DRAFT EDIT', 2);
    const unreachable = {
      load: () => Promise.resolve({ ok: false as const, error: 'offline' }),
      summary: () => Promise.resolve({ ok: false as const, error: 'offline' }),
      save: () => {
        throw new Error('a save must never be attempted here');
      },
    } as unknown as IWorkflowFileClient;

    const outcome = await ensureDiskBaseline(
      SLUG,
      unreachable,
      restored.serializer,
      restored.model,
    );

    expect(outcome.kind).toBe('stood-down');
    expect(pendingRestoredDraftChoice()).toBeNull();
  });
});

/**
 * The decision on its own, at the three inputs it has.
 *
 * Separate from the cases above rather than instead of them: a pure function
 * proves the rule, and the cases above prove the rule is the one the write
 * path actually consults. This repository has paid twice for a green test at
 * the wrong layer.
 */
describe('decideRestoredDraft', () => {
  it('takes the file as the baseline when the draft is the same document', () => {
    expect(decideRestoredDraft('same', 'same')).toEqual({ kind: 'baselined' });
  });

  it('asks when they differ, because only the user knows which is wanted', () => {
    expect(decideRestoredDraft('the file', 'the draft')).toEqual({ kind: 'ask' });
  });

  it('stands down when the file could not be read', () => {
    expect(decideRestoredDraft(null, 'the draft')).toEqual({ kind: 'stood-down' });
  });
});
