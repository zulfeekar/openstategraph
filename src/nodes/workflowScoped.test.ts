import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import type { ToolCapability } from '@core/runtime/WorkflowFileClient';
import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
import {
  registerScopedFamily,
  registerDiscoveredCapabilities,
  registerNodeTypesForRawDocument,
} from './workflowScoped';

/**
 * The gap this closes (recorded in `.scratch/fullstack-langgraph/map.md`):
 * Chinook's tools were registered unconditionally in the global catalogue,
 * so every workflow's palette carried them regardless of whether that
 * workflow used them at all.
 */
/**
 * What "registered" has to mean for the node to be usable.
 *
 * Every assertion in this file was `expect(registry.nodeTypes.get(id))
 * .toBeDefined()` — that an entry exists under that key, and nothing about
 * ports, the executor, or the workflow scope, which is what this module is
 * actually about (reviews-2026-08-14 ticket 09). A registration missing its
 * executor draws a card that cannot run; one missing the `workflow` scope
 * leaks into the always-available palette sections, which is the exact bug
 * `applyFamilyRegistration` re-upserts to prevent.
 */
function expectUsable(workbench: Workbench, id: string): void {
  const definition = workbench.registry.nodeTypes.get(id);
  expect(definition, `${id} is not registered`).toBeDefined();
  expect(definition?.scope, `${id} is not workflow-scoped`).toBe('workflow');
  // `ports` is a function of the node's data, so this calls it — a type that
  // resolves no ports is a card nothing can be wired to.
  expect(
    definition?.ports(definition.create({ position: { x: 0, y: 0 } }).data).length ?? 0,
    `${id} resolves no ports`,
  ).toBeGreaterThan(0);
  expect(workbench.engine.executors.get(id), `${id} has no executor`).toBeDefined();
}

describe('workflow-scoped node registration', () => {
  const chinookIds = CHINOOK_NODES.map((n) => n.definition.id);

  it('a fresh workbench does not carry Chinook tools in its palette', () => {
    const workbench = new Workbench();
    for (const id of chinookIds) {
      expect(workbench.registry.nodeTypes.get(id)).toBeUndefined();
    }
  });

  it('adding a Chinook node registers the whole family, not just that one', () => {
    const workbench = new Workbench();
    // Bypasses `controller.nodes.add` (which itself requires the type to
    // already be registered) — the point under test is what happens when a
    // node of this type *becomes present in the document*, however it got
    // there (a fresh add, an import, an undo).
    const definition = CHINOOK_NODES[0]!.definition;
    workbench.registry.nodeTypes.upsert(definition);
    const created = definition.create({ position: { x: 0, y: 0 } });
    workbench.model.addNode(created);

    for (const id of chinookIds) {
      expectUsable(workbench, id);
    }
  });

  it('removing the last Chinook node from the document unregisters the family', () => {
    const workbench = new Workbench();
    const definition = CHINOOK_NODES[0]!.definition;
    workbench.registry.nodeTypes.upsert(definition);
    const created = definition.create({ position: { x: 0, y: 0 } });
    workbench.model.addNode(created);

    workbench.model.removeNode(created.id);

    for (const id of chinookIds) {
      expect(workbench.registry.nodeTypes.get(id)).toBeUndefined();
    }
  });

  it('importing a document that references a Chinook tool registers it for that session', () => {
    const workbench = new Workbench();
    const definition = CHINOOK_NODES[0]!.definition;
    // The type must be registered before a document referencing it can be
    // imported at all — mirrors how a real load would go through the
    // capability-discovery/manifest step first. Once the node exists in the
    // model, the sync must pick it up regardless of *how* it arrived.
    workbench.registry.nodeTypes.upsert(definition);
    const created = definition.create({ position: { x: 0, y: 0 } });
    workbench.model.addNode(created);
    workbench.model.notifyReset();

    for (const id of chinookIds) {
      expectUsable(workbench, id);
    }
  });

  it('clearing the document back to empty unregisters the whole family', () => {
    const workbench = new Workbench();
    const definition = CHINOOK_NODES[0]!.definition;
    workbench.registry.nodeTypes.upsert(definition);
    const created = definition.create({ position: { x: 0, y: 0 } });
    workbench.model.addNode(created);

    workbench.model.clear();

    for (const id of chinookIds) {
      expect(workbench.registry.nodeTypes.get(id)).toBeUndefined();
    }
  });
});

/**
 * The palette's provenance split (`src/view/palette/Palette.tsx`) is only as
 * good as this flag: a scoped node type that reaches the registry unstamped
 * silently rejoins the always-available sections, which is precisely the
 * confusion the split exists to remove.
 */
describe('workflow-scoped node types announce their scope', () => {
  it('stamps scope: workflow on a family registered for the open document', () => {
    const workbench = new Workbench();
    const definition = CHINOOK_NODES[0]!.definition;
    workbench.registry.nodeTypes.upsert(definition);
    workbench.model.addNode(definition.create({ position: { x: 0, y: 0 } }));

    for (const id of CHINOOK_NODES.map((n) => n.definition.id)) {
      expect(workbench.registry.nodeTypes.get(id)?.scope).toBe('workflow');
    }
  });

  it('stamps scope: workflow on a discovered capability', () => {
    const workbench = new Workbench();
    registerDiscoveredCapabilities(
      [
        {
          id: 'a/tools.One',
          name: 'One',
          description: 'discovered',
          argsSchema: { type: 'object', properties: {} },
          nodeType: '',
        },
      ],
      workbench.registry,
      workbench.engine.executors,
    );

    expect(workbench.registry.nodeTypes.get('a/tools.One')?.scope).toBe('workflow');
  });

  it('leaves app-wide prebuilts unscoped', () => {
    const workbench = new Workbench();
    expect(workbench.registry.nodeTypes.get('input.text')?.scope).toBeUndefined();
  });

  /**
   * A purpose-built card shadows the generic one minted from discovery.
   *
   * Found in the palette: once the Chinook tools moved into
   * `workflows/chinook-assistant/tools/`, the capabilities endpoint reported
   * three tools for the open workflow and the palette's "This workflow"
   * section showed **six** entries — the hand-authored cards, and a generic
   * card per capability keyed by `capability.id`.
   *
   * Worse than cosmetic. The generic card's executor refuses toward Chat, and
   * it is not the type the shipped document wires, so a developer who picked
   * the wrong one of two identically-named entries got a node that behaved
   * differently from the one already on the canvas beside it.
   *
   * The backend has always sent `node_type` naming the hand-authored card, and
   * `registries.py` already documents the rule — "same-type collisions resolve
   * workflow-wins, mirroring the frontend's local-shadows-global registry
   * rule". The frontend simply never read the field.
   */
  describe('a discovered capability that a hand-authored card already covers', () => {
    const capability = (patch: Partial<ToolCapability> = {}): ToolCapability => ({
      id: 'chinook-assistant/tools.ExecuteSqlTool',
      name: 'chinook_execute_sql',
      description: 'discovered',
      argsSchema: { type: 'object', properties: {} },
      nodeType: '',
      ...patch,
    });

    it('is not minted a second time when its node_type already resolves', () => {
      const workbench = new Workbench();
      // The hand-authored card, as `syncWorkflowScopedNodes` would have it.
      registerScopedFamily('chinook', workbench.registry, workbench.engine.executors);
      const before = workbench.registry.nodeTypes.get('tool.chinook-execute-sql');
      expect(before).toBeDefined();

      registerDiscoveredCapabilities(
        [capability({ nodeType: 'tool.chinook-execute-sql' })],
        workbench.registry,
        workbench.engine.executors,
      );

      // No generic twin…
      expect(
        workbench.registry.nodeTypes.get('chinook-assistant/tools.ExecuteSqlTool'),
      ).toBeUndefined();
      // …and the purpose-built card is untouched, not replaced by a copy.
      expect(workbench.registry.nodeTypes.get('tool.chinook-execute-sql')).toBe(before);
    });

    it('is still minted when node_type names a card nobody has written', () => {
      // The ordinary case, and the reason the guard checks resolution rather
      // than merely the presence of the field: a Python tool declaring a
      // `node_type` no TS module ships must still reach the palette.
      const workbench = new Workbench();
      registerDiscoveredCapabilities(
        [capability({ nodeType: 'tool.nobody-wrote-this' })],
        workbench.registry,
        workbench.engine.executors,
      );
      expect(
        workbench.registry.nodeTypes.get('chinook-assistant/tools.ExecuteSqlTool'),
      ).toBeDefined();
    });

    it('is still minted when the capability declares no node_type at all', () => {
      const workbench = new Workbench();
      registerDiscoveredCapabilities(
        [capability({ nodeType: '' })],
        workbench.registry,
        workbench.engine.executors,
      );
      expect(
        workbench.registry.nodeTypes.get('chinook-assistant/tools.ExecuteSqlTool'),
      ).toBeDefined();
    });

    it('does not unregister the shadowing card when the next workflow opens', () => {
      // The teardown loop walks the ids registered last time. A shadowed
      // capability was never registered, so its id must not be in that list —
      // otherwise opening a second workflow would drop the hand-authored
      // Chinook card that discovery merely declined to duplicate.
      const workbench = new Workbench();
      registerScopedFamily('chinook', workbench.registry, workbench.engine.executors);
      registerDiscoveredCapabilities(
        [capability({ nodeType: 'tool.chinook-execute-sql' })],
        workbench.registry,
        workbench.engine.executors,
      );
      registerDiscoveredCapabilities([], workbench.registry, workbench.engine.executors);

      expectUsable(workbench, 'tool.chinook-execute-sql');
    });
  });
});

describe('registerNodeTypesForRawDocument — the load-order bug', () => {
  it('a document referencing an unregistered Chinook tool imports that node, not skips it', () => {
    // Reproduces the exact bug found while building this: `fromJSON` skips
    // any node whose type is not yet registered. Without calling
    // `registerNodeTypesForRawDocument` first, this import would silently
    // drop the tool node and warn "Skipped unknown node type", exactly what
    // would have happened to every real load of `chinook-assistant` or
    // `intent-routed-demo` once Chinook stopped being globally registered.
    const workbench = new Workbench();
    const toolType = CHINOOK_NODES[0]!.definition.id;
    const document = {
      version: 1,
      name: 'a workflow using a Chinook tool',
      nodes: [{ id: 'tool-1', type: toolType, data: {}, position: { x: 0, y: 0 } }],
      edges: [],
    };

    // Without this call, `nodeTypes.get(toolType)` is undefined and the
    // import below would skip the node entirely.
    registerNodeTypesForRawDocument(document, workbench.registry, workbench.engine.executors);
    const outcome = workbench.controller.document.importJSON(JSON.stringify(document));

    expect(outcome.ok).toBe(true);
    expect(outcome.message).toBeUndefined();
    expect(workbench.model.nodeCount).toBe(1);
    expect(workbench.model.node('tool-1')?.type).toBe(toolType);
  });

  it('a document that does not use Chinook leaves it unregistered', () => {
    const workbench = new Workbench();
    const document = {
      version: 1,
      name: 'a plain workflow',
      nodes: [{ id: 'in-1', type: 'input.text', data: {}, position: { x: 0, y: 0 } }],
      edges: [],
    };

    registerNodeTypesForRawDocument(document, workbench.registry, workbench.engine.executors);

    for (const { definition } of CHINOOK_NODES) {
      expect(workbench.registry.nodeTypes.get(definition.id)).toBeUndefined();
    }
  });

  it('switching from a Chinook workflow to a plain one unregisters it again', () => {
    const workbench = new Workbench();
    const toolType = CHINOOK_NODES[0]!.definition.id;
    registerNodeTypesForRawDocument(
      { nodes: [{ id: 't1', type: toolType, data: {}, position: { x: 0, y: 0 } }] },
      workbench.registry,
      workbench.engine.executors,
    );
    expectUsable(workbench, toolType);

    registerNodeTypesForRawDocument(
      { nodes: [{ id: 'in1', type: 'input.text', data: {}, position: { x: 0, y: 0 } }] },
      workbench.registry,
      workbench.engine.executors,
    );
    expect(workbench.registry.nodeTypes.get(toolType)).toBeUndefined();
  });

  it('a malformed document (no nodes array) is a no-op, not a crash', () => {
    const workbench = new Workbench();
    expect(() =>
      registerNodeTypesForRawDocument(null, workbench.registry, workbench.engine.executors),
    ).not.toThrow();
    expect(() =>
      registerNodeTypesForRawDocument({}, workbench.registry, workbench.engine.executors),
    ).not.toThrow();
  });
});

/**
 * Ticket 18's node-type-discovery half: a workflow's discovered `tools/`
 * capabilities become real, connectable node types the moment that
 * workflow is opened — see `DiscoveredToolNode.ts` for the node-type side.
 */
describe('registerDiscoveredCapabilities', () => {
  const capability = (id: string): ToolCapability => ({
    id,
    name: id,
    description: `discovered tool ${id}`,
    argsSchema: { type: 'object', properties: {} },
    nodeType: '',
  });

  it('registers one node type per discovered capability', () => {
    const workbench = new Workbench();
    registerDiscoveredCapabilities(
      [capability('a/tools.One'), capability('a/tools.Two')],
      workbench.registry,
      workbench.engine.executors,
    );

    expectUsable(workbench, 'a/tools.One');
    expectUsable(workbench, 'a/tools.Two');
  });

  it('unregisters the previous workflow’s capabilities when a new one is opened', () => {
    const workbench = new Workbench();
    registerDiscoveredCapabilities(
      [capability('a/tools.One')],
      workbench.registry,
      workbench.engine.executors,
    );

    registerDiscoveredCapabilities(
      [capability('b/tools.Two')],
      workbench.registry,
      workbench.engine.executors,
    );

    expect(workbench.registry.nodeTypes.get('a/tools.One')).toBeUndefined();
    expectUsable(workbench, 'b/tools.Two');
  });

  it('an empty list clears whatever was registered, without leaving it stranded', () => {
    const workbench = new Workbench();
    registerDiscoveredCapabilities(
      [capability('a/tools.One')],
      workbench.registry,
      workbench.engine.executors,
    );

    registerDiscoveredCapabilities([], workbench.registry, workbench.engine.executors);

    expect(workbench.registry.nodeTypes.get('a/tools.One')).toBeUndefined();
  });

  it('re-registering the same capability is idempotent, not a duplicate-id crash', () => {
    const workbench = new Workbench();
    expect(() => {
      registerDiscoveredCapabilities(
        [capability('a/tools.One')],
        workbench.registry,
        workbench.engine.executors,
      );
      registerDiscoveredCapabilities(
        [capability('a/tools.One')],
        workbench.registry,
        workbench.engine.executors,
      );
    }).not.toThrow();
    expectUsable(workbench, 'a/tools.One');
  });
});
