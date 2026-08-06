import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
import { registerNodeTypesForRawDocument } from './workflowScoped';

/**
 * The gap this closes (recorded in `.scratch/fullstack-langgraph/map.md`):
 * Chinook's tools were registered unconditionally in the global catalogue,
 * so every workflow's palette carried them regardless of whether that
 * workflow used them at all.
 */
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
      expect(workbench.registry.nodeTypes.get(id)).toBeDefined();
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
      expect(workbench.registry.nodeTypes.get(id)).toBeDefined();
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

describe('registerNodeTypesForRawDocument — the load-order bug', () => {
  it('a document referencing an unregistered Chinook tool imports that node, not skips it', () => {
    // Reproduces the exact bug found while building this: `fromJSON` skips
    // any node whose type is not yet registered. Without calling
    // `registerNodeTypesForRawDocument` first, this import would silently
    // drop the tool node and warn "Skipped unknown node type", exactly what
    // would have happened to every real load of `chinook-nl-to-sql` or
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
    expect(workbench.registry.nodeTypes.get(toolType)).toBeDefined();

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
