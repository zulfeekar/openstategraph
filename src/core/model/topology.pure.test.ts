import { describe, expect, it } from 'vitest';
import type { AbstractNodeModel } from './AbstractNodeModel';
import type { EdgeModel } from './EdgeModel';
import { bounds, topologicalOrder } from './topology';

/**
 * Direct unit tests of the pure functions, alongside the existing
 * integration coverage in `topology.test.ts` (which exercises the same
 * behaviour through a real `WorkflowModel`). These pin the algorithm with
 * no model, no controller, no registry — the point of pulling it out.
 */

const fakeNode = (id: string, isExecutable = true, x = 0, y = 0, w = 10, h = 10) =>
  ({ id, isExecutable, position: { x, y }, size: { width: w, height: h } }) as unknown as AbstractNodeModel;

const fakeEdge = (sourceId: string, targetId: string) =>
  ({ source: { nodeId: sourceId }, target: { nodeId: targetId } }) as unknown as EdgeModel;

describe('topology.topologicalOrder', () => {
  it('orders a linear chain upstream-first', () => {
    const { order, cycle } = topologicalOrder(
      [fakeNode('a'), fakeNode('b'), fakeNode('c')],
      [fakeEdge('a', 'b'), fakeEdge('b', 'c')],
    );
    expect(cycle).toBeNull();
    expect(order).toEqual(['a', 'b', 'c']);
  });

  it('excludes non-executable nodes from the schedule', () => {
    const { order } = topologicalOrder([fakeNode('a'), fakeNode('note', false)], []);
    expect(order).toEqual(['a']);
  });

  it('reports the surviving cycle instead of throwing', () => {
    const { order, cycle } = topologicalOrder(
      [fakeNode('a'), fakeNode('b')],
      [fakeEdge('a', 'b'), fakeEdge('b', 'a')],
    );
    expect(order).toHaveLength(0);
    expect([...(cycle ?? [])].sort()).toEqual(['a', 'b']);
  });
});

describe('topology.bounds', () => {
  it('is null for no nodes', () => {
    expect(bounds([])).toBeNull();
  });

  it('unions every rectangle', () => {
    expect(bounds([fakeNode('a', true, 0, 0, 10, 10), fakeNode('b', true, 100, 100, 10, 10)])).toEqual({
      x: 0,
      y: 0,
      width: 110,
      height: 110,
    });
  });
});
