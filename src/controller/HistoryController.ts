import type { Unsubscribe } from '@core/kernel/Disposable';
import type { CommandStack } from '@core/commands/CommandStack';
import type { IHistoryController } from './contracts';

/**
 * Undo, redo, and composite edits.
 *
 * A thin adapter over `CommandStack`, and deliberately so: it exists to stop
 * the rest of the app importing the stack directly. Before it, `AutoLayout`
 * reached through to `controller.commands.transact(...)`, which meant a canvas
 * feature held a reference to the whole command stack — including `execute`
 * and `clear` — to group one batch of moves.
 */
export class HistoryController implements IHistoryController {
  constructor(private readonly commands: CommandStack) {}

  undo(): void {
    this.commands.undo();
  }

  redo(): void {
    this.commands.redo();
  }

  get canUndo(): boolean {
    return this.commands.canUndo;
  }

  get canRedo(): boolean {
    return this.commands.canRedo;
  }

  /** Groups everything `fn` executes into a single undo step. */
  transact(label: string, fn: () => void): void {
    this.commands.transact(label, fn);
  }

  onChange(handler: (state: { canUndo: boolean; canRedo: boolean }) => void): Unsubscribe {
    return this.commands.on('changed', ({ canUndo, canRedo }) => handler({ canUndo, canRedo }));
  }

  /**
   * Fires when a change was **not** allowed — a structural edit inside a
   * mounted instance, today (ticket 42, `core/commands/editScope`).
   *
   * On this collaborator because a refusal is a fact about the history: the
   * command did not run and nothing was pushed, so "what just happened to my
   * undo stack" is the question it answers. The shell renders the sentence;
   * nothing in `core/` or here knows what a toast is.
   */
  onRefused(handler: (state: { label: string; reason: string }) => void): Unsubscribe {
    return this.commands.on('refused', ({ command, reason }) =>
      handler({ label: command.label, reason }),
    );
  }
}
