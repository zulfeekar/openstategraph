import { describe, expect, it, vi } from 'vitest';
import { ModelRegistry } from '@core/model/ModelRegistry';
import { WorkflowModel } from '@core/model/WorkflowModel';
import { CommandStack } from './CommandStack';
import { CompositeCommand, type CommandContext, type ICommand } from './ICommand';
import { MountEditScope } from './editScope';

/**
 * What may be edited while a mounted **instance** is on screen — ticket 42.
 *
 * A mount's per-instance state is `data.overrides`: a map of child node id →
 * field key → value. That shape can express "this mount's grader is stricter".
 * It cannot express a moved card, a new node, or a deleted edge — and
 * `docs/decisions/mount-overrides.md` is explicit that this is by design ("an
 * override narrows, it does not delete"; deleting behaviour belongs in the
 * package).
 *
 * So a gesture that cannot become an override has exactly three possible
 * fates, and two of them are bad:
 *
 * - applied and silently lost when you navigate away — the silent no-op this
 *   codebase has a standing rule against, and the worst option because the
 *   work looks done;
 * - applied to the shared package — fork-on-configure by accident, hitting
 *   every other instance;
 * - **refused, with a sentence saying why.** That is what this is.
 *
 * The gate lives at `CommandStack.execute`, which every gesture, shortcut and
 * menu already funnels through — one place rather than a guard on each of
 * `NodeEditor`, `EdgeEditor`, grouping, the clipboard and drag-to-move. And it
 * decides by asking the **command** whether it is expressible per instance,
 * rather than by matching labels: a label is display text, and a list of
 * allowed labels here would be a second place to update every time a command
 * is added.
 */
const fieldEdit = (label: string): ICommand => ({
  label,
  perInstance: true,
  execute: vi.fn(),
  undo: vi.fn(),
});

const structural = (label: string): ICommand => ({
  label,
  execute: vi.fn(),
  undo: vi.fn(),
});

function stackWith(scope: MountEditScope): {
  stack: CommandStack;
  refusals: { command: ICommand; reason: string }[];
} {
  const model = new WorkflowModel();
  const ctx: CommandContext = { model, registry: new ModelRegistry(), editScope: scope };
  const stack = new CommandStack(ctx);
  const refusals: { command: ICommand; reason: string }[] = [];
  stack.on('refused', (event) => refusals.push(event));
  return { stack, refusals };
}

describe('MountEditScope', () => {
  it('allows everything while a document is open', () => {
    const { stack, refusals } = stackWith(new MountEditScope());
    const command = structural('Move nodes');
    stack.execute(command);
    expect(command.execute).toHaveBeenCalled();
    expect(refusals).toEqual([]);
  });

  it('allows a field edit while an instance is open', () => {
    // The one kind of change an override *can* carry. In the next tranche this
    // becomes a write to the parent's overrides rather than to the child.
    const scope = new MountEditScope();
    scope.enterInstance('wf-music');
    const { stack, refusals } = stackWith(scope);
    const command = fieldEdit('Edit rules');
    stack.execute(command);
    expect(command.execute).toHaveBeenCalled();
    expect(refusals).toEqual([]);
  });

  it('refuses a structural change, and never runs it', () => {
    const scope = new MountEditScope();
    scope.enterInstance('wf-music');
    const { stack, refusals } = stackWith(scope);
    const command = structural('Delete node');
    stack.execute(command);
    expect(command.execute).not.toHaveBeenCalled();
    expect(refusals).toHaveLength(1);
  });

  it('says which mount, and what to do instead', () => {
    // A refusal with no way forward is just a wall. The sentence has to name
    // the instance and point at the shared definition, because editing the
    // class is the legitimate way to do what was just refused.
    const scope = new MountEditScope();
    scope.enterInstance('wf-music');
    const { stack, refusals } = stackWith(scope);
    stack.execute(structural('Delete node'));
    const reason = refusals[0]!.reason;
    expect(reason).toContain('wf-music');
    expect(reason.toLowerCase()).toContain('shared definition');
  });

  it('leaves the history untouched when it refuses', () => {
    // A refused command is not an undo step: pressing undo afterwards must
    // reach past it to whatever the user really did last.
    const scope = new MountEditScope();
    scope.enterInstance('wf-music');
    const { stack } = stackWith(scope);
    stack.execute(structural('Delete node'));
    expect(stack.canUndo).toBe(false);
  });

  it('refuses a composite whose children are not all expressible', () => {
    // Deleting a node arrives as a composite (the node, then its edges). A
    // gate that only looked at the wrapper would wave the whole thing through.
    const scope = new MountEditScope();
    scope.enterInstance('wf-music');
    const { stack, refusals } = stackWith(scope);
    const composite = new CompositeCommand('Delete node and its edges', [
      fieldEdit('Edit rules'),
      structural('Remove edge'),
    ]);
    stack.execute(composite);
    expect(refusals).toHaveLength(1);
  });

  it('allows a composite of field edits', () => {
    const scope = new MountEditScope();
    scope.enterInstance('wf-music');
    const { stack, refusals } = stackWith(scope);
    const a = fieldEdit('Edit rules');
    const b = fieldEdit('Edit criteria');
    stack.execute(new CompositeCommand('Edit two fields', [a, b]));
    expect(refusals).toEqual([]);
    expect(a.execute).toHaveBeenCalled();
  });

  it('goes back to allowing everything on leaving the instance', () => {
    const scope = new MountEditScope();
    scope.enterInstance('wf-music');
    scope.leaveInstance();
    const { stack, refusals } = stackWith(scope);
    const command = structural('Move nodes');
    stack.execute(command);
    expect(command.execute).toHaveBeenCalled();
    expect(refusals).toEqual([]);
  });

  it('is absent by default, so nothing that does not opt in is affected', () => {
    // Every existing construction of `CommandContext` omits the scope, and
    // must behave exactly as it did before this existed.
    const model = new WorkflowModel();
    const stack = new CommandStack({ model, registry: new ModelRegistry() });
    const command = structural('Move nodes');
    stack.execute(command);
    expect(command.execute).toHaveBeenCalled();
  });
});
