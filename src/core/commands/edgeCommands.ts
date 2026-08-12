import { EdgeModel } from '@core/model/EdgeModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { INodeDefinition, NodeInit } from '@core/model/contracts/node';
import type { Point } from '@core/kernel/geometry';
import type { PortRef } from '@core/model/contracts/ports';
import type { EdgeId } from '@core/model/contracts/workflow';
import { AddNodeCommand } from './nodeCommands';
import type { CommandContext, ICommand } from './ICommand';

/**
 * Connects two ports.
 *
 * The edge instance is created once and reused on redo so its id survives,
 * which keeps selection and any label attached to it intact.
 *
 * Validation happens *before* the command is constructed — a command's job
 * is to apply a decision, not to make one. See `ConnectionValidator`.
 */
export class ConnectCommand implements ICommand {
  readonly label = 'Connect';
  private edge: EdgeModel | null = null;

  constructor(
    private readonly source: PortRef,
    private readonly target: PortRef,
    private readonly initialLabel: string | null = null,
  ) {}

  get created(): EdgeModel | null {
    return this.edge;
  }

  execute(ctx: CommandContext): void {
    this.edge ??= new EdgeModel({
      source: this.source,
      target: this.target,
      label: this.initialLabel,
    });
    if (!ctx.model.edge(this.edge.id)) ctx.model.addEdge(this.edge);
  }

  undo(ctx: CommandContext): void {
    if (this.edge) ctx.model.removeEdge(this.edge.id);
  }
}

/**
 * Removes one or more edges.
 *
 * Also used to enforce single-input ports: connecting to an occupied input
 * is a composite of "disconnect the incumbent" plus "connect the new one",
 * which undoes as a single step back to the original wiring.
 */
export class DisconnectCommand implements ICommand {
  readonly label: string;
  private removed: readonly EdgeModel[] = [];

  constructor(
    private readonly edgeIds: readonly EdgeId[],
    label?: string,
  ) {
    this.label =
      label ?? (edgeIds.length === 1 ? 'Disconnect' : `Disconnect ${edgeIds.length} links`);
  }

  execute(ctx: CommandContext): void {
    const captured: EdgeModel[] = [];
    ctx.model.transact(() => {
      for (const id of this.edgeIds) {
        const edge = ctx.model.edge(id);
        if (!edge) continue;
        captured.push(edge);
        ctx.model.removeEdge(id);
      }
    });
    this.removed = captured;
  }

  undo(ctx: CommandContext): void {
    ctx.model.transact(() => {
      for (const edge of this.removed) {
        if (!ctx.model.edge(edge.id)) ctx.model.addEdge(edge);
      }
    });
  }
}

/**
 * Inserts a new node inline on an existing edge — ticket 25's "splice
 * insert": dropping a node onto a link that already connects two others
 * replaces that one edge with two, through the new node, as a single undo
 * step.
 *
 * Not built from `AddNodeCommand` + two `ConnectCommand`s composed via
 * `CompositeCommand`, because the two new edges need the *real* id of the
 * node `AddNodeCommand` creates — which does not exist until that command
 * has actually executed. `CompositeCommand`'s children are fixed at
 * construction time, before anything has run, so this command builds its
 * own edges lazily inside `execute`, the same way `ConnectCommand` and
 * `DisconnectCommand` capture their own undo state rather than relying on
 * being composed from smaller pieces.
 */
export class SpliceInsertCommand implements ICommand {
  readonly label: string;
  private readonly add: AddNodeCommand;
  private removedEdge: EdgeModel | null = null;
  private inEdge: EdgeModel | null = null;
  private outEdge: EdgeModel | null = null;

  constructor(
    private readonly edgeId: EdgeId,
    definition: INodeDefinition,
    init: NodeInit,
  ) {
    this.add = new AddNodeCommand(definition, init);
    this.label = `Insert ${definition.label}`;
  }

  /** The created node, available after the first execute — for selection. */
  get created(): AbstractNodeModel | null {
    return this.add.created;
  }

  execute(ctx: CommandContext): void {
    ctx.model.transact(() => {
      const existing = ctx.model.edge(this.edgeId);
      if (existing) {
        this.removedEdge ??= existing;
        ctx.model.removeEdge(this.edgeId);
      }

      this.add.execute(ctx);
      const node = this.add.created;
      if (!node || !this.removedEdge) return;

      const inPort = node.primaryInput;
      const outPort = node.primaryOutput;
      if (inPort) {
        this.inEdge ??= new EdgeModel({
          source: this.removedEdge.source,
          target: { nodeId: node.id, portId: inPort.id },
        });
        if (!ctx.model.edge(this.inEdge.id)) ctx.model.addEdge(this.inEdge);
      }
      if (outPort) {
        this.outEdge ??= new EdgeModel({
          source: { nodeId: node.id, portId: outPort.id },
          target: this.removedEdge.target,
        });
        if (!ctx.model.edge(this.outEdge.id)) ctx.model.addEdge(this.outEdge);
      }
    });
  }

  undo(ctx: CommandContext): void {
    ctx.model.transact(() => {
      if (this.outEdge) ctx.model.removeEdge(this.outEdge.id);
      if (this.inEdge) ctx.model.removeEdge(this.inEdge.id);
      this.add.undo(ctx);
      if (this.removedEdge && !ctx.model.edge(this.removedEdge.id)) {
        ctx.model.addEdge(this.removedEdge);
      }
    });
  }
}

export class SetEdgeLabelCommand implements ICommand {
  readonly label = 'Label link';
  readonly coalesceKey: string;
  private previous: string | null | undefined;

  constructor(
    private readonly edgeId: EdgeId,
    private value: string | null,
  ) {
    this.coalesceKey = `edge-label:${edgeId}`;
  }

  execute(ctx: CommandContext): void {
    const edge = ctx.model.edge(this.edgeId);
    if (!edge) return;
    if (this.previous === undefined) this.previous = edge.label;
    ctx.model.setEdgeLabel(this.edgeId, this.value);
  }

  undo(ctx: CommandContext): void {
    if (this.previous !== undefined) ctx.model.setEdgeLabel(this.edgeId, this.previous);
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof SetEdgeLabelCommand) || next.edgeId !== this.edgeId) return null;
    this.value = next.value;
    return this;
  }
}

/**
 * Moves, adds or removes the waypoints a link's run must pass through.
 *
 * One command for all three gestures, because to the document they are the
 * same edit: the whole list is replaced. `linkTools.Vertices` adds a point on
 * click, drags it, and removes it on double-click, and each of those arrives
 * here as "the list is now this".
 *
 * Coalesced per edge, so a drag — which emits a change per frame — collapses
 * into one undo step, exactly as a node drag does. Adding a point and then
 * dragging it inside the merge window also collapses, which is right: the user
 * performed one placement.
 */
export class SetEdgeVerticesCommand implements ICommand {
  readonly label = 'Move link point';
  readonly coalesceKey: string;
  private previous: readonly Point[] | undefined;

  constructor(
    private readonly edgeId: EdgeId,
    private value: readonly Point[],
  ) {
    this.coalesceKey = `edge-vertices:${edgeId}`;
  }

  execute(ctx: CommandContext): void {
    const edge = ctx.model.edge(this.edgeId);
    if (!edge) return;
    // Captured on the *first* execute only: a redo must restore the state the
    // gesture started from, not the one the undo just put back.
    this.previous ??= edge.vertices;
    ctx.model.setEdgeVertices(this.edgeId, this.value);
  }

  undo(ctx: CommandContext): void {
    if (this.previous !== undefined) ctx.model.setEdgeVertices(this.edgeId, this.previous);
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof SetEdgeVerticesCommand) || next.edgeId !== this.edgeId) return null;
    this.value = next.value;
    return this;
  }
}

/* ------------------------------------------------------------------ *
 * Document-level
 * ------------------------------------------------------------------ */

export class RenameWorkflowCommand implements ICommand {
  readonly label = 'Rename workflow';
  readonly coalesceKey = 'workflow:name';
  private previous: string | null = null;

  constructor(private name: string) {}

  execute(ctx: CommandContext): void {
    this.previous ??= ctx.model.name;
    ctx.model.setName(this.name);
  }

  undo(ctx: CommandContext): void {
    if (this.previous != null) ctx.model.setName(this.previous);
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof RenameWorkflowCommand)) return null;
    this.name = next.name;
    return this;
  }
}
