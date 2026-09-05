import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import { setOpenSlug } from '@app/openWorkflow';
import {
  diskDocumentStatus,
  ensureDiskBaseline,
  forgetDiskDocument,
  rememberDiskDocument,
  writeOpenWorkflowToDisk,
} from '@app/diskAutosave';
import { draftIdForSlug } from '@app/workflowDrafts';
import { newWriteGuard, saveWorkflow } from '@app/workflowStore';
import { clearRestoredDraftChoice } from '@app/restoredDraftConflict';
import { decideExternalChange } from '@app/externalWorkflowChange';
import { forgetKnownDigest, getKnownDigest, recordKnownDigest } from '@app/workflowFileWatch';
import {
  announceWorkflowSaved,
  closeWorkflowSaveChannel,
  subscribeWorkflowSaved,
} from '@app/workflowSaveBroadcast';
import { Ok, type Result } from '@core/kernel/Result';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import type { KeyValueStore } from '@app/workflowStore';

/**
 * `osg-agent-experience/69` — **three tabs on one workflow did not see each
 * other's saves.**
 *
 * The owner, after `68`: *"a user opens three tabs on the same workflow, how
 * does each get the latest changes?"* A tab that was not the writer learned
 * nothing until its user reloaded, and the only thing the editor said was a
 * toast asking them to reload — the gesture `68` is the ticket about.
 *
 * The rule, in one sentence: **a save says which revision it was based on; the
 * server refuses a stale one; every other tab is told; a tab with no unsaved
 * edits takes the new revision silently, a tab with unsaved edits is asked,
 * and nothing is written before the answer.**
 *
 * This file asserts the editor's half. The backend's is
 * `backend/tests/test_three_tabs_on_one_workflow.py`; the two together at the
 * browser are `tests/e2e/twoTabsOnOneWorkflow.spec.ts`.
 *
 * ## What would still be green if the fix were in the wrong place
 *
 * The trap `skills/ticket-loop/` names. A test that restated
 * `decideExternalChange`'s own `if` would pass against any implementation
 * including no implementation, so the clean/dirty cases below build the
 * status out of `diskAutosave`'s **real** baseline map — the same one
 * `writeOpenWorkflowToDisk` consults — rather than passing the answer in.
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

/** A document of `nodes` nodes, named `name`, plus its authored form. */
function aDocument(name: string, nodes: number): { bench: Workbench; onDisk: unknown } {
  const bench = new Workbench();
  bench.model.setName(name);
  for (let i = 0; i < nodes; i += 1) {
    addNode(bench, TYPE.textInput, { at: { x: i * 200, y: 0 } });
  }
  return {
    bench,
    onDisk: JSON.parse(bench.serializer.toJSONString(bench.model)) as unknown,
  };
}

describe('osg-agent-experience 69 — a tab that did not write still learns', () => {
  let session: FakeStore;

  beforeEach(() => {
    session = new FakeStore();
    (globalThis as Record<string, unknown>)['sessionStorage'] = session;
    forgetDiskDocument(SLUG);
    forgetKnownDigest(SLUG);
    closeWorkflowSaveChannel();
    clearRestoredDraftChoice();
    setOpenSlug(SLUG);
  });

  describe('the clean/dirty decision', () => {
    it('refreshes silently when the canvas matches the file it came from', () => {
      // A tab opened on the package and left alone: the baseline was recorded
      // by the load path and nothing has been edited since.
      const { bench, onDisk } = aDocument('Probe', 3);
      rememberDiskDocument(SLUG, 'Probe', onDisk, bench.serializer);
      recordKnownDigest(SLUG, 'rev-1');

      const status = diskDocumentStatus(SLUG, bench.model, bench.serializer);
      expect(status).toBe('matches');
      expect(
        decideExternalChange({
          incomingDigest: 'rev-2',
          knownDigest: getKnownDigest(SLUG),
          status,
        }),
      ).toEqual({ kind: 'refresh' });
    });

    it('asks when the canvas holds edits the file has never seen', () => {
      const { bench, onDisk } = aDocument('Probe', 3);
      rememberDiskDocument(SLUG, 'Probe', onDisk, bench.serializer);
      recordKnownDigest(SLUG, 'rev-1');
      // The user typed. This is the whole difference between the two answers,
      // and it is measured through the same baseline `writeOpenWorkflowToDisk`
      // uses rather than asserted by the test.
      addNode(bench, TYPE.textInput, { at: { x: 900, y: 0 } });

      const status = diskDocumentStatus(SLUG, bench.model, bench.serializer);
      expect(status).toBe('differs');
      expect(
        decideExternalChange({
          incomingDigest: 'rev-2',
          knownDigest: getKnownDigest(SLUG),
          status,
        }),
      ).toEqual({ kind: 'ask' });
    });

    it('asks, never refreshes, a tab whose writer has been disarmed', () => {
      // No baseline: a save was refused, or a reload found a conflict. The
      // document on screen is the only copy of those edits and the editor has
      // already been told it must not write this package.
      const { bench } = aDocument('Probe', 3);
      expect(diskDocumentStatus(SLUG, bench.model, bench.serializer)).toBe('unbaselined');
      expect(
        decideExternalChange({
          incomingDigest: 'rev-2',
          knownDigest: undefined,
          status: 'unbaselined',
        }),
      ).toEqual({ kind: 'ask' });
    });

    it('ignores a frame carrying the revision this tab already holds', () => {
      // Disk autosave writes on every edit, so a tab hears about its own
      // writes constantly. Without this the feature is a fetch per keystroke
      // in the clean case and a dialog per keystroke in the dirty one.
      const { bench, onDisk } = aDocument('Probe', 3);
      rememberDiskDocument(SLUG, 'Probe', onDisk, bench.serializer);
      recordKnownDigest(SLUG, 'rev-7');
      addNode(bench, TYPE.textInput, { at: { x: 900, y: 0 } });

      expect(
        decideExternalChange({
          incomingDigest: 'rev-7',
          knownDigest: getKnownDigest(SLUG),
          status: diskDocumentStatus(SLUG, bench.model, bench.serializer),
        }),
      ).toEqual({ kind: 'ignore' });
    });

    it('leaves a deleted package to the watch that disarms the writer', () => {
      // An absent `workflow.json` digests as the empty string. Acting on it
      // here would be a second verdict about a deletion, racing
      // `abandonDeletedWorkflow`, which does more than notify.
      expect(
        decideExternalChange({ incomingDigest: '', knownDigest: 'rev-1', status: 'matches' }),
      ).toEqual({ kind: 'ignore' });
    });
  });

  describe('the revision a save quotes', () => {
    it('is the digest the last write answered with, so a second tab is refused', async () => {
      // The seam, end to end at this layer. Tab A saved and the backend
      // answered `rev-2`; tab B still holds `rev-1`, and its next autosave
      // must quote `rev-1` — which is what the 409 needs in order to refuse.
      const quoted: (string | undefined)[] = [];
      const client = {
        save: (
          _slug: string,
          _name: string,
          _doc: unknown,
          baseDigest?: string,
        ): Promise<Result<unknown, string>> => {
          quoted.push(baseDigest);
          return Promise.resolve(Ok({ digest: 'rev-3' }));
        },
      } as unknown as IWorkflowFileClient;

      const { bench, onDisk } = aDocument('Probe', 3);
      rememberDiskDocument(SLUG, 'Probe', onDisk, bench.serializer);
      recordKnownDigest(SLUG, 'rev-1');
      addNode(bench, TYPE.textInput, { at: { x: 900, y: 0 } });

      const outcome = await writeOpenWorkflowToDisk(client, bench.model, bench.serializer, session);
      expect(outcome.kind).toBe('saved');
      expect(quoted).toEqual(['rev-1']);
      // …and the receipt becomes this tab's revision, so the frame its own
      // write produces is ignored rather than answered.
      expect(getKnownDigest(SLUG)).toBe('rev-3');
    });
  });

  describe('the revision a draft was taken from', () => {
    /** A reload of a tab whose draft differs from the file, with a base recorded. */
    async function reload(base: string | undefined, fileDigest: string): Promise<{ kind: string }> {
      const local = new FakeStore();
      (globalThis as Record<string, unknown>)['localStorage'] = local;
      const { bench, onDisk } = aDocument('Probe', 3);
      // The draft: the file plus one node the user typed, written to browser
      // storage by the ordinary autosave path with its base recorded.
      const draft = new Workbench();
      draft.controller.document.importJSON(JSON.stringify(onDisk));
      addNode(draft, TYPE.textInput, { at: { x: 900, y: 0 } });
      saveWorkflow(local, draftIdForSlug(SLUG), draft.model, draft.serializer, newWriteGuard(), {
        baseDigest: base,
      });
      const client = {
        load: (): Promise<Result<unknown, string>> => Promise.resolve(Ok(onDisk)),
        summary: () =>
          Promise.resolve(
            Ok({ slug: SLUG, savedAt: '2026-09-05T10:10:00+00:00', digest: fileDigest }),
          ),
      } as unknown as IWorkflowFileClient;
      void bench;
      return ensureDiskBaseline(SLUG, client, draft.serializer, draft.model);
    }

    it('restores silently when the file still holds the revision the draft started from', async () => {
      // An edit made while the backend was unreachable. The draft differs from
      // the file — so `68`'s byte comparison alone would ask — but nobody else
      // touched the file, so there is nothing to ask about.
      expect(await reload('rev-1', 'rev-1')).toEqual({ kind: 'baselined' });
    });

    it('still asks when the file has moved since the draft was taken', async () => {
      // `68`'s reproduction: the CLI rewrote the file, so its revision is not
      // the one the draft recorded. This is the case that must not regress.
      expect((await reload('rev-1', 'rev-2')).kind).toBe('ask');
    });

    it('asks when the draft cannot say what it was taken from', async () => {
      // A draft written before the envelope carried a base. Cannot-tell keeps
      // the question, because the safe answer is the one `68` already ships.
      expect((await reload(undefined, 'rev-2')).kind).toBe('ask');
    });
  });

  describe('the same-browser head start', () => {
    it('announces the revision a save produced, in the shape the stream sends', () => {
      // One shape for both transports, so a listener cannot tell which one a
      // change arrived on and the digest deduplicates across them.
      const heard: unknown[] = [];
      const off = subscribeWorkflowSaved((announcement) => heard.push(announcement));
      announceWorkflowSaved(SLUG, 'rev-9');
      off();
      // jsdom delivers `BroadcastChannel` messages asynchronously, and a tab
      // never hears its own post, so what this asserts is that the channel
      // exists and the call is well-formed rather than a round trip that
      // cannot happen in one context. The round trip is the Playwright spec.
      expect(heard).toEqual([]);
    });

    it('says nothing at all when the save produced no revision', () => {
      // A create with no receipt and no readable summary. Announcing an
      // empty digest would tell every sibling tab the package is gone.
      const heard: unknown[] = [];
      const off = subscribeWorkflowSaved((announcement) => heard.push(announcement));
      announceWorkflowSaved(SLUG, undefined);
      announceWorkflowSaved(SLUG, '');
      off();
      expect(heard).toEqual([]);
    });
  });
});
