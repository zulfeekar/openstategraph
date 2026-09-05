import { beforeEach, describe, expect, it } from 'vitest';

import { Workbench } from '@app/Workbench';
import { addNode, TYPE } from '@core/testing/fixtures';
import { Err, Ok, type Result } from '@core/kernel/Result';
import type { SaveFailure, SaveReceipt, WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import {
  clearConflictStandDown,
  conflictWantsTheFile,
  diskConflictNotice,
  forgetDiskDocument,
  rememberDiskDocument,
  writeOpenWorkflowToDisk,
} from '@app/diskAutosave';
import {
  CURRENT_SLUG_KEY,
  forgetKnownDigest,
  getKnownDigest,
  recordKnownVersion,
} from '@app/workflowFileWatch';

/**
 * **A coding agent's edit is not undone by the next autosave** —
 * `osg-agent-experience/45`.
 *
 * Reproduced in a try-folder session on 2026-09-05: a generator rewrote
 * fifteen tails in `workflows/cpl-analyst/workflow.json` while the developer
 * had that workflow open to watch the board, and four of the edges it wrote
 * were gone by the time anybody re-read the file. Nothing failed. The editor
 * posted the document it had held since the load and the backend wrote it.
 *
 * The refusal itself belongs to the backend, which is the only process that
 * can see the file — pinned in
 * `backend/tests/test_a_save_refuses_a_document_that_moved_on_disk.py`. What
 * is pinned here is this side of the seam, and the part that makes the
 * refusal survivable rather than merely loud:
 *
 * - autosave **quotes the version it loaded**, so the backend has something
 *   to refuse;
 * - a refusal **stops this document autosaving**, because a writer that keeps
 *   trying every keystroke turns one refused write into a queue of them;
 * - the digest the refusal carried is **adopted**, so *keep mine* is a save
 *   the user can actually make rather than a guard they have to switch off;
 * - and consecutive saves keep working, which is the thing a version check is
 *   most likely to break: the second one conflicts with the first one's own
 *   work unless the receipt is adopted.
 *
 * No DOM here — `vite.config.ts` sets `test.environment: 'node'` — so this
 * drives the writer directly with a stub client, the shape `useSpend.test.ts`
 * uses for the same reason.
 */

const SLUG = 'cpl-analyst';

/** The one call `writeOpenWorkflowToDisk` makes, recorded and answered. */
class StubClient {
  readonly saves: { slug: string; name: string; baseDigest?: string }[] = [];
  answers: Result<SaveReceipt, SaveFailure>[] = [];

  save(
    slug: string,
    name: string,
    _document: unknown,
    baseDigest?: string,
  ): Promise<Result<SaveReceipt, SaveFailure>> {
    this.saves.push({ slug, name, baseDigest });
    return Promise.resolve(this.answers.shift() ?? Ok({ digest: `sha-${this.saves.length}` }));
  }
}

const storage = (slug: string | null): Pick<Storage, 'getItem'> => ({
  getItem: (key: string) => (key === CURRENT_SLUG_KEY ? slug : null),
});

/** An editor holding the file's document, with a version quoted for it. */
function openWorkflow(digest: string): Workbench {
  const workbench = new Workbench();
  workbench.model.setName('CPL Analyst');
  rememberDiskDocument(
    SLUG,
    'CPL Analyst',
    workbench.serializer.serialize(workbench.model),
    workbench.serializer,
  );
  recordKnownVersion(SLUG, { savedAt: 't0', digest } as WorkflowSummary);
  return workbench;
}

const edit = (workbench: Workbench): void => {
  addNode(workbench, TYPE.agent);
};

const CONFLICT: SaveFailure = {
  kind: 'conflict',
  reason: "'cpl-analyst' changed on disk since it was loaded here",
  digest: 'sha-from-the-agent',
};

describe('autosave quotes the version it is editing', () => {
  beforeEach(() => {
    forgetDiskDocument(SLUG);
    forgetKnownDigest(SLUG);
  });

  it('sends the digest the load path recorded', async () => {
    const workbench = openWorkflow('sha-loaded');
    const client = new StubClient();
    edit(workbench);

    const outcome = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      storage(SLUG),
    );

    expect(outcome.kind).toBe('saved');
    expect(client.saves[0]?.baseDigest).toBe('sha-loaded');
  });

  it('adopts each receipt so consecutive saves do not conflict with themselves', async () => {
    const workbench = openWorkflow('sha-loaded');
    const client = new StubClient();

    edit(workbench);
    await writeOpenWorkflowToDisk(client, workbench.model, workbench.serializer, storage(SLUG));
    addNode(workbench, TYPE.agent);
    await writeOpenWorkflowToDisk(client, workbench.model, workbench.serializer, storage(SLUG));

    expect(client.saves.map((call) => call.baseDigest)).toEqual(['sha-loaded', 'sha-1']);
  });
});

describe('a refusal stops this document autosaving, and leaves a way forward', () => {
  beforeEach(() => {
    forgetDiskDocument(SLUG);
    forgetKnownDigest(SLUG);
  });

  it('reports the conflict rather than calling it a failed save', async () => {
    const workbench = openWorkflow('sha-loaded');
    const client = new StubClient();
    client.answers = [Err(CONFLICT)];
    edit(workbench);

    const outcome = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      storage(SLUG),
    );

    expect(outcome).toEqual({
      kind: 'conflict',
      slug: SLUG,
      reason: CONFLICT.reason,
    });
  });

  it('writes nothing more for that package, however many edits follow', async () => {
    const workbench = openWorkflow('sha-loaded');
    const client = new StubClient();
    client.answers = [Err(CONFLICT)];
    edit(workbench);
    await writeOpenWorkflowToDisk(client, workbench.model, workbench.serializer, storage(SLUG));

    addNode(workbench, TYPE.agent);
    const next = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      storage(SLUG),
    );

    expect(next.kind).toBe('skipped');
    expect(client.saves).toHaveLength(1);
  });

  it('adopts the digest the file actually has, so *keep mine* is a save the user can make', async () => {
    const workbench = openWorkflow('sha-loaded');
    const client = new StubClient();
    client.answers = [Err(CONFLICT)];
    edit(workbench);

    await writeOpenWorkflowToDisk(client, workbench.model, workbench.serializer, storage(SLUG));

    expect(getKnownDigest(SLUG)).toBe('sha-from-the-agent');
  });

  it('keeps an ordinary failure ordinary — the backend being down is not a conflict', async () => {
    const workbench = openWorkflow('sha-loaded');
    const client = new StubClient();
    client.answers = [Err({ kind: 'error', message: 'the runtime is unreachable' })];
    edit(workbench);

    const outcome = await writeOpenWorkflowToDisk(
      client,
      workbench.model,
      workbench.serializer,
      storage(SLUG),
    );

    expect(outcome).toEqual({ kind: 'failed', reason: 'the runtime is unreachable' });
    // Still armed: an unreachable backend is a reason to try again on the next
    // edit, and disarming there would turn a blip into a session that never
    // saves — the opposite failure to this ticket's.
    addNode(workbench, TYPE.agent);
    await writeOpenWorkflowToDisk(client, workbench.model, workbench.serializer, storage(SLUG));
    expect(client.saves).toHaveLength(2);
  });
});

describe('recordKnownVersion — the poll must not adopt a digest', () => {
  beforeEach(() => forgetKnownDigest(SLUG));

  it('records what a load or a save was handed', () => {
    recordKnownVersion(SLUG, { savedAt: 't', digest: 'sha-x' } as WorkflowSummary);
    expect(getKnownDigest(SLUG)).toBe('sha-x');
  });

  it('leaves the last known version alone when the backend could not say', () => {
    // The whole guard rests on this. The file watch polls the same summary
    // every few seconds; if a poll's digest were adopted, an agent's edit
    // would be adopted with it and the next autosave would quote the agent's
    // own version back at the backend and overwrite it — the guard would
    // report success at exactly the moment it was needed.
    recordKnownVersion(SLUG, { savedAt: 't', digest: 'sha-x' } as WorkflowSummary);
    recordKnownVersion(SLUG, null);
    expect(getKnownDigest(SLUG)).toBe('sha-x');
  });
});

describe('the two doors the notice names are doors that exist', () => {
  beforeEach(() => {
    forgetDiskDocument(SLUG);
    forgetKnownDigest(SLUG);
    clearConflictStandDown(SLUG);
  });

  const refuse = async (): Promise<void> => {
    const workbench = openWorkflow('sha-loaded');
    const client = new StubClient();
    client.answers = [Err(CONFLICT)];
    edit(workbench);
    await writeOpenWorkflowToDisk(client, workbench.model, workbench.serializer, storage(SLUG));
  };

  it('names both of them, and says what each one costs', () => {
    const notice = diskConflictNotice(SLUG);

    expect(notice).toContain(SLUG);
    // Neither door may be described without its consequence: one discards the
    // edits on screen and the other discards the ones on disk, and a notice
    // that hid either would be asking for a decision it had not stated.
    expect(notice).toContain('discard what is on screen');
    expect(notice).toContain('overwrite the file');
  });

  it('makes the next open of that workflow take the file, not this browser drafts', async () => {
    expect(conflictWantsTheFile(SLUG)).toBe(false);
    await refuse();

    // Read by the load path, which otherwise restores this browser's draft
    // over the file it just fetched — putting back precisely the document the
    // user chose against.
    expect(conflictWantsTheFile(SLUG)).toBe(true);
  });

  it('goes back to an ordinary open once the user has answered', async () => {
    await refuse();
    clearConflictStandDown(SLUG);

    expect(conflictWantsTheFile(SLUG)).toBe(false);
  });

  it('says nothing about a workflow that was never refused', () => {
    expect(conflictWantsTheFile('some-other-package')).toBe(false);
  });
});
