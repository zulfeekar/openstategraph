import { EdgeModel } from '@core/model/EdgeModel';
import type { PortRef } from '@core/model/contracts/ports';
import type { EdgeId } from '@core/model/contracts/workflow';
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
    this.label = label ?? (edgeIds.length === 1 ? 'Disconnect' : `Disconnect ${edgeIds.length} links`);
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
