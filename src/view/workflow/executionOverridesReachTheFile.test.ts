import { describe, expect, it, beforeEach } from 'vitest';

import { Ok, type Result } from '@core/kernel/Result';
import type { WorkflowSummary } from '@core/runtime/WorkflowFileClient';
import { Workbench } from '@app/Workbench';
import { EXECUTION_OVERRIDE_KEYS } from '@core/model/ModelRegistry';
import { clearOpenSlug, setOpenSlug } from '@app/openWorkflow';
import { saveWorkflow, type IWorkflowSaving, type SavableWorkbench } from './saveWorkflow';

/**
 * **A regression guard, not a fix** (`organisms-first-class/58`).
 *
 * The ticket recorded a sighting: `cacheTtlSeconds` was typed in the browser,
 * read back off the node, and then apparently absent from `workflow.json`
 * after pressing Save. Reproducing it end to end — a real backend over a
 * scratch workflows root, a real browser, `md5` before and after — showed the
 * value **does** reach the file, and reaches it through the button: the file's
 * digest moves exactly across the Save click, and the key is at
 * `workflow.json` → `document` → `nodes[].data`, one level deeper than a
 * reader looking for a top-level `nodes` would find it.
 *
 * So this test would have been green all along. It is here because the seam it
 * covers had nothing on it: `saveWorkflow.test.ts` drives the save with a
 * **stubbed** serializer returning a fixed four-key document, so a serializer
 * or node model that dropped configuration on the way out would not have
 * disturbed a single assertion there. This drives a real `Workbench` — real
 * registry, real node model, real `WorkflowSerializer` — and asserts on the
 * bytes handed to the client.
 *
 * All three execution overrides, never only the one that was reported: they
 * share `EXECUTION_OVERRIDE_FIELDS`, so a filter that lost one would lose all
 * three, and the list is imported rather than retyped for the reason ticket 34
 * already paid for once.
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

interface SavedNode {
  readonly id: string;
  readonly data: Record<string, unknown>;
}

function recordingClient(): { client: IWorkflowSaving; saved: () => unknown } {
  let document: unknown = null;
  const client: IWorkflowSaving = {
    list: (): Promise<Result<readonly WorkflowSummary[], string>> => Promise.resolve(Ok([])),
    summary: (): Promise<Result<WorkflowSummary | null, string>> => Promise.resolve(Ok(null)),
    save: (_slug: string, _name: string, sent: unknown): Promise<Result<void, string>> => {
      document = sent;
      return Promise.resolve(Ok(undefined));
    },
    create: (): Promise<Result<string, string>> => Promise.resolve(Ok('unused')),
  };
  return { client, saved: () => document };
}

/** A real workbench holding one agent, with the overrides a user typed. */
function workbenchWithOverrides(values: Record<string, string>): {
  workbench: SavableWorkbench;
  nodeId: string;
} {
  const workbench = new Workbench();
  const node = workbench.registry.nodeTypes.require('agent.llm').create({
    position: { x: 10, y: 20 },
  });
  workbench.controller.model.addNode(node);
  for (const [key, value] of Object.entries(values)) {
    workbench.controller.nodes.setField(node.id, key, value);
  }
  return { workbench: workbench as unknown as SavableWorkbench, nodeId: node.id };
}

const nodesOf = (document: unknown): readonly SavedNode[] =>
  ((document as { document?: { nodes?: SavedNode[] }; nodes?: SavedNode[] }).document?.nodes ??
    (document as { nodes?: SavedNode[] }).nodes ??
    []) as readonly SavedNode[];

describe('an execution override a user typed reaches the saved document', () => {
  beforeEach(() => {
    globalThis.sessionStorage = memoryStorage();
    globalThis.localStorage = memoryStorage();
    clearOpenSlug();
  });

  it('names the three keys from their declaration, so this cannot go stale', () => {
    // Anti-vacuity twice over: the loop below is over this list, and a list
    // that shrank to nothing would make every assertion trivially true.
    expect([...EXECUTION_OVERRIDE_KEYS].sort()).toEqual([
      'cacheTtlSeconds',
      'maxRetries',
      'timeoutSeconds',
    ]);
  });

  it('carries every one of them through a real serializer to the client', async () => {
    setOpenSlug('support-triage');
    const typed = { maxRetries: '5', timeoutSeconds: '42', cacheTtlSeconds: '300' };
    const { workbench, nodeId } = workbenchWithOverrides(typed);
    const { client, saved } = recordingClient();

    const outcome = await saveWorkflow({ client, workbench, confirm: () => true });

    expect(outcome.kind).toBe('saved');
    const node = nodesOf(saved()).find((n) => n.id === nodeId);
    expect(node, 'the node the user edited is not in the saved document').toBeDefined();
    for (const key of EXECUTION_OVERRIDE_KEYS) {
      expect(node?.data[key], `${key} did not reach the saved document`).toBe(
        typed[key as keyof typeof typed],
      );
    }
  });

  it('still writes them as blank when the user typed nothing', async () => {
    // The inverse, and the one a careless "drop empty values" optimisation
    // would break: blank is the schema's way of saying "use the graph's
    // default", and it is a value the document carries rather than an absence.
    setOpenSlug('support-triage');
    const { workbench, nodeId } = workbenchWithOverrides({});
    const { client, saved } = recordingClient();

    await saveWorkflow({ client, workbench, confirm: () => true });

    const node = nodesOf(saved()).find((n) => n.id === nodeId);
    for (const key of EXECUTION_OVERRIDE_KEYS) {
      expect(node?.data[key], `${key} is missing entirely`).toBe('');
    }
  });

  it('asks no question on the overwrite path — Save on an open slug never confirms', async () => {
    // The ticket's second observation, and it is not a symptom: `confirm` is
    // consulted only when a *create* would mint a second package of a name
    // that already has one. A document opened at a slug takes the overwrite
    // branch, where there is no question to ask, so no dialog firing is the
    // behaviour rather than evidence the press was lost.
    setOpenSlug('support-triage');
    const { workbench } = workbenchWithOverrides({ cacheTtlSeconds: '300' });
    const { client } = recordingClient();
    let asked = 0;

    const outcome = await saveWorkflow({
      client,
      workbench,
      confirm: () => {
        asked += 1;
        return true;
      },
    });

    expect(outcome.kind).toBe('saved');
    expect(asked).toBe(0);
  });
});
