import type { Point } from '@core/kernel/geometry';
import { BINDING_SIDE, type FlowDirection, type PortSide } from '@core/model/contracts/ports';

/**
 * Where equipment goes when the flow is laid out.
 *
 * **The problem.** A tool is wired *tool → agent*, so a layered layout reads it
 * as a predecessor and gives it a rank of its own — one column earlier than the
 * agent that uses it, beside the router that decides which agent runs. Two
 * things then go wrong at once. The tool card reads as a *stage of the flow*,
 * which it is not; and its line has to cross every branch the router fans out
 * before it reaches the bus under its agent. On `chinook-assistant` that was
 * measured: one binding curve ran straight across the card it was bound to.
 *
 * The model already draws the distinction this module needs. `BINDING_SIDE`
 * says a capability is offered from a card's *top* and gathered on a bus slung
 * under the card that uses it — across the reading axis, deliberately, "so a
 * binding never looks like a stage of the flow". Layout simply had not been
 * told. So the classification here is not a new rule; it is the existing one,
 * read by the thing that positions cards.
 *
 * **The move.** Equipment is taken out of the ranking entirely and hung under
 * its consumer, and the space it needs is added to the consumer's own box
 * *before* layout runs. That reservation is the part that matters: the layout
 * engine keeps its neighbours clear of a band that turns out to hold tools,
 * so nothing has to be nudged afterwards and nothing can collide. It mirrors
 * how ELK defines spacing — measured from a node's *margin*, which
 * "encompasses the node, its ports, and labels" — with a tool shelf as one
 * more thing inside the consumer's margin.
 *
 * Pure by construction: boxes and edges in, positions out. No JointJS, no
 * paper, no DOM — which is why the rules are unit tested rather than eyeballed.
 */

/** One end of an edge, reduced to what layout reasons about. */
export interface LayoutEnd {
  readonly nodeId: string;
  /** The port's *horizontal* side — the role, before the flow rotation. */
  readonly side: PortSide;
  /** The port's index in its node's own port list. */
  readonly portRank: number;
}

export interface LayoutEdge {
  readonly source: LayoutEnd;
  readonly target: LayoutEnd;
}

/** A card, reduced to what layout reasons about. */
export interface LayoutBox {
  readonly id: string;
  readonly width: number;
  readonly height: number;
}

export interface Size {
  readonly width: number;
  readonly height: number;
}

/** Equipment gathered under one consumer, measured as a block. */
export interface Shelf {
  readonly consumerId: string;
  /** In edge order, so the picture matches the order the links were made. */
  readonly itemIds: readonly string[];
  readonly width: number;
  readonly height: number;
}

/**
 * Is this edge a *binding* — a capability attached to a step — rather than a
 * stage of the flow?
 *
 * Both ends must agree. A `result` output landing on an agent's tool bus is a
 * real step of the graph that happens to arrive at a bus-shaped port; reading
 * only the target side would classify it as equipment and hide a stage of the
 * workflow under a card.
 *
 * **Why this reads `side` and not a separate `role`.** Splitting the two — a
 * `role` for this classifier, a `side` for the dot — was considered when
 * `skill` moved back to the left edge, and rejected. The two are one claim seen
 * at two scales: *equipment lives off the reading axis*. A port that was
 * equipment for layout but drawn on-axis would put its provider card on the
 * shelf **below** the consumer while its wire entered from the **left** — a
 * line travelling down, along and back up to a dot it started beside, which is
 * the very defect the shelf exists to prevent. A second field only earns its
 * place once some port needs those two answers to differ; none does, and
 * `skill` is the evidence that when they differ, the picture is worse.
 */
export function isBindingEdge(edge: LayoutEdge): boolean {
  return edge.source.side === BINDING_SIDE.provider && edge.target.side === BINDING_SIDE.consumer;
}

/**
 * The nodes that are equipment: every edge they touch is a binding they
 * provide.
 *
 * The "every" is load-bearing. A tool that is itself fed by the flow — a
 * search tool configured by an upstream node — is a stage *and* equipment, so
 * it keeps its rank; pulling it out would leave its flow input stretched
 * across the whole diagram to a card parked under someone else.
 */
export function equipmentIds(
  boxes: readonly LayoutBox[],
  edges: readonly LayoutEdge[],
): ReadonlySet<string> {
  const touched = new Map<string, { total: number; provided: number }>();
  const bump = (id: string, provided: boolean): void => {
    const tally = touched.get(id) ?? { total: 0, provided: 0 };
    touched.set(id, { total: tally.total + 1, provided: tally.provided + (provided ? 1 : 0) });
  };
  for (const edge of edges) {
    const bindingEdge = isBindingEdge(edge);
    bump(edge.source.nodeId, bindingEdge);
    bump(edge.target.nodeId, false);
  }
  const equipment = new Set<string>();
  for (const boxItem of boxes) {
    const tally = touched.get(boxItem.id);
    if (tally && tally.total > 0 && tally.total === tally.provided) equipment.add(boxItem.id);
  }
  return equipment;
}

/**
 * One shelf per consumer that has equipment, measured as a block.
 *
 * A tool bound to two agents goes on the shelf of the **first** consumer it
 * was wired to, and reaches the other with an ordinary binding curve. The two
 * alternatives were both worse: reserving space on every consumer inflates
 * several ranks for one card, and centring the tool between its consumers puts
 * it in space no rank reserved — reintroducing exactly the overlap the shelf
 * exists to prevent.
 */
export function planShelves(
  boxes: readonly LayoutBox[],
  edges: readonly LayoutEdge[],
  gap: number,
): readonly Shelf[] {
  const equipment = equipmentIds(boxes, edges);
  const sizeOf = new Map(boxes.map((boxItem) => [boxItem.id, boxItem]));
  const claimed = new Set<string>();
  const byConsumer = new Map<string, string[]>();

  for (const edge of edges) {
    if (!isBindingEdge(edge)) continue;
    const itemId = edge.source.nodeId;
    if (!equipment.has(itemId) || claimed.has(itemId)) continue;
    claimed.add(itemId);
    const items = byConsumer.get(edge.target.nodeId) ?? [];
    items.push(itemId);
    byConsumer.set(edge.target.nodeId, items);
  }

  const shelves: Shelf[] = [];
  for (const [consumerId, itemIds] of byConsumer) {
    let width = 0;
    let height = 0;
    itemIds.forEach((itemId, index) => {
      const item = sizeOf.get(itemId);
      if (!item) return;
      width += item.width + (index > 0 ? gap : 0);
      height = Math.max(height, item.height);
    });
    shelves.push({ consumerId, itemIds, width, height });
  }
  return shelves;
}

/**
 * Orders edges the way a reader would list them: node by node in layout order,
 * and within a node, port by port down the card's footer.
 *
 * This is not cosmetic. Dagre seeds its crossing-minimisation sweep from the
 * order edges arrive in, and it is *very* sensitive to it: on
 * `chinook-assistant`, handing the same eleven links to the same layout in
 * reverse took the picture from no crossings at all to two links over a card
 * and seven over each other. Declaration order happened to be the good order,
 * because a router's branches are authored top to bottom — but "happened to
 * be" is not a property, and an edge list survives an edit, a paste or a JSON
 * round trip without promising to keep its order.
 *
 * So the good order is imposed rather than inherited. A router's branches are
 * fed to dagre in the order their ports appear on the card, which is the order
 * the labels read, which is the order the reader expects the lines to stack.
 */
export function byDeclaredOrder(
  nodeOrder: readonly string[],
): (a: LayoutEdge, b: LayoutEdge) => number {
  const rankOfNode = new Map(nodeOrder.map((id, index) => [id, index]));
  const key = (edge: LayoutEdge): [number, number] => [
    rankOfNode.get(edge.source.nodeId) ?? Number.MAX_SAFE_INTEGER,
    edge.source.portRank,
  ];
  return (a, b) => {
    const [an, ap] = key(a);
    const [bn, bp] = key(b);
    return an - bn || ap - bp;
  };
}

/**
 * The box the layout engine should reserve for a card — its own size plus the
 * shelf it will carry.
 *
 * The shelf grows the card along the **cross-flow** axis, because that is the
 * axis the bus rotates onto: `resolvePortSide` swings a `bottom` bus round to
 * the card's flank when the canvas reads top-to-bottom, and the reserved band
 * has to follow it. Growing the wrong axis would reserve space on the side the
 * lines do not arrive from and leave the shelf overlapping a neighbour.
 */
export function reservedSize(
  boxItem: LayoutBox,
  shelf: Shelf | undefined,
  flow: FlowDirection,
  gap: number,
): Size {
  if (!shelf) return { width: boxItem.width, height: boxItem.height };
  // Both axes. A shelf of three tools is far wider than the agent above it, and
  // reserving only the axis it grows along lets the ends of the row hang over
  // whatever the neighbouring ranks hold — which is how a three-tool agent
  // parked its shelf on top of the markdown card beside it.
  return flow === 'horizontal'
    ? {
        width: Math.max(boxItem.width, shelf.width),
        height: boxItem.height + gap + shelf.height,
      }
    : {
        width: boxItem.width + gap + shelf.width,
        height: Math.max(boxItem.height, shelf.height),
      };
}

export interface Placement {
  readonly card: Point;
  readonly items: ReadonlyMap<string, Point>;
}

/**
 * Where the card and its equipment sit inside the box that was reserved.
 *
 * The single place the reservation's geometry is spelled out, so `reservedSize`
 * and this cannot disagree about which end of the reserved box holds the card.
 * The card takes the end the flow arrives at — the top in a left-to-right
 * reading, the right-hand end in a top-to-bottom one — and the shelf fills the
 * rest, centred on the card so the bus sits over the middle of its tools.
 */
export function placeConsumer(
  reservedTopLeft: Point,
  boxItem: LayoutBox,
  shelf: Shelf | undefined,
  boxes: readonly LayoutBox[],
  flow: FlowDirection,
  gap: number,
): Placement {
  const items = new Map<string, Point>();
  if (!shelf) return { card: { ...reservedTopLeft }, items };

  const sizeOf = new Map(boxes.map((entry) => [entry.id, entry]));

  const reserved = reservedSize(boxItem, shelf, flow, gap);

  if (flow === 'horizontal') {
    // Card and shelf are each centred in the reserved band, so the bus sits
    // over the middle of its tools whichever of the two is wider.
    const card = {
      x: reservedTopLeft.x + (reserved.width - boxItem.width) / 2,
      y: reservedTopLeft.y,
    };
    const top = card.y + boxItem.height + gap;
    let x = reservedTopLeft.x + (reserved.width - shelf.width) / 2;
    for (const itemId of shelf.itemIds) {
      const item = sizeOf.get(itemId);
      if (!item) continue;
      items.set(itemId, { x, y: top });
      x += item.width + gap;
    }
    return { card, items };
  }

  const card = {
    x: reservedTopLeft.x + shelf.width + gap,
    y: reservedTopLeft.y + (reserved.height - boxItem.height) / 2,
  };
  const columnHeight = shelf.itemIds.reduce((total, itemId, index) => {
    const item = sizeOf.get(itemId);
    return total + (item ? item.height : 0) + (index > 0 ? gap : 0);
  }, 0);
  let y = reservedTopLeft.y + (reserved.height - columnHeight) / 2;
  for (const itemId of shelf.itemIds) {
    const item = sizeOf.get(itemId);
    if (!item) continue;
    // Right-aligned against the card, so every provider dot is the same short
    // hop from the bus rather than a hop that grows with the tool's width.
    items.set(itemId, { x: reservedTopLeft.x + shelf.width - item.width, y });
    y += item.height + gap;
  }
  return { card, items };
}
