import { describe, expect, it } from 'vitest';
import type { AbstractNodeModel } from './AbstractNodeModel';
import { AdjacencyIndex } from './AdjacencyIndex';
import type { EdgeModel } from './EdgeModel';
import { GraphQueries } from './GraphQueries';

interface FakeNodeInit {
  id: string;
  type?: string;
  parentId?: string | null;
  isExecutable?: boolean;
  position?: { x: number; y: number };
  size?: { width: number; height: number };
}

const fakeNode = (init: FakeNodeInit) =>
  ({
    id: init.id,
    type: init.type ?? 'test.node',
    parentId: init.parentId ?? null,
    isExecutable: init.isExecutable ?? true,
    position: init.position ?? { x: 0, y: 0 },
    size: init.size ?? { width: 10, height: 10 },
  }) as unknown as AbstractNodeModel;

const fakeEdge = (id: string, sourceId: string, targetId: string, ports = { s: 'out', t: 'in' }) =>
  ({
    id,
    source: { nodeId: sourceId, portId: ports.s },
    target: { nodeId: targetId, portId: ports.t },
  }) as unknown as EdgeModel;

/** Wires a small graph and returns queries plus the raw maps for assertions. */
function build(nodes: FakeNodeInit[], edges: [string, string, string][]) {
  const nodeMap = new Map<string, AbstractNodeModel>();
  const edgeMap = new Map<string, EdgeModel>();
  const adjacency = new AdjacencyIndex();

  for (const n of nodes) {
    const node = fakeNode(n);
    nodeMap.set(node.id, node);
    adjacency.registerNode(node.id);
    if (n.parentId) adjacency.linkChild(n.parentId, node.id);
  }
  for (const [id, source, target] of edges) {
    const edge = fakeEdge(id, source, target);
    edgeMap.set(id, edge);
    adjacency.registerEdge(edge);
  }

  return new GraphQueries(nodeMap, edgeMap, adjacency);
}

describe('GraphQueries', () => {
  describe('edgesOf / edgesInto / edgesFrom', () => {
    it('finds edges touching a node in either direction', () => {
      const queries = build(
        [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
        [
          ['e1', 'a', 'b'],
          ['e2', 'c', 'a'],
        ],
      );
      expect(queries.edgesOf('a').map((e) => e.id).sort()).toEqual(['e1', 'e2']);
    });

    it('filters to only edges landing on a specific port', () => {
      const queries = build([{ id: 'a' }, { id: 'b' }], [['e1', 'a', 'b']]);
      expect(queries.edgesInto({ nodeId: 'b', portId: 'in' })).toHaveLength(1);
      expect(queries.edgesInto({ nodeId: 'b', portId: 'other' })).toHaveLength(0);
    });

    it('filters to only edges leaving a specific port', () => {
      const queries = build([{ id: 'a' }, { id: 'b' }], [['e1', 'a', 'b']]);
      expect(queries.edgesFrom({ nodeId: 'a', portId: 'out' })).toHaveLength(1);
    });
  });

  describe('childrenOf / descendantsOf', () => {
    it('lists direct children only', () => {
      const queries = build(
        [{ id: 'group' }, { id: 'a', parentId: 'group' }, { id: 'b', parentId: 'group' }],
        [],
      );
      expect(queries.childrenOf('group').map((n) => n.id).sort()).toEqual(['a', 'b']);
    });

    it('walks grandchildren too, unlike childrenOf', () => {
      const queries = build(
        [
          { id: 'root' },
          { id: 'mid', parentId: 'root' },
          { id: 'leaf', parentId: 'mid' },
        ],
        [],
      );
      expect(queries.childrenOf('root').map((n) => n.id)).toEqual(['mid']);
      expect(queries.descendantsOf('root').map((n) => n.id).sort()).toEqual(['leaf', 'mid']);
    });
  });

  describe('predecessorsOf / successorsOf', () => {
    it('dedupes multiple edges from the same neighbour', () => {
      const queries = build(
        [{ id: 'a' }, { id: 'b' }],
        [
          ['e1', 'a', 'b'],
          ['e2', 'a', 'b'],
        ],
      );
      expect(queries.predecessorsOf('b').map((n) => n.id)).toEqual(['a']);
      expect(queries.successorsOf('a').map((n) => n.id)).toEqual(['b']);
    });
  });

  describe('countOfType', () => {
    it('counts only nodes of the given type', () => {
      const queries = build(
        [{ id: 'a', type: 'x' }, { id: 'b', type: 'x' }, { id: 'c', type: 'y' }],
        [],
      );
      expect(queries.countOfType('x')).toBe(2);
      expect(queries.countOfType('z')).toBe(0);
    });
  });

  describe('isAncestorOf', () => {
    it('is true for a direct parent and a transitive grandparent', () => {
      const queries = build(
        [{ id: 'root' }, { id: 'mid', parentId: 'root' }, { id: 'leaf', parentId: 'mid' }],
        [],
      );
      expect(queries.isAncestorOf('mid', 'leaf')).toBe(true);
      expect(queries.isAncestorOf('root', 'leaf')).toBe(true);
    });

    it('is false for an unrelated node, and false for itself', () => {
      const queries = build([{ id: 'a' }, { id: 'b' }], []);
      expect(queries.isAncestorOf('a', 'b')).toBe(false);
      expect(queries.isAncestorOf('a', 'a')).toBe(false);
    });
  });

  describe('topologicalOrder', () => {
    it('orders a linear chain upstream-first', () => {
      const queries = build(
        [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
        [
          ['e1', 'a', 'b'],
          ['e2', 'b', 'c'],
        ],
      );
      const { order, cycle } = queries.topologicalOrder();
      expect(cycle).toBeNull();
      expect(order.indexOf('a')).toBeLessThan(order.indexOf('b'));
      expect(order.indexOf('b')).toBeLessThan(order.indexOf('c'));
    });

    it('excludes non-executable nodes from the schedule entirely', () => {
      const queries = build(
        [{ id: 'a' }, { id: 'note', isExecutable: false }, { id: 'b' }],
        [
          ['e1', 'a', 'note'],
          ['e2', 'note', 'b'],
        ],
      );
      const { order } = queries.topologicalOrder();
      expect(order).not.toContain('note');
    });

    it('reports the surviving cycle instead of throwing', () => {
      const queries = build(
        [{ id: 'a' }, { id: 'b' }],
        [
          ['e1', 'a', 'b'],
          ['e2', 'b', 'a'],
        ],
      );
      const { order, cycle } = queries.topologicalOrder();
      expect(order).toHaveLength(0);
      expect(cycle).not.toBeNull();
      expect([...(cycle ?? [])].sort()).toEqual(['a', 'b']);
    });
  });

  describe('bounds', () => {
    it('is null for an empty graph', () => {
      const queries = build([], []);
      expect(queries.bounds()).toBeNull();
    });

    it('unions every node rectangle', () => {
      const queries = build(
        [
          { id: 'a', position: { x: 0, y: 0 }, size: { width: 10, height: 10 } },
          { id: 'b', position: { x: 100, y: 100 }, size: { width: 10, height: 10 } },
        ],
        [],
      );
      const bounds = queries.bounds();
      expect(bounds).toEqual({ x: 0, y: 0, width: 110, height: 110 });
    });
  });
});
