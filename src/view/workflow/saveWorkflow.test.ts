import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SaveFailure, SaveReceipt } from '@core/runtime/WorkflowFileClient';
import { Ok, Err, type Result } from '@core/kernel/Result';
import type { WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import { clearOpenSlug, getOpenSlug, setOpenSlug } from '@app/openWorkflow';
import {
  saveMessage,
  saveSucceeded,
  saveWorkflow,
  type IWorkflowSaving,
  type SavableWorkbench,
} from './saveWorkflow';

/**
 * `say-it-on-the-surface` 01 — the act of saving, lifted out of the panel so a
 * second surface can press it without reimplementing it.
 *
 * These tests are about the *knowledge*: which of the three acts fired, what
 * the backend was asked to do, and what sentence the surface is entitled to
 * say. The toolbar button and the panel button are then both thin.
 */

/**
 * The tests run under `environment: 'node'` like the rest of this suite, so
 * the two web storages are supplied here rather than by pulling in a DOM. Both
 * are real behaviour under test: the slug lands in `sessionStorage` and the
 * autosave baseline in `localStorage`, and a save that writes neither is
 * ticket 49's empty-canvas-after-reload bug.
 */
function memoryStorage(): Storage {
  const entries = new Map<string, string>();
  return {
    get length() {
      return entries.size;
    },
    clear: () => entries.clear(),
    getItem: (key: string) => entries.get(key) ?? null,
    key: (index: number) => [...entries.keys()][index] ?? null,
    removeItem: (key: string) => void entries.delete(key),
    setItem: (key: string, value: string) => void entries.set(key, String(value)),
  } as Storage;
}

const DOCUMENT = { version: 3, name: 'Draft', nodes: [], edges: [] };

function workbench(initial: string): SavableWorkbench {
  // The name is live rather than captured: `toJSONString` reads whatever the
  // model currently holds, so a test that renames at save time proves the new
  // name reached the serialised bytes and not just the create call.
  const model = {
    name: initial,
    setName(next: string) {
      model.name = next;
    },
  };
  return {
    model,
    serializer: {
      toJSONString: () => JSON.stringify({ ...DOCUMENT, name: model.name }),
      canonicalise: (document: unknown) => document,
      sizeIsMeasured: () => true,
    },
    controller: { document: { mountContext: () => null } },
  };
}

function recordingClient(overrides: Partial<IWorkflowSaving> = {}) {
  const calls: string[] = [];
  const client: IWorkflowSaving = {
    list: (): Promise<Result<readonly WorkflowSummary[], string>> => {
      calls.push('list');
      return Promise.resolve(Ok([]));
    },
    summary: (): Promise<Result<WorkflowSummary | null, string>> => Promise.resolve(Ok(null)),
    save: (slug: string): Promise<Result<SaveReceipt, SaveFailure>> => {
      calls.push(`save:${slug}`);
      return Promise.resolve(Ok({ digest: 'sha-written' }));
    },
    create: (name: string): Promise<Result<string, string>> => {
      calls.push(`create:${name}`);
      return Promise.resolve(Ok('draft-a1b2c3'));
    },
    ...overrides,
  };
  return { client, calls };
}

const alwaysYes = () => true;
/**
 * The name prompt, answered with whatever the document already holds — so
 * these tests keep asserting what they were written to assert. That a first
 * save *asks* at all, and what happens when it is dismissed, is
 * `aFirstSaveAsksForAName.test.ts` (`say-it-on-the-surface/09`).
 */
const keepsTheName = (suggestion: string) => suggestion;
const alwaysNo = () => false;

describe('saveWorkflow', () => {
  beforeEach(() => {
    vi.stubGlobal('sessionStorage', memoryStorage());
    vi.stubGlobal('localStorage', memoryStorage());
    clearOpenSlug();
  });

  it('creates when no slug is open, and reports the slug the backend minted', async () => {
    const { client, calls } = recordingClient();
    const outcome = await saveWorkflow({
      client,
      workbench: workbench('Draft'),
      confirm: alwaysYes,
      promptName: keepsTheName,
    });

    expect(outcome).toEqual({ kind: 'created', slug: 'draft-a1b2c3', name: 'Draft' });
    expect(calls).toContain('create:Draft');
    // The one thing the user could not have predicted is said out loud.
    expect(saveMessage(outcome)).toBe('Created: Draft (draft-a1b2c3)');
  });

  it('adopts the minted slug so the next page load finds the work', async () => {
    const { client } = recordingClient();
    await saveWorkflow({
      client,
      workbench: workbench('Draft'),
      confirm: alwaysYes,
      promptName: keepsTheName,
    });
    // Press Save, press reload: the address bar and the autosave key both know
    // this document now. Ticket 49's failure was an empty canvas here.
    expect(getOpenSlug()).toBe('draft-a1b2c3');
  });

  it('overwrites — never creates a second package — when a slug is open', async () => {
    setOpenSlug('chinook-assistant');
    const { client, calls } = recordingClient();
    const outcome = await saveWorkflow({
      client,
      workbench: workbench('Chinook'),
      confirm: alwaysYes,
      promptName: keepsTheName,
    });

    expect(outcome).toEqual({ kind: 'saved', slug: 'chinook-assistant', name: 'Chinook' });
    expect(calls).toContain('save:chinook-assistant');
    expect(calls).not.toContain('create:Chinook');
  });

  it('asks before minting a second package of a name that already has one', async () => {
    const { client, calls } = recordingClient({
      list: () =>
        Promise.resolve(
          Ok([{ slug: 'draft', name: 'Draft', published: false } as unknown as WorkflowSummary]),
        ),
    });
    const asked = vi.fn(() => false);
    const outcome = await saveWorkflow({
      client,
      workbench: workbench('Draft'),
      confirm: asked,
      promptName: keepsTheName,
    });

    expect(asked).toHaveBeenCalledOnce();
    expect(outcome).toEqual({ kind: 'cancelled', name: 'Draft' });
    // And it says so. A dismissed confirm used to return nothing at all, so
    // the button looked broken rather than obeyed.
    expect(saveMessage(outcome)).toContain('Not saved');
    expect(saveMessage(outcome)).toContain('Draft');
    // Refused means refused: nothing reached the backend.
    expect(calls).not.toContain('create:Draft');
  });

  it('does not ask when overwriting a package it already owns', async () => {
    setOpenSlug('draft');
    const { client } = recordingClient({
      list: () =>
        Promise.resolve(
          Ok([{ slug: 'draft', name: 'Draft', published: false } as unknown as WorkflowSummary]),
        ),
    });
    const asked = vi.fn(alwaysNo);
    await saveWorkflow({
      client,
      workbench: workbench('Draft'),
      confirm: asked,
      promptName: keepsTheName,
    });
    expect(asked).not.toHaveBeenCalled();
  });

  it('turns a backend failure into a sentence rather than a thrown error', async () => {
    const { client } = recordingClient({
      create: () => Promise.resolve(Err('runtime unreachable')),
    });
    const outcome = await saveWorkflow({
      client,
      workbench: workbench('Draft'),
      confirm: alwaysYes,
      promptName: keepsTheName,
    });

    expect(outcome.kind).toBe('refused');
    expect(saveMessage(outcome)).toBe('Could not save: runtime unreachable');
    expect(saveSucceeded(outcome)).toBe(false);
    // A failed create must not leave the tab believing it owns a package.
    expect(getOpenSlug()).toBeNull();
  });

  it('every outcome that reached the backend reports success, and only those', () => {
    expect(saveSucceeded({ kind: 'created', slug: 's', name: 'n' })).toBe(true);
    expect(saveSucceeded({ kind: 'saved', slug: 's', name: 'n' })).toBe(true);
    expect(saveSucceeded({ kind: 'overrides', root: 'r' })).toBe(true);
    expect(saveSucceeded({ kind: 'cancelled', name: 'n' })).toBe(false);
    expect(saveSucceeded({ kind: 'refused', message: 'x' })).toBe(false);
  });

  it('says whose document was written when an instance is open', () => {
    // The one case where "Saved" would be a lie: the bytes went to the parent,
    // not to the document on screen. A toolbar button must be able to say so.
    expect(saveMessage({ kind: 'overrides', root: 'concierge' })).toBe(
      "Saved this mount's overrides to concierge",
    );
  });
});
