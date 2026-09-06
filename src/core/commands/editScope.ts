import type { MountContext } from '@core/model/MountContext';
import { CompositeCommand, type ICommand } from './ICommand';

/**
 * Whether a change is allowed to happen at all, and why not when it is not.
 *
 * A narrow interface on purpose: the stack asks one question and renders
 * nothing, so a scope can grow new rules without the stack learning what a
 * mount is. Absent by default — a context with no scope allows everything,
 * which is what every existing construction gets.
 */
export interface IEditScope {
  /** A sentence explaining the refusal, or `null` to allow. */
  refuse(command: ICommand): string | null;
}

/**
 * The rule for editing a mounted **instance** — ticket 42.
 *
 * A mount's own state is `data.overrides`: child node id → field key → value.
 * That expresses "this mount's grader is stricter". It cannot express a moved
 * card, an added node or a deleted edge, and
 * `docs/decisions/mount-overrides.md` says so deliberately — an override
 * narrows, it does not delete, and removing behaviour belongs in the package.
 *
 * A gesture that cannot become an override therefore has three fates, and the
 * two easy ones are both wrong: applying it and losing it on navigation is the
 * silent no-op this codebase has a standing rule against, and applying it to
 * the package is fork-on-configure by accident, hitting every other instance.
 * So it is refused, and the refusal says where the legitimate door is.
 *
 * **It asks the command, not the label.** `ICommand.perInstance` is a
 * declaration a command makes about itself; a list of permitted labels here
 * would be a second place to update whenever a command is added, and labels
 * are display text that changes for presentational reasons.
 *
 * Composites are checked through to their children, because a delete arrives
 * as one — the node, then its edges — and a gate that only read the wrapper
 * would wave the whole thing through.
 */
export class MountEditScope implements IEditScope {
  private mountId: string | null = null;
  /**
   * The parent document this instance's edits are written to, when the caller
   * supplied one. Held here rather than beside it because "which mount is
   * displayed" and "where do its edits go" are one fact with two readers —
   * the stack's gate and `SetMountOverrideCommand` — and two holders that can
   * disagree is a bug waiting for a race.
   */
  private context: MountContext | null = null;

  /** Now displaying the instance mounted at `mountId`. */
  enterInstance(mountId: string, context?: MountContext): void {
    this.mountId = mountId;
    this.context = context ?? null;
  }

  /** Back to a document, where every change is expressible. */
  leaveInstance(): void {
    this.mountId = null;
    this.context = null;
  }

  /** Where an instance edit is written, or `undefined` outside one. */
  get mounts(): MountContext | undefined {
    return this.context ?? undefined;
  }

  refuse(command: ICommand): string | null {
    if (this.mountId === null) return null;
    if (expressibleAsOverride(command)) return null;
    return (
      `“${command.label}” cannot differ per mount, so it is not applied to the ` +
      `${this.mountId} instance. Only a field's value can be overridden here — ` +
      `open the shared definition to change the workflow's shape.`
    );
  }
}

function expressibleAsOverride(command: ICommand): boolean {
  if (command instanceof CompositeCommand) {
    return command.children.every(expressibleAsOverride);
  }
  return command.perInstance === true;
}
