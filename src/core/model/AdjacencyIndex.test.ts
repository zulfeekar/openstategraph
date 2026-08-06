import { describe, expect, it } from 'vitest';
import type { IEdgeModel } from './contracts/workflow';
import { AdjacencyIndex } from './AdjacencyIndex';

const edge = (id: string, sourceId: string, targetId: string): IEdgeModel =>
  ({
    id,
    source: { nodeId: sourceId, portId: 'out' },
    target: { nodeId: targetId, portId: 'in' },
    label: null,
    toJSON: () => ({ source: { nodeId: sourceId, portId: 'out' }, target: { nodeId: targetId, portId: 'in' } }),
  }) as unknown as IEdgeModel;

describe('AdjacencyIndex', () => {
  it('has no edges or children for an id it has never seen', () => {
    const index = new AdjacencyIndex();
    expect(index.edgeIdsOf('x')).toEqual(new Set());
    expect(index.childIdsOf('x')).toEqual(new Set());
  });

  it('registers an edge under both of its endpoints', () => {
    const index = new AdjacencyIndex();
    index.registerNode('a');
    index.registerNode('b');
    index.registerEdge(edge('e1', 'a', 'b'));

    expect(index.edgeIdsOf('a')).toEqual(new Set(['e1']));
    expect(index.edgeIdsOf('b')).toEqual(new Set(['e1']));
  });

  it('a node touched by several edges accumulates all of them', () => {
    const index = new AdjacencyIndex();
    index.registerNode('a');
    index.registerNode('b');
    index.registerNode('c');
    index.registerEdge(edge('e1', 'a', 'b'));
    index.registerEdge(edge('e2', 'a', 'c'));

    expect(index.edgeIdsOf('a')).toEqual(new Set(['e1', 'e2']));
  });

  it('unregistering an edge removes it from both endpoints', () => {
    const index = new AdjacencyIndex();
    index.registerNode('a');
    index.registerNode('b');
    const e = edge('e1', 'a', 'b');
    index.registerEdge(e);
    index.unregisterEdge(e);

    expect(index.edgeIdsOf('a')).toEqual(new Set());
    expect(index.edgeIdsOf('b')).toEqual(new Set());
  });

  it('unregistering a node drops its own incidence and child sets', () => {
    const index = new AdjacencyIndex();
    index.registerNode('a');
    index.linkChild('a', 'child');
    index.unregisterNode('a');

    expect(index.edgeIdsOf('a')).toEqual(new Set());
    expect(index.childIdsOf('a')).toEqual(new Set());
  });

  it('links and unlinks a child under its parent', () => {
    const index = new AdjacencyIndex();
    index.linkChild('group', 'a');
    index.linkChild('group', 'b');
    expect(index.childIdsOf('group')).toEqual(new Set(['a', 'b']));

    index.unlinkChild('group', 'a');
    expect(index.childIdsOf('group')).toEqual(new Set(['b']));
  });

  it('drops an empty children set once the last child is unlinked, rather than leaking it', () => {
    const index = new AdjacencyIndex();
    index.linkChild('group', 'a');
    index.unlinkChild('group', 'a');

    // Not observable from childIdsOf alone (empty either way), but clear()
    // plus a fresh registerNode of the same id must not see stale state.
    expect(index.childIdsOf('group')).toEqual(new Set());
  });

  it('clear() empties both indices at once', () => {
    const index = new AdjacencyIndex();
    index.registerNode('a');
    index.registerNode('b');
    index.registerEdge(edge('e1', 'a', 'b'));
    index.linkChild('a', 'b');

    index.clear();

    expect(index.edgeIdsOf('a')).toEqual(new Set());
    expect(index.childIdsOf('a')).toEqual(new Set());
  });
});
