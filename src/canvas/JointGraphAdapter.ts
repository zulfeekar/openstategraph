import { dia } from '@joint/core';
import { DisposableStore, type IDisposable } from '@core/kernel/Disposable';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { INodeModel, NodeId } from '@core/model/contracts/node';
import {
  resolvePortSide,
  type FlowDirection,
  type IPortDescriptor,
  type PortSide,
} from '@core/model/contracts/ports';
import type { EdgeId, IEdgeModel } from '@core/model/contracts/workflow';
import { HtmlNode, FlowLink, PORT_GROUP, type NodeGeometry } from './shapes/HtmlNode';
import { branchRank, edgeLabelText, labelPlacement, linkConnector } from './links/edgeDecoration';

/**
 * Projects the workflow model onto a JointJS graph.
 *
 * Strictly one-way: model → graph. User gestures never write to the model
 * directly; they go through the controller's commands, and the resulting
 * model events come back through here. That single rule is what keeps undo
 * honest — there is no path by which the canvas and the document can
 * disagree, because the canvas is only ever a projection.
 *
 * The graph is therefore disposable: throwing it away and rebuilding from
 * the model is always safe, which is exactly what an import does.
 */
export class JointGraphAdapter implements IDisposable {
  private readonly disposables = new DisposableStore();
  /** Suppresses re-entrant writes while the adapter itself is mutating. */
  private applying = false;

  constructor(
    private readonly model: WorkflowModel,
    private readonly graph: dia.Graph,
    private readonly registry: ModelRegistry,
    private flow: FlowDirection = 'horizontal',
  ) {
    this.rebuild();
    this.listen();
  }

  /**
   * Re-projects everything whose geometry depends on the reading direction.
   *
   * Port sides rotate (`resolvePortSide`) and label rhythm changes with them,
   * so both the seeded port placement and every link label are re-derived.
   * Still one-way: nothing here writes to the document, and the direction
   * itself is a preference the shell owns.
   */
  setFlowDirection(flow: FlowDirection): void {
    if (this.flow === flow) return;
    this.flow = flow;
    this.transaction(() => {
      for (const node of this.model.nodes()) {
        const element = this.element(node.id);
        element?.prop(['ports', 'items'], this.portItems(node));
      }
      for (const edge of this.model.edges()) {
        this.applyGeometryHints(edge);
        this.applyLabel(edge);
      }
    });
  }

  /** Discards the graph and re-projects the whole document. */
  rebuild(): void {
    this.transaction(() => {
      this.graph.clear();

      // Elements must be *in the graph* before links are built: `createLink`
      // refuses to attach to an endpoint the graph doesn't know about, so
      // building both lists up front and resetting once would silently drop
      // every link.
      this.graph.resetCells(this.model.nodes().map((node) => this.createElement(node)));

      const links: dia.Link[] = [];
      for (const edge of this.model.edges()) {
        const link = this.createLink(edge);
        if (link) links.push(link);
      }
      if (links.length > 0) this.graph.addCells(links);

      // Embedding last, for the same reason — both ends have to exist.
      for (const node of this.model.nodes()) {
        if (!node.parentId) continue;
        this.graph.getCell(node.parentId)?.embed(this.graph.getCell(node.id));
      }
    });
  }

  element(nodeId: NodeId): dia.Element | undefined {
    const cell = this.graph.getCell(nodeId);
    return cell?.isElement() ? cell : undefined;
  }

  link(edgeId: EdgeId): dia.Link | undefined {
    const cell = this.graph.getCell(edgeId);
    return cell?.isLink() ? cell : undefined;
  }

  /**
   * Writes measured card geometry onto a cell.
   *
   * Called by the React card after layout. Guarded against no-op writes:
   * a ResizeObserver fires on every reflow, and re-setting an identical
   * height would churn the graph on every repaint.
   */
  applyGeometry(nodeId: NodeId, geometry: NodeGeometry): boolean {
    const element = this.element(nodeId);
    const node = this.model.node(nodeId);
    if (!element || !node) return false;

    let changed = false;

    const current = element.size();
    const height = Math.max(1, Math.round(geometry.height));
    if (Math.abs(current.height - height) >= 1) {
      this.transaction(() => element.resize(current.width, height));
      changed = true;
    }

    for (const [portId, point] of Object.entries(geometry.ports)) {
      const existing = element.portProp(portId, 'position/args') as
        { x?: number; y?: number } | undefined;
      if (
        existing &&
        Math.abs((existing.x ?? 0) - point.x) < 0.5 &&
        Math.abs((existing.y ?? 0) - point.y) < 0.5
      ) {
        continue;
      }
      this.transaction(() => {
        element.portProp(portId, 'position/args', { x: point.x, y: point.y });
      });
      changed = true;
    }

    return changed;
  }

  /** True while the adapter is writing, so interaction handlers can bail. */
  get isApplying(): boolean {
    return this.applying;
  }

  dispose(): void {
    this.disposables.dispose();
  }

  /* ================================================================ *
   * Model → graph
   * ================================================================ */

  private listen(): void {
    const on = <K extends Parameters<WorkflowModel['on']>[0]>(
      type: K,
      handler: Parameters<WorkflowModel['on']>[1],
    ) => this.disposables.addFn(this.model.on(type, handler as never));

    on('node:added', ((payload: { node: INodeModel }) => {
      this.transaction(() => {
        const element = this.createElement(payload.node);
        this.graph.addCell(element);
        if (payload.node.parentId) {
          this.graph.getCell(payload.node.parentId)?.embed(element);
        }
      });
    }) as never);

    on('node:removed', ((payload: { nodeId: NodeId }) => {
      this.transaction(() => this.graph.getCell(payload.nodeId)?.remove());
    }) as never);

    on('node:moved', ((payload: { nodeId: NodeId; position: { x: number; y: number } }) => {
      const element = this.element(payload.nodeId);
      if (!element) return;
      const current = element.position();
      if (current.x === payload.position.x && current.y === payload.position.y) return;
      // `deep` so a container carries its children, matching what the user
      // saw while dragging.
      this.transaction(() =>
        element.position(payload.position.x, payload.position.y, { deep: true }),
      );
    }) as never);

    on('node:resized', ((payload: { nodeId: NodeId; size: { width: number; height: number } }) => {
      const element = this.element(payload.nodeId);
      if (!element) return;
      const current = element.size();
      if (current.width === payload.size.width && current.height === payload.size.height) return;
      this.transaction(() => element.resize(payload.size.width, payload.size.height));
    }) as never);

    on('node:parent', ((payload: { nodeId: NodeId; parentId: NodeId | null }) => {
      const element = this.element(payload.nodeId);
      if (!element) return;
      this.transaction(() => {
        const previousParent = element.getParentCell();
        previousParent?.unembed(element);
        if (payload.parentId) this.graph.getCell(payload.parentId)?.embed(element);
      });
    }) as never);

    // A data change can add or remove ports (a node type may vary them with
    // configuration), so the port set is reconciled rather than assumed
    // fixed for the element's lifetime.
    on('node:data', ((payload: { nodeId: NodeId }) => {
      this.syncPorts(payload.nodeId);
      // Renaming a router branch keeps its port *id* — the whole point of
      // stable branch ids — so `syncPorts` sees no change while every link
      // leaving that branch is now labelled with the old name.
      this.transaction(() => {
        for (const edge of this.model.edges()) {
          if (edge.source.nodeId === payload.nodeId) this.applyLabel(edge);
        }
      });
    }) as never);

    on('edge:added', ((payload: { edge: IEdgeModel }) => {
      this.transaction(() => {
        const link = this.createLink(payload.edge);
        if (link) this.graph.addCell(link);
      });
    }) as never);

    on('edge:removed', ((payload: { edgeId: EdgeId }) => {
      this.transaction(() => this.graph.getCell(payload.edgeId)?.remove());
    }) as never);

    on('edge:label', ((payload: { edgeId: EdgeId }) => {
      const edge = this.model.edge(payload.edgeId);
      if (edge) this.transaction(() => this.applyLabel(edge));
    }) as never);

    on('workflow:reset', (() => this.rebuild()) as never);
  }

  /* ================================================================ *
   * Cell construction
   * ================================================================ */

  private createElement(node: INodeModel): dia.Element {
    const element = new HtmlNode({
      id: node.id,
      position: { ...node.position },
      size: { ...node.size },
      ports: { items: this.portItems(node) },
    });
    // Kind drives CSS on the view's root group, so containers and
    // annotations can be styled and z-ordered without a per-type class list.
    element.attr(['root', 'data-kind'], node.kind);
    element.set('nodeType', node.type);
    // Containers sit behind their children; annotations behind everything.
    element.set('z', node.kind === 'container' ? -2 : node.kind === 'annotation' ? -3 : 1);
    return element;
  }

  private portItems(node: INodeModel): dia.Element.Port[] {
    return node.ports.map((port) => this.portItem(node as AbstractNodeModel, port));
  }

  /**
   * A port's initial placement.
   *
   * Seeded from the port's declared side so links look right on the very
   * first frame, before the card has measured itself and reported exact row
   * offsets. Without a seed, every node would flash with all its ports
   * stacked at the origin.
   */
  private portItem(node: AbstractNodeModel, port: IPortDescriptor): dia.Element.Port {
    // `resolvePortSide`, not `sideOf`: the seed has to agree with the side the
    // card will measure to, or every node in vertical flow flashes with its
    // links leaving sideways before the first measurement lands.
    const side = resolvePortSide(port, this.flow);
    const { width, height } = node.size;
    const seed =
      side === 'left'
        ? { x: 0, y: height - 24 }
        : side === 'right'
          ? { x: width, y: height - 24 }
          : side === 'top'
            ? { x: width / 2, y: 0 }
            : { x: width / 2, y: height };

    const portType = this.registry.portType(port.type);

    return {
      id: port.id,
      group: PORT_GROUP,
      position: { args: seed },
      attrs: {
        portDot: {
          // The accent travels as a data attribute rather than a colour: CSS
          // resolves it to the port type's hue, so the dot re-themes and a
          // link's two endpoints visibly agree about what flows along it.
          'data-accent': portType.accent,
        },
        portHit: {
          // Carried through to `validateConnection`, which needs to know
          // which model port a magnet belongs to.
          'data-port-id': port.id,
          'data-port-direction': port.direction,
          'data-port-type': port.type,
        },
      },
    };
  }

  private syncPorts(nodeId: NodeId): void {
    const node = this.model.node(nodeId);
    const element = this.element(nodeId);
    if (!node || !element) return;

    const desired = node.ports.map((port) => port.id);
    const existing = element.getPorts().map((port) => String(port.id));
    if (
      desired.length === existing.length &&
      desired.every((id, index) => existing[index] === id)
    ) {
      return;
    }
    this.transaction(() => element.prop(['ports', 'items'], this.portItems(node)));
  }

  private createLink(edge: IEdgeModel): dia.Link | null {
    if (!this.graph.getCell(edge.source.nodeId) || !this.graph.getCell(edge.target.nodeId)) {
      return null;
    }
    const link = new FlowLink({
      id: edge.id,
      source: { id: edge.source.nodeId, port: edge.source.portId },
      target: { id: edge.target.nodeId, port: edge.target.portId },
    });
    // What flows along a link is decided by the port it lands on, so the
    // link is tinted by its *target* port's type — the same accent the two
    // port dots already carry. Written as data attributes, never as a
    // colour: `canvas.css` resolves the accent (so it re-themes) and the
    // type (so the line also carries a dash signature, which is what keeps
    // the distinction legible without colour vision). Keyed off the port
    // descriptor, so a node type or plugin registering a new port type gets
    // link semantics with no canvas edit.
    const targetPort = this.model
      .node(edge.target.nodeId)
      ?.ports.find((port) => port.id === edge.target.portId);
    if (targetPort) {
      link.attr(['root', 'data-accent'], this.registry.portType(targetPort.type).accent);
      link.attr(['root', 'data-port-type'], targetPort.type);
    }
    this.applyGeometryHints(edge, link);
    this.applyLabel(edge, link);
    return link;
  }

  /**
   * Pins the curve's two tangents to the sides the ports sit on.
   *
   * Re-applied whenever the reading direction changes, because that is what
   * moves the ports: `resolvePortSide` rotates every side 90°, and a tangent
   * left pointing right would draw a link that leaves a bottom port sideways.
   */
  private applyGeometryHints(edge: IEdgeModel, existing?: dia.Link): void {
    const link = existing ?? this.link(edge.id);
    if (!link) return;
    const side = (ref: { nodeId: NodeId; portId: string }): PortSide | undefined => {
      const port = this.model.node(ref.nodeId)?.ports.find((item) => item.id === ref.portId);
      return port ? resolvePortSide(port, this.flow) : undefined;
    };
    link.connector(linkConnector(side(edge.source), side(edge.target)));
  }

  /**
   * Projects an edge's label — authored or derived — onto its link.
   *
   * Derived, never written back: a router branch's name lives on the port
   * descriptor, and inferring the label here keeps `workflow.json` free of a
   * denormalised copy that could go stale the moment a branch is renamed.
   */
  private applyLabel(edge: IEdgeModel, existing?: dia.Link): void {
    const link = existing ?? this.link(edge.id);
    if (!link) return;

    const ports = this.model.node(edge.source.nodeId)?.ports ?? [];
    const sourcePort = ports.find((port) => port.id === edge.source.portId);
    const text = edgeLabelText(edge.label, sourcePort);

    link.labels(
      text ? [buildLabel(text, labelPlacement(this.flow, branchRank(ports, edge.source.portId)))] : [],
    );
  }

  /**
   * Marks a block of graph writes as adapter-driven.
   *
   * Interaction handlers check `isApplying` and ignore graph events raised
   * from inside, which is what prevents a model change from being fed back
   * to the model as if the user had made it.
   */
  private transaction(fn: () => void): void {
    const previous = this.applying;
    this.applying = true;
    try {
      fn();
    } finally {
      this.applying = previous;
    }
  }
}

/**
 * A label with a halo.
 *
 * `labelBody` is an opaque rounded rect sized from the text by `calc()`, drawn
 * beneath it — so the words survive crossing a line, a dot grid or another
 * card's edge instead of dissolving into whatever they land on. That is the
 * free-tier answer to "make labels survive their surroundings"; it needs no
 * collision search, and it is why the label can sit *on* its own line.
 */
function buildLabel(text: string, position: dia.Link.LabelPosition): dia.Link.Label {
  return {
    attrs: {
      labelText: {
        text,
        fill: 'var(--color-text-secondary)',
        fontSize: 11,
        fontFamily: 'var(--font-sans)',
        fontWeight: 500,
        textAnchor: 'middle',
        textVerticalAnchor: 'middle',
        pointerEvents: 'none',
      },
      labelBody: {
        ref: 'labelText',
        fill: 'var(--color-bg-canvas)',
        stroke: 'var(--color-border-subtle)',
        strokeWidth: 1,
        rx: 4,
        ry: 4,
        x: 'calc(x - 6)',
        y: 'calc(y - 3)',
        width: 'calc(w + 12)',
        height: 'calc(h + 6)',
      },
    },
    markup: [
      { tagName: 'rect', selector: 'labelBody' },
      { tagName: 'text', selector: 'labelText' },
    ],
    position,
  };
}
