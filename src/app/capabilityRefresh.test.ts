import { beforeEach, describe, expect, it } from 'vitest';
import { Ok, type Result } from '@core/kernel/Result';
import { ModelRegistry } from '@core/model/ModelRegistry';
import { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import type { ToolCapability, WorkflowCapabilities } from '@core/runtime/WorkflowFileClient';
import {
  decideCapabilityRefresh,
  forgetKnownCapabilities,
  recordKnownCapabilities,
  refreshWorkflowCapabilities,
} from './capabilityRefresh';

const capability = (id: string): ToolCapability => ({
  id,
  name: id,
  description: `discovered tool ${id}`,
  argsSchema: {},
});

const clientReturning = (tools: readonly ToolCapability[]) => ({
  capabilities: (): Promise<Result<WorkflowCapabilities, string>> =>
    Promise.resolve(Ok({ tools, pluginTools: [], warnings: [] })),
});

beforeEach(() => {
  forgetKnownCapabilities();
});

/**
 * Ticket 18's hot-reload gap: a new file in a workflow's `tools/` folder
 * doesn't touch `workflow.json`'s `savedAt` at all, so it needs its own
 * comparison sharing the same poll cadence `decideFileWatchAction` uses.
 */
describe('decideCapabilityRefresh', () => {
  it('establishes a baseline on first observation, rather than treating it as new', () => {
    const action = decideCapabilityRefresh([capability('a')], undefined);
    expect(action).toEqual({ kind: 'baseline', ids: ['a'] });
  });

  it('does nothing when the observed set matches what is known', () => {
    const action = decideCapabilityRefresh([capability('a'), capability('b')], ['a', 'b']);
    expect(action).toEqual({ kind: 'unchanged' });
  });

  it('is unchanged regardless of ordering — the backend promises no stable order', () => {
    const action = decideCapabilityRefresh([capability('b'), capability('a')], ['a', 'b']);
    expect(action).toEqual({ kind: 'unchanged' });
  });

  it('flags a newly discovered tool, naming it', () => {
    const action = decideCapabilityRefresh([capability('a'), capability('b')], ['a']);
    expect(action).toEqual({ kind: 'changed', ids: ['a', 'b'], added: ['b'] });
  });

  it('flags a removed tool too, even though nothing was added', () => {
    const action = decideCapabilityRefresh([capability('a')], ['a', 'b']);
    expect(action).toEqual({ kind: 'changed', ids: ['a'], added: [] });
  });

  it('an empty list is a real baseline, not skipped', () => {
    const action = decideCapabilityRefresh([], undefined);
    expect(action).toEqual({ kind: 'baseline', ids: [] });
  });
});

/**
 * The side-effecting half. Ticket 18's gap is only closed if pressing
 * Refresh actually puts a node type in the registry — the decision being
 * right is necessary, not sufficient.
 */
describe('refreshWorkflowCapabilities', () => {
  const stand = () => ({
    registry: new ModelRegistry(),
    executors: new Registry<INodeExecutor>('executors'),
  });

  it('does nothing when no saved workflow is open — there is no tools/ folder to read', async () => {
    const { registry, executors } = stand();
    const outcome = await refreshWorkflowCapabilities(
      null,
      registry,
      executors,
      clientReturning([capability('a')]),
    );
    expect(outcome).toEqual({ kind: 'no-workflow' });
    expect(registry.nodeTypes.size).toBe(0);
  });

  it('registers a newly discovered tool as a workflow-scoped node type', async () => {
    recordKnownCapabilities('chinook-nl-to-sql', []);
    const { registry, executors } = stand();

    const outcome = await refreshWorkflowCapabilities(
      'chinook-nl-to-sql',
      registry,
      executors,
      clientReturning([capability('scratch_probe')]),
    );

    expect(outcome).toEqual({ kind: 'changed', total: 1, added: ['scratch_probe'] });
    const registered = registry.nodeTypes.list();
    expect(registered).toHaveLength(1);
    // The palette's always-available sections filter on exactly this stamp.
    expect(registered[0]?.scope).toBe('workflow');
  });

  it('reports honestly when nothing changed since the load baselined it', async () => {
    recordKnownCapabilities('chinook-nl-to-sql', [capability('a')]);
    const { registry, executors } = stand();

    const outcome = await refreshWorkflowCapabilities(
      'chinook-nl-to-sql',
      registry,
      executors,
      clientReturning([capability('a')]),
    );

    expect(outcome).toEqual({ kind: 'unchanged', total: 1 });
  });
});
