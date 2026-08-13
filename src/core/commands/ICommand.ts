import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { IEditScope } from './editScope';
import type { MountContext } from '@core/model/MountContext';

/** Everything a command is allowed to touch. */
export interface CommandContext {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
  /**
   * Whether a change is permitted at all — see `editScope`. Optional, and
   * absent everywhere except the editor's own controller, so a context built
   * for a test or a script allows everything exactly as before.
   */
  readonly editScope?: IEditScope;
  /**
   * The parent document an instance's edits are written to — ticket 42.
   * Present only while a mount is displayed, which is exactly when
   * `SetMountOverrideCommand` has anywhere to write.
   */
  readonly mounts?: MountContext;
}

/**
 * A reversible change to the document.
 *
 * The stack owns *when* things happen; a command owns *what* happens and
 * how to take it back. Two rules make undo trustworthy:
 *
 *  1. `undo` must restore the exact prior state, including identity — a
 *     re-added node keeps its original id so links and selection survive.
 *  2. A command captures whatever it needs for `undo` during `execute`,
 *     not in its constructor. It may be constructed long before it runs
 *     (or replayed after a redo), and the document will have moved on.
 */
export interface ICommand {
  /** Human-readable, used by the history UI and undo tooltip. */
  readonly label: string;

  execute(ctx: CommandContext): void;
  undo(ctx: CommandContext): void;

  /**
   * Commands sharing a key are candidates for merging, so a drag or a
   * burst of typing collapses into one undo step. Omit to always push a
   * discrete entry.
   */
  readonly coalesceKey?: string;

  /**
   * Whether this change is expressible as a **per-mount override** — ticket 42.
   *
   * A mount's own state is `data.overrides`: child node id → field key →
   * value. A field's value can differ per instance; the workflow's *shape*
   * cannot, and `docs/decisions/mount-overrides.md` says so on purpose. So a
   * command declares this about itself, and `MountEditScope` refuses the ones
   * that do not while an instance is displayed.
   *
   * Declared here rather than inferred from the label, because a label is
   * display text and a list of permitted labels elsewhere would be a second
   * place to update every time a command is added. Absent means "no", which is
   * the safe default: a new command is refused inside an instance until
   * someone has thought about what it would mean there.
   */
  readonly perInstance?: boolean;

  /**
   * Folds `next` into this command, returning the combined command, or
   * `null` to refuse the merge. Only consulted when the coalesce keys
   * match and the two arrived within the stack's merge window.
   */
  mergeWith?(next: ICommand): ICommand | null;
}

/**
 * Convenience base: supplies the label and leaves execute/undo abstract.
 * Commands are free to implement `ICommand` directly instead.
 */
export abstract class Command implements ICommand {
  abstract readonly label: string;
  abstract execute(ctx: CommandContext): void;
  abstract undo(ctx: CommandContext): void;
}

/**
 * Runs several commands as one undo step.
 *
 * Undo walks the children in reverse: deleting a node also deletes its
 * edges, and restoring them in reverse order guarantees the node exists
 * again before an edge tries to attach to it.
 */
export class CompositeCommand implements ICommand {
  readonly children: readonly ICommand[];

  constructor(
    readonly label: string,
    children: readonly ICommand[],
  ) {
    this.children = children;
  }

  /** Drops empty groups and unwraps a group of one. */
  static of(label: string, children: readonly ICommand[]): ICommand | null {
    const kept = children.filter(Boolean);
    if (kept.length === 0) return null;
    if (kept.length === 1) return kept[0] ?? null;
    return new CompositeCommand(label, kept);
  }

  execute(ctx: CommandContext): void {
    ctx.model.transact(() => {
      for (const child of this.children) child.execute(ctx);
    });
  }

  undo(ctx: CommandContext): void {
    ctx.model.transact(() => {
      for (let i = this.children.length - 1; i >= 0; i -= 1) {
        this.children[i]?.undo(ctx);
      }
    });
  }
}
