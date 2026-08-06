import { describe, expect, it } from 'vitest';
import {
  addNode,
  connect,
  LOOPABLE_TYPE,
  makeWorkbench,
  registerLoopableType,
  TYPE,
} from '@core/testing/fixtures';

/**
 * Ticket 25's splice-insert: dropping a node onto an existing edge inserts
 * it inline — the edge is replaced by two edges through the new node, as
 * one undo step. Design settled and recorded in
 * `.scratch/fullstack-langgraph/issues/25-incremental-authoring.md`; this
 * is that design, implemented.
 */
describe('EdgeEditor.insertOnEdge', () => {
  it('replaces one edge with two through the new node', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    const edge = connect(workbench, a, 'out', b, 'in');

    const outcome = workbench.controller.edges.insertOnEdge(edge.id, LOOPABLE_TYPE, {
      x: 200,
      y: 0,
    });

    expect(outcome.ok).toBe(true);
    expect(workbench.model.edge(edge.id)).toBeUndefined();
    expect(workbench.model.nodeCount).toBe(3);
    const inserted = workbench.model
      .nodes()
      .find((n) => n.id !== a.id && n.id !== b.id);
    expect(inserted).toBeDefined();
    expect(workbench.model.edgesInto({ nodeId: inserted!.id, portId: 'in' })[0]?.source).toEqual({
      nodeId: a.id,
      portId: 'out',
    });
    expect(workbench.model.edgesFrom({ nodeId: inserted!.id, portId: 'out' })[0]?.target).toEqual({
      nodeId: b.id,
      portId: 'in',
    });
  });

  it('undoes as a single step, restoring the original edge exactly', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    const edge = connect(workbench, a, 'out', b, 'in');

    workbench.controller.edges.insertOnEdge(edge.id, LOOPABLE_TYPE, { x: 200, y: 0 });
    expect(workbench.model.nodeCount).toBe(3);

    workbench.controller.history.undo();

    expect(workbench.model.nodeCount).toBe(2);
    expect(workbench.model.edgesFrom({ nodeId: a.id, portId: 'out' })[0]?.target).toEqual({
      nodeId: b.id,
      portId: 'in',
    });
  });

  it('rejects a type-incompatible drop without creating anything', () => {
    const workbench = makeWorkbench();
    registerLoopableType(workbench);
    const a = addNode(workbench, LOOPABLE_TYPE);
    const b = addNode(workbench, LOOPABLE_TYPE, { at: { x: 400, y: 0 } });
    const edge = connect(workbench, a, 'out', b, 'in');

    // Grader's `candidate` in-port is a `result` type, incompatible with
    // the loopable fixture's `text` edge — the same mismatch
    // `typeCompatibilityRule` would reject for an ordinary drag-to-connect.
    const outcome = workbench.controller.edges.insertOnEdge(edge.id, TYPE.grader, {
      x: 200,
      y: 0,
    });

    expect(outcome.ok).toBe(false);
    expect(workbench.model.nodeCount).toBe(2);
    expect(workbench.model.edge(edge.id)).toBeDefined();
  });

  it('reports a missing edge rather than throwing', () => {
    const workbench = makeWorkbench();
    const outcome = workbench.controller.edges.insertOnEdge(
      'edge-does-not-exist' as never,
      LOOPABLE_TYPE,
      { x: 0, y: 0 },
    );
    expect(outcome.ok).toBe(false);
  });
});
