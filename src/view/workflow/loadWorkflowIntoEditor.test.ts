import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { Ok, type Result } from '@core/kernel/Result';
import type {
  IWorkflowFileClient,
  ToolCapability,
  WorkflowCapabilities,
  WorkflowSummary,
} from '@core/runtime/WorkflowFileClient';
import { CHINOOK_NODES } from '@nodes/tools/ChinookDatabaseNode';
import { loadWorkflowIntoEditor } from './loadWorkflowIntoEditor';

/**
 * Ticket 32 — the palette listed each of a workflow's three tools twice.
 *
 * The duplicate is minted by `registerDiscoveredCapabilities`, which is
 * supposed to decline whenever the capability's `node_type` already resolves
 * to a hand-authored card. Two things stopped it, and both are load-path
 * facts rather than registry facts, which is why this test lives here:
 *
 *  1. the field never came off the wire (fixed in `WorkflowFileClient`), and
 *  2. discovery ran **before** the document's own hand-authored families were
 *     registered, so the guard asked "is there a card for this?" at the one
 *     moment the answer was guaranteed to be no.
 */
describe('loadWorkflowIntoEditor', () => {
  let workbench: Workbench;

  const CHINOOK_DOCUMENT = {
    version: 2,
    name: 'Chinook Assistant',
    nodes: [
      {
        id: 't-tables',
        type: 'tool.chinook-get-all-tables',
        position: { x: 0, y: 0 },
        size: { width: 240, height: 96 },
        parentId: null,
        data: {},
      },
    ],
    edges: [],
  };

  const capability = (nodeType: string): ToolCapability => ({
    id: 'chinook-assistant/tools.ListTablesTool',
    name: 'chinook_list_tables',
    description: 'List all tables in the Chinook music-store database.',
    argsSchema: { type: 'object', properties: {} },
    nodeType,
  });

  const clientServing = (tools: readonly ToolCapability[]): IWorkflowFileClient =>
    ({
      load: (): Promise<Result<unknown, string>> => Promise.resolve(Ok(CHINOOK_DOCUMENT)),
      capabilities: (): Promise<Result<WorkflowCapabilities, string>> =>
        Promise.resolve(Ok({ tools, pluginTools: [], warnings: [] })),
      summary: (): Promise<Result<WorkflowSummary | null, string>> => Promise.resolve(Ok(null)),
    }) as unknown as IWorkflowFileClient;

  beforeEach(() => {
    workbench = new Workbench();
  });

  it('does not mint a generic card for a tool the document already has one for', async () => {
    const outcome = await loadWorkflowIntoEditor(
      'chinook-assistant',
      clientServing([capability('tool.chinook-get-all-tables')]),
      workbench,
    );

    expect(outcome.ok).toBe(true);
    // The hand-authored card is there…
    expect(workbench.registry.nodeTypes.get('tool.chinook-get-all-tables')).toBeDefined();
    // …and no twin under the raw runtime id beside it. Six entries for three
    // tools was the symptom; nothing in the palette said they were the same
    // capability, and the two behaved differently when dragged.
    expect(
      workbench.registry.nodeTypes.get('chinook-assistant/tools.ListTablesTool'),
    ).toBeUndefined();
  });

  it('registers the document’s own node types before discovery resolves duplicates', async () => {
    // Stated as an ordering fact rather than only as a count, because the
    // count was *unstable*: on a load where the previous document had left the
    // family registered, the same guard answered correctly and the duplicates
    // disappeared — so a developer saw a different palette for the same
    // workflow depending on load timing.
    await loadWorkflowIntoEditor(
      'chinook-assistant',
      clientServing([capability('tool.chinook-get-all-tables')]),
      workbench,
    );

    const chinookIds = CHINOOK_NODES.map((node) => node.definition.id);
    for (const id of chinookIds) {
      expect(workbench.registry.nodeTypes.get(id)).toBeDefined();
    }
  });

  it('still mints a card for a capability no hand-authored module covers', async () => {
    // The guard resolves rather than merely checks the field: a Python tool
    // naming a card nobody has written must still reach the palette, or
    // declaring `node_type` would *remove* a capability.
    await loadWorkflowIntoEditor(
      'chinook-assistant',
      clientServing([capability('tool.nobody-wrote-this')]),
      workbench,
    );

    expect(
      workbench.registry.nodeTypes.get('chinook-assistant/tools.ListTablesTool'),
    ).toBeDefined();
  });
});
