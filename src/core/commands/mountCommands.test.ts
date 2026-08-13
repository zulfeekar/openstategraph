import { describe, expect, it } from 'vitest';
import { ModelRegistry, defineNode } from '@core/model/ModelRegistry';
import { WorkflowModel } from '@core/model/WorkflowModel';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { MountContext } from '@core/model/MountContext';
import { parseMountAddress } from '@core/model/MountAddress';
import { CommandStack } from './CommandStack';
import type { CommandContext } from './ICommand';
import { MountEditScope } from './editScope';
import { ClearMountOverrideCommand, SetMountOverrideCommand } from './mountCommands';

/**
 * `instance.field = x` — ticket 42, tranche 4.
 *
 * Editing a field while a mount is displayed has to do two things at once, and
 * they are two different documents:
 *
 * 1. **write an override on the parent**, because that is where an instance's
 *    own state lives and it is what a later Save persists;
 * 2. **update the model**, because the canvas is a one-way projection and a
 *    card that did not change would say the edit had not happened.
 *
 * Undo takes back both. The half worth its own test is the *absence* case:
 * restoring "no override" must remove the key, not write `null` — a `null`
 * override is not the package default, it is an override whose value is null,
 * and `apply_mount_overrides` would apply it over the package's real value.
 */
class AgentModel extends AbstractNodeModel {}

const AGENT = defineNode(
  {
    id: 'agent.llm',
    category: 'agents',
    label: 'Agent',
    description: 'test',
    iconId: 'node-agent',
    accent: 'violet',
    defaultSize: { width: 200, height: 100 },
    fields: [{ kind: 'textarea', key: 'rules', label: 'Rules', defaultValue: '' }],
    ports: [],
  },
  AgentModel,
);

function modelWithAgent(): WorkflowModel {
  const model = new WorkflowModel();
  model.addNode(AGENT.create({ id: 'agent-sql', position: { x: 0, y: 0 } }));
  return model;
}

function harness() {
  const registry = new ModelRegistry();
  registry.nodeTypes.register(AGENT);
  const model = modelWithAgent();

  const root: Record<string, unknown> = {
    version: 2,
    name: 'concierge',
    nodes: [
      { id: 'wf-music', type: 'workflow.subgraph', data: { workflow: 'chinook-assistant' } },
      { id: 'wf-other', type: 'workflow.subgraph', data: { workflow: 'chinook-assistant' } },
    ],
    edges: [],
  };
  const mounts = new MountContext(parseMountAddress('concierge/wf-music')!, root);
  const scope = new MountEditScope();
  scope.enterInstance('wf-music');
  const ctx: CommandContext = { model, registry, editScope: scope, mounts };
  return { stack: new CommandStack(ctx), model, mounts, root };
}

const overridesOf = (root: Record<string, unknown>, id: string): unknown => {
  const nodes = root['nodes'] as { id: string; data: Record<string, unknown> }[];
  const raw = nodes.find((n) => n.id === id)?.data['overrides'];
  return typeof raw === 'string' ? JSON.parse(raw) : raw;
};

describe('SetMountOverrideCommand', () => {
  it('writes the override on the parent, not the package', () => {
    const { stack, mounts, root } = harness();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'stricter here'));
    expect(overridesOf(root, 'wf-music')).toEqual({ 'agent-sql': { rules: 'stricter here' } });
    expect(mounts.readOverride('agent-sql', 'rules')).toBe('stricter here');
  });

  it('updates the card, because the canvas is a projection', () => {
    const { stack, model } = harness();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'stricter here'));
    expect(model.node('agent-sql')?.data['rules']).toBe('stricter here');
  });

  it('leaves a sibling mount of the same package untouched', () => {
    const { stack, root } = harness();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'stricter here'));
    expect(overridesOf(root, 'wf-other')).toBeUndefined();
  });

  it('is allowed by the edit scope, unlike a structural change', () => {
    // The counterpart to `editScope`'s refusals: this is the one shape a mount
    // can carry, so it must pass the same gate that stops a delete.
    const { stack, root } = harness();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'x'));
    expect(overridesOf(root, 'wf-music')).toBeDefined();
    expect(stack.canUndo).toBe(true);
  });

  describe('undo', () => {
    it('removes the key entirely when there was no override before', () => {
      // Not `null`, and not an empty object: a `null` override is an override
      // whose value is null, which `apply_mount_overrides` would apply over
      // the package's real value.
      const { stack, root } = harness();
      stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'stricter here'));
      stack.undo();
      expect(overridesOf(root, 'wf-music')).toBeUndefined();
    });

    it('restores an override that was already there', () => {
      const { stack, root } = harness();
      stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'first'));
      stack.execute(new SetMountOverrideCommand('agent-sql', 'model', 'keep me'));
      stack.undo();
      expect(overridesOf(root, 'wf-music')).toEqual({ 'agent-sql': { rules: 'first' } });
    });

    it('puts the card back too', () => {
      const { stack, model } = harness();
      stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'stricter here'));
      stack.undo();
      // Back to the package's own value, which for this node is its declared
      // default — the instance no longer says anything about the field.
      expect(model.node('agent-sql')?.data['rules']).toBe('');
    });

    it('redo re-applies to both', () => {
      // The capture-on-execute rule (`ICommand`): a redo must not treat the
      // undone value as the thing to restore.
      const { stack, model, root } = harness();
      stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'stricter here'));
      stack.undo();
      stack.redo();
      expect(model.node('agent-sql')?.data['rules']).toBe('stricter here');
      expect(overridesOf(root, 'wf-music')).toEqual({ 'agent-sql': { rules: 'stricter here' } });
    });
  });

  it('coalesces a burst of typing into one undo step, per field', () => {
    const { stack, root } = harness();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'a'));
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'ab'));
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'abc'));
    stack.undo();
    expect(overridesOf(root, 'wf-music')).toBeUndefined();
  });

  it('does nothing at all when no mount is open', () => {
    // Constructed by a caller that thought an instance was displayed and was
    // wrong. Writing to the model alone would be an edit with nowhere to be
    // saved — the silent no-op, arriving by a different door.
    const registry = new ModelRegistry();
    registry.nodeTypes.register(AGENT);
    const model = modelWithAgent();
    const stack = new CommandStack({ model, registry });
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'x'));
    expect(model.node('agent-sql')?.data['rules']).toBe('');
  });
});

describe('ClearMountOverrideCommand — back to the package default', () => {
  function withInherited() {
    const registry = new ModelRegistry();
    registry.nodeTypes.register(AGENT);
    const model = modelWithAgent();
    const root: Record<string, unknown> = {
      version: 2,
      name: 'concierge',
      nodes: [{ id: 'wf-music', type: 'workflow.subgraph', data: { workflow: 'child' } }],
      edges: [],
    };
    const inherited: Record<string, unknown> = {
      nodes: [{ id: 'agent-sql', data: { rules: 'the package rules' } }],
    };
    const mounts = new MountContext(parseMountAddress('concierge/wf-music')!, root, inherited);
    const scope = new MountEditScope();
    scope.enterInstance('wf-music', mounts);
    return {
      stack: new CommandStack({ model, registry, editScope: scope, mounts }),
      model,
      root,
    };
  }

  it('removes the override and restores the package value on the card', () => {
    const { stack, model, root } = withInherited();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'mine'));
    stack.execute(new ClearMountOverrideCommand('agent-sql', 'rules'));
    expect(overridesOf(root, 'wf-music')).toBeUndefined();
    expect(model.node('agent-sql')?.data['rules']).toBe('the package rules');
  });

  it('does not write an override equal to the default', () => {
    // The whole reason this is its own command. Writing the inherited value
    // back through `SetMountOverride` looks identical on screen and is a
    // different document: the mount would keep counting it, and a later change
    // to the package would stop reaching this instance — a revert that quietly
    // pins the value.
    const { stack, root } = withInherited();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'mine'));
    stack.execute(new ClearMountOverrideCommand('agent-sql', 'rules'));
    const nodes = root['nodes'] as { id: string; data: Record<string, unknown> }[];
    expect(nodes[0]!.data['overrides']).toBeUndefined();
  });

  it('undo puts the override back', () => {
    const { stack, model, root } = withInherited();
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'mine'));
    stack.execute(new ClearMountOverrideCommand('agent-sql', 'rules'));
    stack.undo();
    expect(overridesOf(root, 'wf-music')).toEqual({ 'agent-sql': { rules: 'mine' } });
    expect(model.node('agent-sql')?.data['rules']).toBe('mine');
  });

  it('reports whether a field is overridden at all', () => {
    const { stack } = withInherited();
    const mounts = stack.context.mounts!;
    expect(mounts.isOverridden('agent-sql', 'rules')).toBe(false);
    stack.execute(new SetMountOverrideCommand('agent-sql', 'rules', 'mine'));
    expect(mounts.isOverridden('agent-sql', 'rules')).toBe(true);
  });
});
