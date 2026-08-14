import type { FieldValue } from '@core/model/contracts/fields';
import type { NodeId } from '@core/model/contracts/node';
import type { CommandContext, ICommand } from './ICommand';

/** Distinguishes "there was no override" from "the override was undefined". */
const ABSENT = Symbol('no override');

/**
 * `instance.field = x` — ticket 42, tranche 4.
 *
 * A mount node is an instance of a workflow package, and its own state is
 * `data.overrides`. So editing a field while `concierge/wf-music` is displayed
 * writes **`wf-music`'s overrides, in `concierge`** — never the
 * `chinook-assistant` package, which stays the single source of truth every
 * other mount of it still shares.
 *
 * Two documents move, and both are the point:
 *
 * - the **parent**, through `ctx.mounts`, because that is what a later Save
 *   persists and what the compiler will merge on the next run;
 * - the **model**, because the canvas is a one-way projection and a card that
 *   did not change would say the edit had not happened.
 *
 * `undo` takes back both, and the case worth naming is the *absence* one:
 * restoring "there was no override" removes the key rather than writing
 * `null`. A `null` override is not the package default — it is an override
 * whose value is null, and `apply_mount_overrides` would apply it over the
 * package's real value.
 *
 * Coalesced per node and field, exactly like `SetFieldCommand`, so typing a
 * prompt is one undo step rather than one per keystroke.
 */
export class SetMountOverrideCommand implements ICommand {
  readonly label: string;
  readonly coalesceKey: string;
  /** The one shape a mount can carry — see `editScope`. */
  readonly perInstance = true;

  private previousOverride: unknown = ABSENT;
  private previousField: FieldValue | undefined;

  constructor(
    private readonly nodeId: NodeId,
    private readonly key: string,
    private readonly value: FieldValue,
    label?: string,
  ) {
    this.label = label ?? 'Edit field for this mount';
    this.coalesceKey = `override:${nodeId}:${key}`;
  }

  execute(ctx: CommandContext): void {
    const mounts = ctx.mounts;
    // Constructed by a caller that believed an instance was open and was
    // wrong. Writing to the model alone would be an edit with nowhere to be
    // saved — the silent no-op, arriving through a different door.
    if (!mounts) return;
    const node = ctx.model.node(this.nodeId);
    if (!node) return;

    // Captured on the first run only; a redo must not treat the undone state
    // as the thing to restore (`ICommand`'s second rule).
    if (this.previousOverride === ABSENT) {
      const existing = mounts.readOverride(this.nodeId, this.key);
      this.previousOverride = existing === undefined ? ABSENT : existing;
      this.previousField = node.data[this.key] ?? null;
    }

    mounts.writeOverride(this.nodeId, this.key, this.value);
    ctx.model.setNodeData(this.nodeId, this.key, this.value);
  }

  undo(ctx: CommandContext): void {
    const mounts = ctx.mounts;
    if (!mounts) return;
    if (this.previousOverride === ABSENT) {
      mounts.clearOverride(this.nodeId, this.key);
    } else {
      mounts.writeOverride(this.nodeId, this.key, this.previousOverride);
    }
    if (this.previousField !== undefined) {
      ctx.model.setNodeData(this.nodeId, this.key, this.previousField);
    }
  }

  mergeWith(next: ICommand): ICommand | null {
    if (!(next instanceof SetMountOverrideCommand)) return null;
    if (next.coalesceKey !== this.coalesceKey) return null;
    // The merged command keeps *this* one's captured prior state and the
    // later value, so one undo returns to before the burst began.
    const merged = new SetMountOverrideCommand(this.nodeId, this.key, next.value, this.label);
    merged.previousOverride = this.previousOverride;
    merged.previousField = this.previousField;
    return merged;
  }
}

/**
 * Back to the package default — the other half of tranche 5's affordance.
 *
 * Deliberately not `SetMountOverrideCommand` carrying the inherited value:
 * that would *write an override that happens to equal the default*, which
 * reads identically on screen and is a completely different document. The
 * mount would keep counting it, a later change to the package would no longer
 * reach this instance, and "revert" would have quietly pinned the value.
 */
export class ClearMountOverrideCommand implements ICommand {
  readonly label = 'Use the package default';
  readonly perInstance = true;

  private previousOverride: unknown = ABSENT;
  private previousField: FieldValue | undefined;

  constructor(
    private readonly nodeId: NodeId,
    private readonly key: string,
  ) {}

  execute(ctx: CommandContext): void {
    const mounts = ctx.mounts;
    if (!mounts) return;
    const node = ctx.model.node(this.nodeId);
    if (!node) return;

    if (this.previousOverride === ABSENT) {
      const existing = mounts.readOverride(this.nodeId, this.key);
      this.previousOverride = existing === undefined ? ABSENT : existing;
      this.previousField = node.data[this.key] ?? null;
    }

    mounts.clearOverride(this.nodeId, this.key);
    const inherited = mounts.inheritedValue(this.nodeId, this.key);
    ctx.model.setNodeData(this.nodeId, this.key, (inherited ?? null) as FieldValue);
  }

  undo(ctx: CommandContext): void {
    const mounts = ctx.mounts;
    if (!mounts) return;
    if (this.previousOverride !== ABSENT) {
      mounts.writeOverride(this.nodeId, this.key, this.previousOverride);
    }
    if (this.previousField !== undefined) {
      ctx.model.setNodeData(this.nodeId, this.key, this.previousField);
    }
  }
}
