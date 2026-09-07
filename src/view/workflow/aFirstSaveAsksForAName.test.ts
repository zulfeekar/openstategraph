import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SaveFailure, SaveReceipt } from '@core/runtime/WorkflowFileClient';
import { Ok, type Result } from '@core/kernel/Result';
import type { WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import { clearOpenSlug, setOpenSlug } from '@app/openWorkflow';
import { UNNAMED_DOCUMENT } from '@core/model/documentName';
import { namePromptMessage, saveWorkflow, type IWorkflowSaving } from './saveWorkflow';
import type { SavableWorkbench } from './saveWorkflow';

/**
 * `say-it-on-the-surface/09` — **the moment a folder name is frozen is the
 * moment to ask for it.**
 *
 * The owner, saving a new workflow: *"and when saving, does it ask the user to
 * give a name?"* It did not. `saveWorkflow` read `workbench.model.name` —
 * `AI Workflow` for every document nobody had renamed — and handed it to
 * `create`, where `workflow_store.mint` slugified it into a directory that can
 * never move afterwards. The only question the save path ever asked was the
 * duplicate-name confirmation, and only when a clash already existed, which is
 * to say: the common case minted `ai-workflow/` in silence.
 *
 * This is `03` one surface later. That ticket found a required identifier
 * whose word had never been introduced; this one finds the same identifier
 * being *derived*, permanently, from a default the user never typed.
 *
 * The prompt belongs on the **create** branch alone. An overwrite of a slug
 * that exists cannot re-mint anything, so asking there would be friction that
 * buys nothing — and worse, would suggest the answer could still change the
 * folder.
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
      toJSONString: () => JSON.stringify({ version: 3, name: model.name, nodes: [], edges: [] }),
      canonicalise: (document: unknown) => document,
      sizeIsMeasured: () => true,
    },
    controller: { document: { mountContext: () => null } },
  };
}

function recordingClient() {
  const calls: string[] = [];
  const client: IWorkflowSaving = {
    list: (): Promise<Result<readonly WorkflowSummary[], string>> => Promise.resolve(Ok([])),
    summary: (): Promise<Result<WorkflowSummary | null, string>> => Promise.resolve(Ok(null)),
    save: (slug: string): Promise<Result<SaveReceipt, SaveFailure>> => {
      calls.push(`save:${slug}`);
      return Promise.resolve(Ok({ digest: 'sha-written' }));
    },
    create: (name: string): Promise<Result<string, string>> => {
      calls.push(`create:${name}`);
      return Promise.resolve(Ok('customer-triage'));
    },
  };
  return { client, calls };
}

const alwaysYes = () => true;

describe('the first save', () => {
  beforeEach(() => {
    vi.stubGlobal('sessionStorage', memoryStorage());
    vi.stubGlobal('localStorage', memoryStorage());
    clearOpenSlug();
  });

  it('asks for a name, and creates under the answer rather than the default', async () => {
    const { client, calls } = recordingClient();
    const asked: string[] = [];
    const outcome = await saveWorkflow({
      client,
      workbench: workbench(UNNAMED_DOCUMENT),
      confirm: alwaysYes,
      promptName: (suggestion) => {
        asked.push(suggestion);
        return 'Customer Triage';
      },
    });

    expect(asked).toEqual([UNNAMED_DOCUMENT]);
    expect(calls).toEqual(['create:Customer Triage']);
    expect(outcome).toEqual({
      kind: 'created',
      slug: 'customer-triage',
      name: 'Customer Triage',
    });
  });

  it('offers the name the document already has, so a renamed draft only needs Enter', async () => {
    const { client, calls } = recordingClient();
    const asked: string[] = [];
    await saveWorkflow({
      client,
      workbench: workbench('Chinook Assistant'),
      confirm: alwaysYes,
      promptName: (suggestion) => {
        asked.push(suggestion);
        return suggestion;
      },
    });

    // Asked even when the document carries a name somebody chose: this is the
    // one moment the folder is decided, and a person is entitled to see the
    // word that is about to be frozen before it is.
    expect(asked).toEqual(['Chinook Assistant']);
    expect(calls).toEqual(['create:Chinook Assistant']);
  });

  it('does not ask when a slug is already held', async () => {
    setOpenSlug('customer-triage');
    const { client, calls } = recordingClient();
    let asked = 0;
    await saveWorkflow({
      client,
      workbench: workbench('Customer Triage'),
      confirm: alwaysYes,
      promptName: (suggestion) => {
        asked += 1;
        return suggestion;
      },
    });

    // The folder exists and cannot move. Nothing to decide, so nothing to ask.
    expect(asked).toBe(0);
    expect(calls).toEqual(['save:customer-triage']);
  });

  it('writes nothing when the prompt is dismissed', async () => {
    const { client, calls } = recordingClient();
    const outcome = await saveWorkflow({
      client,
      workbench: workbench(UNNAMED_DOCUMENT),
      confirm: alwaysYes,
      promptName: () => null,
    });

    expect(calls).toEqual([]);
    expect(outcome.kind).toBe('cancelled');
  });

  it('treats a blank answer as a dismissal rather than minting a slug from nothing', async () => {
    const { client, calls } = recordingClient();
    const outcome = await saveWorkflow({
      client,
      workbench: workbench(UNNAMED_DOCUMENT),
      confirm: alwaysYes,
      promptName: () => '   ',
    });

    // `slugify('')` falls back to `workflow`, so a blank answer would not fail
    // — it would quietly mint `workflows/workflow/`. Refusing is the honest
    // branch, and it is the same one the dismissal takes.
    expect(calls).toEqual([]);
    expect(outcome.kind).toBe('cancelled');
  });

  it('trims the answer, because a trailing space is not part of a chosen name', async () => {
    const { client, calls } = recordingClient();
    await saveWorkflow({
      client,
      workbench: workbench(UNNAMED_DOCUMENT),
      confirm: alwaysYes,
      promptName: () => '  Customer Triage  ',
    });

    expect(calls).toEqual(['create:Customer Triage']);
  });

  it('asks before the duplicate-name confirmation, since the answer decides the clash', async () => {
    const order: string[] = [];
    const client: IWorkflowSaving = {
      list: () => {
        order.push('list');
        return Promise.resolve(Ok([]));
      },
      summary: () => Promise.resolve(Ok(null)),
      save: () => Promise.resolve(Ok({ digest: 'sha-written' })),
      create: () => Promise.resolve(Ok('customer-triage')),
    };

    await saveWorkflow({
      client,
      workbench: workbench(UNNAMED_DOCUMENT),
      confirm: alwaysYes,
      promptName: (suggestion) => {
        order.push('prompt');
        return suggestion === UNNAMED_DOCUMENT ? 'Customer Triage' : suggestion;
      },
    });

    // The clash check compares the name against the listing. Running it on the
    // *default* would have warned about the wrong word — and missed a genuine
    // clash with the name the user was about to type.
    expect(order).toEqual(['prompt', 'list']);
  });
});

describe('what the prompt says', () => {
  const message = namePromptMessage();

  it('states that this becomes the folder name', () => {
    // The fact `03` established a user is never told, said at the one moment
    // it is actionable.
    expect(message).toMatch(/folder/i);
  });

  it('states that it cannot be changed later', () => {
    expect(message).toMatch(/can(not|'t)\s+(be\s+)?chang/i);
  });

  it('stays one short line', () => {
    // A prompt nobody reads is a prompt that did not happen. This sits in a
    // browser dialog above an input; two sentences is the budget.
    expect(message.length).toBeLessThanOrEqual(160);
    expect(message.split('. ').filter(Boolean).length).toBeLessThanOrEqual(2);
  });
});
