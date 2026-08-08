import type { Point } from '@core/kernel/geometry';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { NodeId, SerializedNode } from '@core/model/contracts/node';
import type { SerializedEdge } from '@core/model/contracts/workflow';
import type { ICommand } from '@core/commands/ICommand';
import { AddNodeCommand } from '@core/commands/nodeCommands';
import { ConnectCommand } from '@core/commands/edgeCommands';

/** A self-contained excerpt of a graph. */
export interface ClipboardFragment {
  readonly nodes: readonly SerializedNode[];
  readonly edges: readonly SerializedEdge[];
  /** Top-left of the copied bounding box, so paste can offset relative to it. */
  readonly origin: Point;
}

const CLIPBOARD_MIME = 'application/x-dyflow-fragment';

/**
 * Copy / cut / paste of graph fragments.
 *
 * Two design points:
 *
 * **Internal edges only.** A copied selection keeps links whose *both*
 * endpoints were copied. A dangling half-link would either paste as an
 * invisible stub or silently re-attach to whatever node happened to share
 * an id — both worse than dropping it.
 *
 * **Ids are re-minted on paste.** Nodes get fresh ids and edges are
 * remapped through an old→new table, so pasting into the same document
 * cannot collide, and pasting twice yields two independent copies.
 */
export class ClipboardService {
  private fragment: ClipboardFragment | null = null;

  constructor(
    private readonly model: WorkflowModel,
    private readonly registry: ModelRegistry,
  ) {}

  get hasContent(): boolean {
    return this.fragment != null && this.fragment.nodes.length > 0;
  }

  /** Extracts a fragment without mutating the document. */
  copy(nodeIds: readonly NodeId[]): ClipboardFragment | null {
    const included = new Set(nodeIds);
    const nodes = nodeIds
      .map((id) => this.model.node(id))
      .filter((node) => node != null)
      .map((node) => node.toJSON());

    if (nodes.length === 0) return null;

    const edges = this.model
      .edges()
      .filter((edge) => included.has(edge.source.nodeId) && included.has(edge.target.nodeId))
      .map((edge) => edge.toJSON());

    const origin = {
      x: Math.min(...nodes.map((n) => n.position.x)),
      y: Math.min(...nodes.map((n) => n.position.y)),
    };

    // Containment is only meaningful if the container came along too.
    const normalised = nodes.map((node) =>
      node.parentId && included.has(node.parentId) ? node : { ...node, parentId: null },
    );

    this.fragment = { nodes: normalised, edges, origin };
    this.writeSystemClipboard(this.fragment);
    return this.fragment;
  }

  /**
   * Builds the commands that materialise the fragment at `at`.
   *
   * Returns a command rather than applying one, so the caller decides how
   * it lands in history — paste is one undo step, and a paste that is part
   * of a larger gesture can be composed into it.
   */
  pasteCommand(
    at: Point,
    fragment = this.fragment,
  ): { command: ICommand | null; nodeIds: NodeId[] } {
    if (!fragment || fragment.nodes.length === 0) return { command: null, nodeIds: [] };

    const dx = at.x - fragment.origin.x;
    const dy = at.y - fragment.origin.y;

    const idMap = new Map<NodeId, NodeId>();
    const addCommands: AddNodeCommand[] = [];
    /** Types already queued in this paste, so caps count them too. */
    const queued = new Map<string, number>();

    for (const serialized of fragment.nodes) {
      const definition = this.registry.nodeTypes.get(serialized.type);
      if (!definition) continue;
      // Respect per-type instance caps: pasting must not be a way around
      // "only one output node".
      if (definition.maxInstances != null) {
        const existing = this.model.countOfType(definition.id) + (queued.get(definition.id) ?? 0);
        if (existing >= definition.maxInstances) continue;
      }
      queued.set(definition.id, (queued.get(definition.id) ?? 0) + 1);
      const command = new AddNodeCommand(definition, {
        position: { x: serialized.position.x + dx, y: serialized.position.y + dy },
        size: serialized.size,
        data: serialized.data,
        ...(serialized.title ? { title: serialized.title } : {}),
      });
      addCommands.push(command);
      // The new id is not known until execute; record the slot and fill it
      // in from `created` once the command has run.
      idMap.set(serialized.id, '');
    }

    if (addCommands.length === 0) return { command: null, nodeIds: [] };

    const pastedIds: NodeId[] = [];
    const originals = fragment.nodes.filter((n) => idMap.has(n.id));

    // A tiny bespoke command stitches the two phases together: the node
    // ids only exist after the adds run, and the edges and parent links
    // need them. Wrapping it keeps paste a single undo entry.
    const command: ICommand = {
      label: `Paste ${addCommands.length} node${addCommands.length === 1 ? '' : 's'}`,
      execute: (ctx) => {
        ctx.model.transact(() => {
          for (const add of addCommands) add.execute(ctx);

          pastedIds.length = 0;
          originals.forEach((serialized, index) => {
            const created = addCommands[index]?.created;
            if (created) {
              idMap.set(serialized.id, created.id);
              pastedIds.push(created.id);
            }
          });

          for (const serialized of originals) {
            if (!serialized.parentId) continue;
            const child = idMap.get(serialized.id);
            const parent = idMap.get(serialized.parentId);
            if (child && parent) ctx.model.setNodeParent(child, parent);
          }

          for (const edge of fragment.edges) {
            const source = idMap.get(edge.source.nodeId);
            const target = idMap.get(edge.target.nodeId);
            if (!source || !target) continue;
            new ConnectCommand(
              { nodeId: source, portId: edge.source.portId },
              { nodeId: target, portId: edge.target.portId },
              edge.label ?? null,
            ).execute(ctx);
          }
        });
      },
      undo: (ctx) => {
        ctx.model.transact(() => {
          // Removing the nodes takes their edges with them, so the adds
          // are the only thing that needs unwinding.
          for (let i = addCommands.length - 1; i >= 0; i -= 1) addCommands[i]?.undo(ctx);
        });
      },
    };

    return { command, nodeIds: pastedIds };
  }

  clear(): void {
    this.fragment = null;
  }

  /**
   * Mirrors the fragment onto the system clipboard as JSON.
   *
   * Best-effort: it enables paste into an editor or another tab, but the
   * in-memory fragment stays authoritative because clipboard reads need a
   * permission prompt we don't want in the middle of a Cmd-V.
   */
  private writeSystemClipboard(fragment: ClipboardFragment): void {
    try {
      const payload = JSON.stringify({ [CLIPBOARD_MIME]: fragment }, null, 2);
      void navigator.clipboard?.writeText(payload).catch(() => undefined);
    } catch {
      // No clipboard access (insecure context, denied permission) — the
      // internal fragment still works.
    }
  }

  /** Parses a fragment pasted from outside the app, if it is one of ours. */
  static parseExternal(text: string): ClipboardFragment | null {
    try {
      const parsed = JSON.parse(text) as Record<string, unknown>;
      const fragment = parsed[CLIPBOARD_MIME];
      if (!fragment || typeof fragment !== 'object') return null;
      const candidate = fragment as ClipboardFragment;
      if (!Array.isArray(candidate.nodes)) return null;
      return candidate;
    } catch {
      return null;
    }
  }
}
