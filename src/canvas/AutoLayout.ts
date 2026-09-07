import type { dia } from '@joint/core';
import { DirectedGraph } from '@joint/layout-directed-graph';
import type { Point, Rect } from '@core/kernel/geometry';
import { type FlowDirection, sideOf } from '@core/model/contracts/ports';
import { GRAPH_SPACING, GROUP } from '@design/tokens';
import { depthFirstOrder, fitContainers } from '@core/model/containerFit';
import type { WorkflowController } from '@controller/WorkflowController';
import {
  byDeclaredOrder,
  equipmentIds,
  isBindingEdge,
  placeConsumer,
  planShelves,
  reservedSize,
  type LayoutBox,
  type LayoutEdge,
} from './layout/bindingLayout';
import { backEdgeLanes, type LaneCandidate } from './layout/backEdgeLane';

export interface AutoLayoutOptions {
  /** `LR` reads left-to-right, matching how these graphs are drawn. */
  readonly rankDir?: 'LR' | 'TB' | 'RL' | 'BT';
  /** Gap between ranks (columns in `LR`). */
  readonly rankSep?: number;
  /** Gap between nodes within a rank. */
  readonly nodeSep?: number;
}

const FLOW_OF: Record<'LR' | 'TB' | 'RL' | 'BT', FlowDirection> = {
  LR: 'horizontal',
  RL: 'horizontal',
  TB: 'vertical',
  BT: 'vertical',
};

/**
 * Dagre-based automatic layout.
 *
 * Two things it does that a bare `DirectedGraph.layout(graph)` does not.
 *
 * **It lays out the flow, not everything with a line attached.** A tool is
 * wired *tool → agent*, so a layered algorithm reads it as a predecessor and
 * gives it a column of its own beside the router — where it reads as a stage
 * of the flow and its line has to cross every branch the router fans out.
 * Bindings and the equipment that provides them are therefore withheld from
 * the ranking and hung under their consumer by `layout/bindingLayout`, with
 * the space they need added to the consumer's box *before* dagre runs, so
 * neighbouring ranks are kept clear of the band the tools will occupy.
 *
 * **It never writes to the graph.** `@joint/layout-directed-graph` normally
 * writes positions straight onto the cells, which would bypass the model and
 * desync the two. `setPosition` intercepts every result instead, so the
 * positions are only ever *read*, then committed through the controller as one
 * undoable move and re-applied by the adapter. The document stays the source
 * of truth and one Cmd-Z reverses the whole arrangement.
 *
 * Containers and annotations are excluded: dagre reasons about a directed
 * graph, and a frame has no edges — including it would have dagre park it in
 * an arbitrary rank of its own instead of around its children.
 */
export class AutoLayout {
  constructor(
    private readonly graph: dia.Graph,
    private readonly controller: WorkflowController,
  ) {}

  run(options: AutoLayoutOptions = {}): void {
    const rankDir = options.rankDir ?? 'LR';
    const flow = FLOW_OF[rankDir];

    const elements = this.graph
      .getElements()
      .filter((element) => this.controller.model.node(String(element.id))?.kind === 'standard');
    if (elements.length < 2) return;

    const boxes: LayoutBox[] = elements.map((element) => {
      const size = element.size();
      return { id: String(element.id), width: size.width, height: size.height };
    });
    const boxById = new Map(boxes.map((boxItem) => [boxItem.id, boxItem]));
    const laidIds = new Set(boxById.keys());

    const links = this.graph.getLinks();
    const edgeOf = new Map<dia.Link, LayoutEdge>();
    for (const link of links) {
      const edge = this.describe(link);
      if (edge && laidIds.has(edge.source.nodeId) && laidIds.has(edge.target.nodeId)) {
        edgeOf.set(link, edge);
      }
    }
    const edges = [...edgeOf.values()];

    const shelves = planShelves(boxes, edges, GRAPH_SPACING.node);
    const shelfOf = new Map(shelves.map((shelf) => [shelf.consumerId, shelf]));
    const equipment = equipmentIds(boxes, edges);
    const shelved = new Set(shelves.flatMap((shelf) => [...shelf.itemIds]));

    // Dagre sees the flow only: no equipment, and no binding edges to rank it
    // by. An unshelved equipment node — a tool bound to a container, say — is
    // left in so it is still positioned rather than stacked at the origin.
    const rankedElements = elements.filter(
      (element) => !(equipment.has(String(element.id)) && shelved.has(String(element.id))),
    );
    // Sorted, not merely collected: dagre seeds its crossing-minimisation
    // sweep from the order edges arrive in, and on `chinook-assistant` the
    // reverse order costs two links over a card and seven over each other.
    const order = byDeclaredOrder(rankedElements.map((element) => String(element.id)));
    const rankedLinks = [...edgeOf.entries()]
      .filter(([, edge]) => !isBindingEdge(edge))
      .sort(([, a], [, b]) => order(a, b))
      .map(([link]) => link);
    if (rankedElements.length < 2) return;

    const reserved = new Map<string, Point>();
    DirectedGraph.layout([...rankedElements, ...rankedLinks], {
      rankDir,
      rankSep: options.rankSep ?? GRAPH_SPACING.rank,
      nodeSep: options.nodeSep ?? GRAPH_SPACING.node,
      edgeSep: GRAPH_SPACING.edge,
      marginX: GRAPH_SPACING.margin,
      marginY: GRAPH_SPACING.margin,
      // The card's reserved footprint, which is its own size plus any shelf.
      // Dagre keeps its neighbours clear of the whole thing, so the tools land
      // in space that was set aside for them rather than on top of a rank.
      exportElement: (element: dia.Element) => {
        const id = String(element.id);
        const boxItem = boxById.get(id);
        const size = element.size();
        return boxItem ? reservedSize(boxItem, shelfOf.get(id), flow, GRAPH_SPACING.shelf) : size;
      },
      // Read, never write: this is what keeps the graph a faithful projection
      // of the model while the layout is being computed.
      setPosition: (
        element: dia.Element,
        glNode: { x: number; y: number; width: number; height: number },
      ) => {
        reserved.set(String(element.id), {
          x: glNode.x - glNode.width / 2,
          y: glNode.y - glNode.height / 2,
        });
      },
      // Dagre's own vertices are its dummy-node chain — one point per rank a
      // link crosses, in the middle of the gap. They are not waypoints a user
      // would recognise, and the router derives a better run from the two
      // ports. The waypoints this layout *does* place are the back-edge lanes
      // below, which are a deliberate decision rather than a by-product.
      setVertices: false,
      setLabels: false,
    });

    const placed = new Map<string, Point>();
    for (const [id, topLeft] of reserved) {
      const boxItem = boxById.get(id);
      if (!boxItem) continue;
      const placement = placeConsumer(
        topLeft,
        boxItem,
        shelfOf.get(id),
        boxes,
        flow,
        GRAPH_SPACING.shelf,
      );
      placed.set(id, placement.card);
      for (const [itemId, point] of placement.items) placed.set(itemId, point);
    }

    const settled = new Map<string, Point>();
    for (const element of elements) {
      const nodeId = String(element.id);
      const next = placed.get(nodeId);
      if (!next) continue;
      settled.set(nodeId, { x: Math.round(next.x), y: Math.round(next.y) });
    }
    if (settled.size === 0) return;

    const fits = this.refitContainers(settled);

    // Ancestors before descendants. The adapter moves a container with
    // `{ deep: true }` — deliberately, so dragging a frame carries what is in
    // it — while the model moves only the node it was told about. So a frame's
    // move shifts children the graph already knows the position of, and only a
    // later *absolute* set for each descendant brings the two back into step.
    const model = this.controller.model;
    const ordered = depthFirstOrder(
      [...settled.keys(), ...fits.keys()],
      (id) => model.node(id)?.parentId ?? null,
    );

    const moves: { nodeId: string; position: Point }[] = [];
    for (const nodeId of ordered) {
      const target = fits.get(nodeId) ?? settled.get(nodeId);
      if (!target) continue;
      const node = model.node(nodeId);
      if (!node) continue;
      const position = { x: Math.round(target.x), y: Math.round(target.y) };
      // A node whose own position is unchanged still has to be re-asserted
      // when an ancestor moved, or the ancestor's deep move leaves it
      // displaced in the graph with the model none the wiser.
      const ancestorMoved = this.hasMovingAncestor(nodeId, moves);
      if (!ancestorMoved && position.x === node.position.x && position.y === node.position.y) {
        continue;
      }
      moves.push({ nodeId, position });
    }

    const resizes = [...fits]
      .map(([nodeId, rect]) => ({ nodeId, rect, node: model.node(nodeId) }))
      .filter(
        (entry) =>
          entry.node != null &&
          (entry.node.size.width !== entry.rect.width ||
            entry.node.size.height !== entry.rect.height),
      );

    const routes = this.replanRoutes(edgeOf, settled, flow);

    if (moves.length === 0 && resizes.length === 0 && routes.length === 0) return;

    // One transaction, so one Cmd-Z reverses the arrangement *and* the frames
    // that were re-wrapped around it *and* the waypoints. Two steps would let a
    // user undo the layout and be left with frames fitted to positions nothing
    // occupies, or a hand-placed point stranded in space.
    this.controller.history.transact('Auto layout', () => {
      if (moves.length > 0) this.controller.nodes.move(moves, false);
      for (const entry of resizes) {
        this.controller.nodes.resize(entry.nodeId, {
          width: entry.rect.width,
          height: entry.rect.height,
        });
      }
      for (const route of routes) {
        this.controller.edges.setVertices(route.edgeId, route.vertices);
      }
    });
  }

  /**
   * What every link's waypoints become when the arrangement re-runs.
   *
   * **Arrange replaces them. All of them.** A hand-placed point is a position
   * in document space, chosen against where the cards were; once every card has
   * moved, that point is no longer the route the user drew, it is a point in
   * space nobody chose — and leaving it there produces a run that detours
   * through empty canvas for no reason a reader can see. Keeping stale points
   * is a worse failure than dropping them, because it is silent, whereas
   * dropping them is not: it happens inside the layout's own single undo step,
   * so one Cmd-Z restores the hand-routing exactly along with the positions,
   * and the Undo button says "Auto layout" while it can.
   *
   * The layout then seeds the one route it genuinely knows better than the
   * router does: a lane, outside the arrangement, for every link that runs
   * against the flow. See `backEdgeLane`.
   */
  private replanRoutes(
    edgeOf: ReadonlyMap<dia.Link, LayoutEdge>,
    settled: ReadonlyMap<string, Point>,
    flow: FlowDirection,
  ): readonly { edgeId: string; vertices: readonly Point[] }[] {
    const rectOf = (nodeId: string): Rect | null => {
      const node = this.controller.model.node(nodeId);
      const position = settled.get(nodeId) ?? node?.position;
      if (!node || !position) return null;
      return { x: position.x, y: position.y, width: node.size.width, height: node.size.height };
    };

    const occupied = [...settled.keys()].map(rectOf).filter((rect): rect is Rect => rect !== null);

    // Bindings are excluded on the same grounds they are excluded from the
    // ranking: equipment sits across the reading axis, so "against the flow"
    // is not a claim that can be made about it.
    const candidates: LaneCandidate[] = [];
    for (const [link, edge] of edgeOf) {
      if (isBindingEdge(edge)) continue;
      const source = rectOf(edge.source.nodeId);
      const target = rectOf(edge.target.nodeId);
      if (!source || !target) continue;
      candidates.push({ edgeId: String(link.id), source, target });
    }

    const lanes = backEdgeLanes(candidates, occupied, flow, GRAPH_SPACING.node);

    const routes: { edgeId: string; vertices: readonly Point[] }[] = [];
    for (const link of edgeOf.keys()) {
      const edgeId = String(link.id);
      const next = lanes.get(edgeId) ?? [];
      const current = this.controller.model.edge(edgeId)?.vertices ?? [];
      const unchanged =
        current.length === next.length &&
        current.every((point, index) => {
          const wanted = next[index];
          return wanted != null && point.x === wanted.x && point.y === wanted.y;
        });
      if (!unchanged) routes.push({ edgeId, vertices: next });
    }
    return routes;
  }

  /**
   * Every container re-wrapped around where its children have *just* been put.
   *
   * The arithmetic — including the nesting order and the childless case — is
   * `fitContainers`, which is pure and tested. This does only the part that
   * needs the model: reading membership and turning settled positions into the
   * rects the children will occupy once the move lands.
   */
  private refitContainers(settled: ReadonlyMap<string, Point>): ReadonlyMap<string, Rect> {
    const model = this.controller.model;
    const containers = model.nodes().filter((node) => node.kind === 'container');
    if (containers.length === 0) return new Map();

    // Where each non-container node will be *after* the move, which is the
    // whole point: fitting against current positions would wrap the frame
    // around where the cards used to be.
    const leafRects = new Map<string, Rect>();
    for (const node of model.nodes()) {
      if (node.kind === 'container') continue;
      const next = settled.get(node.id) ?? node.position;
      leafRects.set(node.id, {
        x: next.x,
        y: next.y,
        width: node.size.width,
        height: node.size.height,
      });
    }

    return fitContainers(
      containers.map((container) => ({
        id: container.id,
        childIds: model.childrenOf(container.id).map((child) => child.id),
        rect: {
          x: container.position.x,
          y: container.position.y,
          width: container.size.width,
          height: container.size.height,
        },
      })),
      leafRects,
      GROUP.padding,
      { width: GROUP.minWidth, height: GROUP.minHeight },
    );
  }

  /** Is any ancestor of this node already in the batch about to move? */
  private hasMovingAncestor(nodeId: string, moves: readonly { nodeId: string }[]): boolean {
    const moving = new Set(moves.map((move) => move.nodeId));
    const seen = new Set<string>();
    let parentId = this.controller.model.node(nodeId)?.parentId ?? null;
    while (parentId && !seen.has(parentId)) {
      if (moving.has(parentId)) return true;
      seen.add(parentId);
      parentId = this.controller.model.node(parentId)?.parentId ?? null;
    }
    return false;
  }

  /**
   * A link reduced to the two port *roles* it connects.
   *
   * `sideOf`, not `resolvePortSide`: whether an edge is a binding is a fact
   * about what the ports are for, and does not change when the canvas is
   * rotated. The reading direction is applied later, once, when the shelf is
   * placed.
   */
  private describe(link: dia.Link): LayoutEdge | null {
    const source = link.get('source') as { id?: unknown; port?: unknown };
    const target = link.get('target') as { id?: unknown; port?: unknown };
    if (source.id === undefined || target.id === undefined) return null;
    const sourceNode = this.controller.model.node(String(source.id));
    const targetNode = this.controller.model.node(String(target.id));
    if (!sourceNode || !targetNode) return null;
    const sourcePortId = String(source.port ?? '');
    const targetPortId = String(target.port ?? '');
    const sourcePort = sourceNode.port(sourcePortId);
    const targetPort = targetNode.port(targetPortId);
    return {
      source: {
        nodeId: String(source.id),
        side: sourcePort ? sideOf(sourcePort) : 'right',
        portRank: sourceNode.ports.findIndex((port) => port.id === sourcePortId),
      },
      target: {
        nodeId: String(target.id),
        side: targetPort ? sideOf(targetPort) : 'left',
        portRank: targetNode.ports.findIndex((port) => port.id === targetPortId),
      },
    };
  }
}
