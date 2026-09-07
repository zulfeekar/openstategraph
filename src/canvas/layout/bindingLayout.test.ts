import { describe, expect, it } from 'vitest';
import { BINDING_SIDE } from '@core/model/contracts/ports';
import {
  byDeclaredOrder,
  equipmentIds,
  isBindingEdge,
  placeConsumer,
  planShelves,
  reservedSize,
  type LayoutBox,
  type LayoutEdge,
} from './bindingLayout';

const flow = (sourceId: string, targetId: string, portRank = 0): LayoutEdge => ({
  source: { nodeId: sourceId, side: 'right', portRank },
  target: { nodeId: targetId, side: 'left', portRank: 0 },
});

const binding = (providerId: string, consumerId: string): LayoutEdge => ({
  source: { nodeId: providerId, side: BINDING_SIDE.provider, portRank: 0 },
  target: { nodeId: consumerId, side: BINDING_SIDE.consumer, portRank: 0 },
});

const box = (id: string, width = 252, height = 120): LayoutBox => ({ id, width, height });

describe('isBindingEdge', () => {
  it('recognises provider→consumer as a binding', () => {
    expect(isBindingEdge(binding('t', 'a'))).toBe(true);
  });

  it('leaves an ordinary flow edge alone', () => {
    expect(isBindingEdge(flow('a', 'b'))).toBe(false);
  });

  it('needs BOTH ends to agree', () => {
    // A `result` output landing on an agent's tool bus is not a binding: the
    // value is a stage of the flow that happens to arrive at a bus-shaped
    // port. Classifying on one end would rank it as equipment and hide a real
    // step of the graph under a card.
    expect(
      isBindingEdge({
        source: { nodeId: 'a', side: 'right', portRank: 0 },
        target: { nodeId: 'b', side: BINDING_SIDE.consumer, portRank: 0 },
      }),
    ).toBe(false);
  });
});

describe('equipmentIds', () => {
  it('names a node whose every edge is a binding it provides', () => {
    const ids = equipmentIds([box('t'), box('a')], [binding('t', 'a')]);
    expect([...ids]).toEqual(['t']);
  });

  it('does not name the consumer', () => {
    const ids = equipmentIds([box('t'), box('a'), box('b')], [binding('t', 'a'), flow('a', 'b')]);
    expect(ids.has('a')).toBe(false);
  });

  it('keeps a tool that is also fed by the flow', () => {
    // It is a stage AND equipment, so it has a rank of its own and dagre must
    // keep ranking it — pulling it out would leave its flow input dangling
    // across the whole diagram.
    const ids = equipmentIds(
      [box('cfg'), box('t'), box('a')],
      [flow('cfg', 't'), binding('t', 'a')],
    );
    expect(ids.has('t')).toBe(false);
  });

  it('ignores a node with no edges at all', () => {
    expect([...equipmentIds([box('lonely')], [])]).toEqual([]);
  });
});

describe('planShelves', () => {
  it('gathers a consumer’s tools into one shelf, in edge order', () => {
    const shelves = planShelves(
      [box('a'), box('t1', 200, 90), box('t2', 100, 140)],
      [binding('t1', 'a'), binding('t2', 'a')],
      20,
    );
    expect(shelves).toHaveLength(1);
    expect(shelves[0]!.consumerId).toBe('a');
    expect(shelves[0]!.itemIds).toEqual(['t1', 't2']);
    // A row: widths plus one gap, and as tall as its tallest member.
    expect(shelves[0]!.width).toBe(200 + 20 + 100);
    expect(shelves[0]!.height).toBe(140);
  });

  it('gives a shared tool to its first consumer only', () => {
    // Reserving space on both would inflate two ranks for one card, and
    // placing it between them would put it in space no rank reserved.
    const shelves = planShelves(
      [box('a'), box('b'), box('t')],
      [binding('t', 'a'), binding('t', 'b')],
      20,
    );
    expect(shelves.map((s) => s.consumerId)).toEqual(['a']);
    expect(shelves[0]!.itemIds).toEqual(['t']);
  });

  it('has nothing to say about a graph with no bindings', () => {
    expect(planShelves([box('a'), box('b')], [flow('a', 'b')], 20)).toEqual([]);
  });
});

describe('byDeclaredOrder', () => {
  it('stacks one node’s branches in port order however they arrive', () => {
    // Dagre seeds its crossing sweep from the order edges arrive in, so a
    // router's branches have to reach it top-to-bottom down the card's footer.
    const edges = [flow('r', 'c', 2), flow('r', 'a', 0), flow('r', 'b', 1)];
    const sorted = [...edges].sort(byDeclaredOrder(['r']));
    expect(sorted.map((e) => e.target.nodeId)).toEqual(['a', 'b', 'c']);
  });

  it('groups by node in layout order before looking at ports', () => {
    const edges = [flow('z', 'x', 0), flow('a', 'y', 9)];
    expect([...edges].sort(byDeclaredOrder(['a', 'z'])).map((e) => e.source.nodeId)).toEqual([
      'a',
      'z',
    ]);
  });

  it('sends a node it has never heard of to the back rather than to the front', () => {
    // An unknown source must not displace the ordering that was established.
    const edges = [flow('ghost', 'x', 0), flow('a', 'y', 5)];
    expect([...edges].sort(byDeclaredOrder(['a'])).map((e) => e.source.nodeId)).toEqual([
      'a',
      'ghost',
    ]);
  });
});

describe('reservedSize', () => {
  const shelf = { consumerId: 'a', itemIds: ['t'], width: 300, height: 90 };

  it('adds the shelf below the card in horizontal flow', () => {
    expect(reservedSize(box('a', 252, 200), shelf, 'horizontal', 20)).toEqual({
      // 300-wide shelf under a 252 card: the band is as wide as the wider of
      // the two, or the row's ends hang over the neighbouring ranks.
      width: 300,
      height: 200 + 20 + 90,
    });
  });

  it('keeps the card’s own width when the shelf is narrower', () => {
    const narrow = { consumerId: 'a', itemIds: ['t'], width: 100, height: 90 };
    expect(reservedSize(box('a', 252, 200), narrow, 'horizontal', 20).width).toBe(252);
  });

  it('adds the shelf beside the card in vertical flow', () => {
    // The bus rotates with the reading direction (`resolvePortSide`), so the
    // shelf rotates with it — otherwise the reserved band and the port that
    // gathers the lines end up on opposite sides of the card.
    expect(reservedSize(box('a', 252, 200), shelf, 'vertical', 20)).toEqual({
      width: 252 + 20 + 300,
      height: 200,
    });
  });

  it('grows the cross axis in vertical flow too when the column is taller', () => {
    const tall = { consumerId: 'a', itemIds: ['t'], width: 100, height: 600 };
    expect(reservedSize(box('a', 252, 200), tall, 'vertical', 20).height).toBe(600);
  });

  it('reserves nothing for a card with no shelf', () => {
    expect(reservedSize(box('a', 252, 200), undefined, 'horizontal', 20)).toEqual({
      width: 252,
      height: 200,
    });
  });
});

describe('placeConsumer', () => {
  const boxes = [box('a', 252, 200), box('t1', 200, 90), box('t2', 100, 60)];
  const shelf = { consumerId: 'a', itemIds: ['t1', 't2'], width: 320, height: 90 };

  it('centres card and shelf in the reserved band, shelf underneath', () => {
    const placed = placeConsumer(
      { x: 100, y: 50 },
      box('a', 252, 200),
      shelf,
      boxes,
      'horizontal',
      20,
    );
    // The 320-wide shelf sets the band, so the 252 card is centred in it.
    expect(placed.card).toEqual({ x: 100 + (320 - 252) / 2, y: 50 });
    expect(placed.items.get('t1')).toEqual({ x: 100, y: 50 + 200 + 20 });
    expect(placed.items.get('t2')).toEqual({ x: 100 + 200 + 20, y: 50 + 200 + 20 });
  });

  it('puts the card at the right of its reserved box in vertical flow', () => {
    const placed = placeConsumer(
      { x: 100, y: 50 },
      box('a', 252, 200),
      shelf,
      boxes,
      'vertical',
      20,
    );
    // Reserved width is 252 + 20 + 320; the card sits after the shelf.
    expect(placed.card).toEqual({ x: 100 + 320 + 20, y: 50 });
    // Column centred beside the card: total column height 90 + 20 + 60 = 170,
    // so it starts at (200 - 170) / 2 = 15 below the card top.
    expect(placed.items.get('t1')).toEqual({ x: 100 + 320 - 200, y: 50 + 15 });
    expect(placed.items.get('t2')).toEqual({ x: 100 + 320 - 100, y: 50 + 15 + 90 + 20 });
  });

  it('leaves a card with no shelf exactly where the layout put it', () => {
    const placed = placeConsumer(
      { x: 7, y: 9 },
      box('a', 252, 200),
      undefined,
      boxes,
      'horizontal',
      20,
    );
    expect(placed.card).toEqual({ x: 7, y: 9 });
    expect(placed.items.size).toBe(0);
  });
});
