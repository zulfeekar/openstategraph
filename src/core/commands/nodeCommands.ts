import type { Point, Size } from '@core/kernel/geometry';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { EdgeModel } from '@core/model/EdgeModel';
import type { FieldValue, NodeData } from '@core/model/contracts/fields';
import type { INodeDefinition, NodeId, NodeInit } from '@core/model/contracts/node';
import type { CommandContext, ICommand } from './ICommand';

/* ================================================================== *
 * Add
 * ================================================================== */

/**
 * Adds one node.
 *
 * The instance is built once and reused across redo, so the node keeps its
 * id and any edits it accumulated before being undone away. Re-creating it
 * would mint a fresh id and orphan every link pointing at the old one.
 */
export class AddNodeCommand implements ICommand {
  readonly label: string;
  private node: AbstractNodeModel | null = null;

  constructor(
    private readonly definition: INodeDefinition,
    private readonly init: NodeInit,
  ) {
    this.label = `Add ${definition.label}`;
  }

  /** The created node, available after the first execute (for selection). */
  get created(): AbstractNodeModel | null {
    return this.node;
  }

  execute(ctx: CommandContext): void {
    if (!this.node) {
      this.node = this.definition.create(this.init) as AbstractNodeModel;
    }
    ctx.model.addNode(this.node);
  }

  undo(ctx: CommandContext): void {
    if (this.node) ctx.model.removeNode(this.node.id);
  }
}

/* ================================================================== *
 * Remove
 * ================================================================== */

interface RemovalSnapshot {
  readonly nodes: readonly AbstractNodeModel[];
  readonly edges: readonly EdgeModel[];
  /** Children promoted to the root because their container went away. */
  readonly orphaned: readonly { nodeId: NodeId; parentId: NodeId }[];
}

/**
 * Removes nodes and everything that structurally depended on them.
 *
 * The snapshot is taken at execute time rather than construction, because
 * the same command object is replayed on redo and the graph will have
 * changed in between.
 */
export class RemoveNodesCommand implements ICommand {
  readonly label: string;
  private snapshot: RemovalSnapshot | null = null;

  constructor(
    private readonly nodeIds: readonly NodeId[],
    label?: string,
  ) {
    this.label = label ?? (nodeIds.length === 1 ? 'Delete node' : `Delete ${nodeIds.length} nodes`);
  }

  execute(ctx: CommandContext): void {
    const { model } = ctx;
    const targets = this.nodeIds
      .map((id) => model.node(id))
      .filter((node): node is AbstractNodeModel => node != null);

    // Deduplicate edges: one edge between two doomed nodes would
    // otherwise be captured — and restored — twice.
    const edges = new Map<string, EdgeModel>();
    const orphaned: { nodeId: NodeId; parentId: NodeId }[] = [];
    const doomed = new Set(targets.map((node) => node.id));

    for (const node of targets) {
      for (const edge of model.edgesOf(node.id)) edges.set(edge.id, edge);
      for (const child of model.childrenOf(node.id)) {
        // Children of a deleted container survive at the root; record the
        // link so undo can put them back inside it.
        if (!doomed.has(child.id)) orphaned.push({ nodeId: child.id, parentId: node.id });
      }
    }

    this.snapshot = { nodes: targets, edges: [...edges.values()], orphaned };

    model.transact(() => {
      for (const node of targets) model.removeNode(node.id);
    });
  }

  undo(ctx: CommandContext): void {
    const snapshot = this.snapshot;
    if (!snapshot) return;
    const { model } = ctx;

    model.transact(() => {
      // Nodes first: an edge cannot be attached to a node that is not
      // back yet, and a child's parent link is just a map entry.
      for (const node of snapshot.nodes) {
        if (!model.hasNode(node.id)) model.addNode(node);
      }
      for (const { nodeId, parentId } of snapshot.orphaned) {
        model.setNodeParent(nodeId, parentId);
      }
      for (const edge of snapshot.edges) {
        if (!model.edge(edge.id)) model.addEdge(edge);
      }
    });
  }
}

/* ================================================================== *
 * Move
 * ================================================================== */

interface MoveEntry {
  readonly nodeId: NodeId;
  readonly from: Point;
  to: Point;
}

/**
 * Moves one or more nodes.
 *
 * Coalesces across a drag: the pointer emits a move per frame, and merging
 * them keeps the original `from` while advancing `to`, so one undo returns
 * the node to where the drag started.
 */
export class MoveNodesCommand implements ICommand {
  readonly label: string;
  readonly coalesceKey: string;

  constructor(private readonly entries: readonly MoveEntry[]) {
    this.label = entries.length === 1 ? 'Move node' : `Move ${entries.length} nodes`;
    // Keyed on the participating nodes, so dragging A then B does not
    // merge into a single confusing entry.
    this.coalesceKey = `move:${entries
      .map((e) => e.nodeId)
      .sort()
      .join(',')}`;
  }

  static from(
    nodes: readonly { id: NodeId; position: Point }[],
    to: (node: { id: NodeId; position: Point }) => Point,
  ): MoveNodesCommand {
    return new MoveNodesCommand(
      nodes.map((node) => ({ nodeId: node.id, from: { ...node.position }, to: to(node) })),
    );
  }

  execute(ctx: CommandContext): void {
    ctx.model.transact(() => {
      for (const entry of this.entries) ctx.model.moveNode(entry.nodeId, entry.to);
    });
  }

  undo(ctx: CommandContext): void {
    ctx.model.transact(() => {
      for (const entry of this.entries) ctx.model.moveNode(entry.nodeId, entry.from);
    });
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof MoveNodesCommand)) return null;
    const byId = new Map(this.entries.map((entry) => [entry.nodeId, entry]));
    // Refuse if the sets differ — merging would silently drop a node's move.
    for (const entry of next.entries) {
      const existing = byId.get(entry.nodeId);
      if (!existing) return null;
    }
    for (const entry of next.entries) {
      const existing = byId.get(entry.nodeId);
      if (existing) existing.to = entry.to;
    }
    return this;
  }
}

/* ================================================================== *
 * Resize
 * ================================================================== */

export class ResizeNodeCommand implements ICommand {
  readonly label = 'Resize node';
  readonly coalesceKey: string;
  private from: Size | null = null;

  constructor(
    private readonly nodeId: NodeId,
    private to: Size,
  ) {
    this.coalesceKey = `resize:${nodeId}`;
  }

  execute(ctx: CommandContext): void {
    const node = ctx.model.node(this.nodeId);
    if (!node) return;
    this.from ??= { ...node.size };
    ctx.model.resizeNode(this.nodeId, this.to);
  }

  undo(ctx: CommandContext): void {
    if (this.from) ctx.model.resizeNode(this.nodeId, this.from);
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof ResizeNodeCommand) || next.nodeId !== this.nodeId) return null;
    this.to = next.to;
    return this;
  }
}

/* ================================================================== *
 * Field edits
 * ================================================================== */

/**
 * Sets a single configuration field.
 *
 * Coalesced per node+field so typing a prompt is one undo step, not one
 * per character — while switching to a different field starts a new step.
 */
export class SetFieldCommand implements ICommand {
  readonly label: string;
  readonly coalesceKey: string;
  private previous: FieldValue | undefined;

  constructor(
    private readonly nodeId: NodeId,
    private readonly key: string,
    private value: FieldValue,
    label?: string,
  ) {
    this.label = label ?? 'Edit field';
    this.coalesceKey = `field:${nodeId}:${key}`;
  }

  execute(ctx: CommandContext): void {
    const node = ctx.model.node(this.nodeId);
    if (!node) return;
    // Capture only on the first run; a redo must not treat the undone
    // value as the thing to restore.
    if (this.previous === undefined) this.previous = node.data[this.key] ?? null;
    ctx.model.setNodeData(this.nodeId, this.key, this.value);
  }

  undo(ctx: CommandContext): void {
    if (this.previous !== undefined) {
      ctx.model.setNodeData(this.nodeId, this.key, this.previous);
    }
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof SetFieldCommand)) return null;
    if (next.nodeId !== this.nodeId || next.key !== this.key) return null;
    this.value = next.value;
    return this;
  }
}

/** Sets several fields at once — used by file loads and inspector presets. */
export class SetFieldsCommand implements ICommand {
  readonly label: string;
  private previous: Partial<NodeData> | null = null;

  constructor(
    private readonly nodeId: NodeId,
    private readonly patch: Partial<NodeData>,
    label = 'Edit fields',
  ) {
    this.label = label;
  }

  execute(ctx: CommandContext): void {
    const node = ctx.model.node(this.nodeId);
    if (!node) return;
    if (!this.previous) {
      const snapshot: Partial<NodeData> = {};
      for (const key of Object.keys(this.patch)) snapshot[key] = node.data[key] ?? null;
      this.previous = snapshot;
    }
    ctx.model.setNodeDataBulk(this.nodeId, this.patch);
  }

  undo(ctx: CommandContext): void {
    if (this.previous) ctx.model.setNodeDataBulk(this.nodeId, this.previous);
  }
}

/* ================================================================== *
 * Title
 * ================================================================== */

export class SetNodeTitleCommand implements ICommand {
  readonly label = 'Rename node';
  readonly coalesceKey: string;
  private previous: string | null = null;

  constructor(
    private readonly nodeId: NodeId,
    private title: string,
  ) {
    this.coalesceKey = `title:${nodeId}`;
  }

  execute(ctx: CommandContext): void {
    const node = ctx.model.node(this.nodeId);
    if (!node) return;
    // Store the *raw* prior title so undo restores "inherits type label"
    // rather than pinning the type label as a custom one.
    this.previous ??= node.hasCustomTitle ? node.title : '';
    ctx.model.setNodeTitle(this.nodeId, this.title);
  }

  undo(ctx: CommandContext): void {
    if (this.previous != null) ctx.model.setNodeTitle(this.nodeId, this.previous);
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof SetNodeTitleCommand) || next.nodeId !== this.nodeId) return null;
    this.title = next.title;
    return this;
  }
}

/* ================================================================== *
 * Embedding
 * ================================================================== */

/** Moves a node into or out of a container. */
export class SetParentCommand implements ICommand {
  readonly label: string;
  private previous: NodeId | null | undefined;

  constructor(
    private readonly nodeId: NodeId,
    private readonly parentId: NodeId | null,
  ) {
    this.label = parentId ? 'Group node' : 'Ungroup node';
  }

  execute(ctx: CommandContext): void {
    const node = ctx.model.node(this.nodeId);
    if (!node) return;
    if (this.previous === undefined) this.previous = node.parentId;
    ctx.model.setNodeParent(this.nodeId, this.parentId);
  }

  undo(ctx: CommandContext): void {
    if (this.previous !== undefined) ctx.model.setNodeParent(this.nodeId, this.previous);
  }
}
