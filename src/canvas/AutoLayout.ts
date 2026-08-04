import type { dia } from '@joint/core';
import { DirectedGraph } from '@joint/layout-directed-graph';
import type { Point } from '@core/kernel/geometry';
import type { WorkflowController } from '@controller/WorkflowController';

export interface AutoLayoutOptions {
  /** `LR` reads left-to-right, matching how these graphs are drawn. */
  readonly rankDir?: 'LR' | 'TB' | 'RL' | 'BT';
  /** Gap between ranks (columns in `LR`). */
  readonly rankSep?: number;
  /** Gap between nodes within a rank. */
  readonly nodeSep?: number;
}

/**
 * Dagre-based automatic layout.
 *
 * `@joint/layout-directed-graph` writes positions straight onto the graph,
 * which would bypass the model and desync the two. So the layout is run,
 * the resulting positions are *read back*, the graph is rewound, and the
 * positions are committed through the controller as one undoable move. The
 * adapter then re-applies them, arriving at the same picture with the
 * document as the source of truth and one Cmd-Z to reverse it.
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
    const laid = this.graph
      .getElements()
      .filter((element) => this.controller.model.node(String(element.id))?.kind === 'standard');

    if (laid.length < 2) return;

    const before = new Map<string, Point>(
      this.graph.getElements().map((element) => [String(element.id), { ...element.position() }]),
    );

    DirectedGraph.layout(this.graph, {
      rankDir: options.rankDir ?? 'LR',
      rankSep: options.rankSep ?? 96,
      nodeSep: options.nodeSep ?? 48,
      edgeSep: 24,
      marginX: 40,
      marginY: 40,
      // Vertices would be written onto links, which the model has no place
      // to store and the smooth connector doesn't need.
      setVertices: false,
      setLabels: false,
    });

    const moves: { nodeId: string; position: Point }[] = [];
    for (const element of laid) {
      const nodeId = String(element.id);
      const after = element.position();
      const original = before.get(nodeId);
      if (!original) continue;
      if (Math.round(after.x) === original.x && Math.round(after.y) === original.y) continue;
      moves.push({ nodeId, position: { x: Math.round(after.x), y: Math.round(after.y) } });
    }

    // Rewind everything dagre touched — including nodes it moved that we are
    // not committing — so the graph is a faithful projection again before the
    // command applies the new positions.
    for (const element of this.graph.getElements()) {
      const original = before.get(String(element.id));
      if (original) element.position(original.x, original.y);
    }

    if (moves.length === 0) return;

    this.controller.history.transact('Auto layout', () => {
      this.controller.nodes.move(moves, false);
    });
  }
}
