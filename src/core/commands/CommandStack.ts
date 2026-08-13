import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import type { CommandContext, ICommand } from './ICommand';
import { CompositeCommand } from './ICommand';

interface CommandStackEvents extends Record<string, unknown> {
  changed: { canUndo: boolean; canRedo: boolean };
  executed: { command: ICommand };
  undone: { command: ICommand };
  redone: { command: ICommand };
  /**
   * A change the current edit scope would not allow — see `editScope`. Emitted
   * rather than thrown: a refusal is a thing to *say*, and the view is what
   * says it. Nothing ran and nothing was pushed, so undo reaches past it.
   */
  refused: { command: ICommand; reason: string };
}

export interface CommandStackOptions {
  /** Entries retained before the oldest is dropped. */
  limit?: number;
  /** Window within which two same-key commands may merge, in ms. */
  mergeWindowMs?: number;
  /** Injected clock, so merge behaviour is testable without real time. */
  now?: () => number;
}

/**
 * Undo/redo.
 *
 * Two behaviours are worth calling out, because they are what separate a
 * usable history from a technically-correct one:
 *
 * **Coalescing.** Dragging a node emits a move per pointer frame and
 * typing emits a change per keystroke. Merging same-key commands inside a
 * short window means one Cmd-Z undoes "the drag" or "the word", which is
 * what a user means by one step.
 *
 * **Transaction capture.** `transact` groups whatever a callback does into
 * a single composite entry, so a paste of nine nodes is one undo — while
 * still letting the individual commands stay small and reusable.
 */
export class CommandStack {
  private readonly undoStack: ICommand[] = [];
  private readonly redoStack: ICommand[] = [];
  private readonly bus = new EventBus<CommandStackEvents>();

  private readonly limit: number;
  private readonly mergeWindowMs: number;
  private readonly now: () => number;

  private lastPushAt = 0;
  /** Non-null while capturing a transaction. */
  private capture: ICommand[] | null = null;
  /** Suppresses capture while the stack itself is replaying a command. */
  private replaying = false;

  constructor(
    private readonly ctx: CommandContext,
    { limit = 200, mergeWindowMs = 600, now = () => Date.now() }: CommandStackOptions = {},
  ) {
    this.limit = limit;
    this.mergeWindowMs = mergeWindowMs;
    this.now = now;
  }

  get canUndo(): boolean {
    return this.undoStack.length > 0;
  }

  get canRedo(): boolean {
    return this.redoStack.length > 0;
  }

  /** Label of the next undo, for the tooltip: "Undo Move node". */
  get undoLabel(): string | null {
    return this.undoStack[this.undoStack.length - 1]?.label ?? null;
  }

  get redoLabel(): string | null {
    return this.redoStack[this.redoStack.length - 1]?.label ?? null;
  }

  /** Number of entries, exposed for the history panel and for tests. */
  get depth(): number {
    return this.undoStack.length;
  }

  /**
   * Runs a command and records it.
   *
   * A command that turns out to be a no-op (nothing to delete, an
   * unchanged value) can return without touching the model; it still
   * records, so callers may pass `null` to opt out entirely instead.
   */
  /**
   * What a command will be handed. Exposed so a collaborator can ask *which*
   * command to construct — `NodeEditor` builds a mount override instead of a
   * field edit while an instance is displayed — without holding a second copy
   * of the context that could disagree with this one.
   */
  get context(): CommandContext {
    return this.ctx;
  }

  execute(command: ICommand | null): void {
    if (!command) return;

    // Asked before anything runs, so a refused change leaves no trace: the
    // model is untouched, nothing is pushed, and undo reaches past it to
    // whatever the user really did last.
    const refusal = this.ctx.editScope?.refuse(command) ?? null;
    if (refusal !== null) {
      this.bus.emit('refused', { command, reason: refusal });
      return;
    }

    command.execute(this.ctx);

    if (this.capture && !this.replaying) {
      // Inside a transaction: collect rather than push, so the whole
      // group lands as one entry when the transaction closes.
      this.capture.push(command);
      return;
    }

    this.push(command);
    this.bus.emit('executed', { command });
    this.notify();
  }

  /**
   * Groups everything executed inside `fn` into one undo entry.
   *
   * Nested transactions flatten into the outermost one — a controller
   * method that transacts can freely call another that also transacts
   * without producing an unpredictable history depth.
   */
  transact<T>(label: string, fn: () => T): T {
    if (this.capture) return fn();

    const captured: ICommand[] = [];
    this.capture = captured;
    let result: T;
    try {
      result = this.ctx.model.transact(fn);
    } finally {
      this.capture = null;
    }

    const composite = CompositeCommand.of(label, captured);
    if (composite) {
      this.push(composite);
      this.bus.emit('executed', { command: composite });
      this.notify();
    }
    return result;
  }

  undo(): boolean {
    const command = this.undoStack.pop();
    if (!command) return false;
    this.replaying = true;
    try {
      command.undo(this.ctx);
    } finally {
      this.replaying = false;
    }
    this.redoStack.push(command);
    // Break the merge window so the next edit cannot fold into a command
    // that is no longer on top of the stack.
    this.lastPushAt = 0;
    this.bus.emit('undone', { command });
    this.notify();
    return true;
  }

  redo(): boolean {
    const command = this.redoStack.pop();
    if (!command) return false;
    this.replaying = true;
    try {
      command.execute(this.ctx);
    } finally {
      this.replaying = false;
    }
    this.undoStack.push(command);
    this.lastPushAt = 0;
    this.bus.emit('redone', { command });
    this.notify();
    return true;
  }

  /** Wipes history — used when loading a new document. */
  clear(): void {
    this.undoStack.length = 0;
    this.redoStack.length = 0;
    this.lastPushAt = 0;
    this.notify();
  }

  on<K extends keyof CommandStackEvents & string>(
    type: K,
    handler: (payload: CommandStackEvents[K]) => void,
  ): Unsubscribe {
    return this.bus.on(type, handler);
  }

  dispose(): void {
    this.bus.dispose();
  }

  /* ---------------- internals ---------------- */

  private push(command: ICommand): void {
    // Any new edit invalidates the redo branch.
    this.redoStack.length = 0;

    const top = this.undoStack[this.undoStack.length - 1];
    const withinWindow = this.now() - this.lastPushAt <= this.mergeWindowMs;

    if (
      top &&
      withinWindow &&
      command.coalesceKey != null &&
      top.coalesceKey === command.coalesceKey &&
      top.mergeWith
    ) {
      const merged = top.mergeWith(command);
      if (merged) {
        this.undoStack[this.undoStack.length - 1] = merged;
        this.lastPushAt = this.now();
        return;
      }
    }

    this.undoStack.push(command);
    this.lastPushAt = this.now();

    if (this.undoStack.length > this.limit) this.undoStack.shift();
  }

  private notify(): void {
    this.bus.emit('changed', { canUndo: this.canUndo, canRedo: this.canRedo });
  }
}
