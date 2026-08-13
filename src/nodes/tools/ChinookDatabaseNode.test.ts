import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench } from '@core/testing/fixtures';
import { isToolExecutor, type ExecutionContext } from '@core/execution/INodeExecutor';
import { registerScopedFamily } from '../workflowScoped';
import {
  getAllTablesExecutor,
  getAllTablesNode,
  getTableSchemaExecutor,
  getTableSchemaNode,
} from './ChinookDatabaseNode';

/**
 * The schema tool tells the truth about what it is configured with — which is
 * nothing.
 *
 * It used to declare a `Table` select of eleven hardcoded names defaulting to
 * `Artist`. The backend tool (`workflows/chinook-assistant/tools/chinook.py`)
 * takes `table` as a *model* argument and declares no `configure()`, so that
 * control reached nothing: it changed no run, and told every reader that this
 * node fetched Artist's schema. These tests pin both halves of the fix — the
 * control is gone, and a document that still carries the dead key loads
 * silently rather than erroring or warning at the user.
 */

function contextFor(nodeId: string): ExecutionContext {
  const workbench = makeWorkbench();
  const node = workbench.model.node(nodeId);
  return {
    node: node!,
    workflow: workbench.model,
    providers: workbench.providers,
    signal: new AbortController().signal,
    input: () => undefined,
    inputs: () => [],
    toolsOn: () => [],
    invokeTool: async () => ({ ok: true, value: 'stub' }) as const,
    log: () => undefined,
    reportUsage: () => undefined,
  } as unknown as ExecutionContext;
}

describe('Get Table Schema', () => {
  it('declares no control that implies a per-node table', () => {
    // The shared execution overrides (retries, timeout) are appended by
    // `defineToolNode` to every tool; what must not be here is anything
    // naming a table.
    expect(getTableSchemaNode.fields.map((field) => field.key)).not.toContain('tableName');
    expect(getTableSchemaNode.fields.some((field) => field.kind === 'select')).toBe(false);
  });

  it('advertises the table as a model argument with no baked-in default', () => {
    if (!isToolExecutor(getTableSchemaExecutor)) throw new Error('not a tool');
    const workbench = makeWorkbench();
    registerScopedFamily('chinook', workbench.registry, workbench.engine.executors);
    const node = addNode(workbench, getTableSchemaNode.id);

    const spec = getTableSchemaExecutor.describeTool(node);
    const table = (spec.parameters.properties as Record<string, Record<string, unknown>>)[
      'tableName'
    ];

    expect(spec.parameters.required).toEqual(['tableName']);
    // A `default` here would be the old lie in a second place: it would push
    // the model toward one table before it has looked at what exists.
    expect(table).not.toHaveProperty('default');
  });

  it('loads a legacy document carrying the dead tableName without complaint', () => {
    const workbench = makeWorkbench();
    registerScopedFamily('chinook', workbench.registry, workbench.engine.executors);

    const node = addNode(workbench, getTableSchemaNode.id, { data: { tableName: 'Artist' } });

    // Unknown keys ride along in the data bag, ignored: nothing reads them,
    // no field renders them, and the compiler never saw them even before.
    expect(workbench.model.node(node.id)).toBe(node);
    expect(node.definition.fields.map((field) => field.key)).not.toContain('tableName');
    expect(node.data['tableName']).toBe('Artist');
  });
});

describe('the browser preview refuses instead of inventing a schema', () => {
  const cases = [
    ['get schema', getTableSchemaNode, getTableSchemaExecutor],
    ['list tables', getAllTablesNode, getAllTablesExecutor],
  ] as const;

  for (const [label, definition, executor] of cases) {
    it(`${label} points at the database rather than answering from a copy`, async () => {
      if (!isToolExecutor(executor)) throw new Error('not a tool');
      const workbench = makeWorkbench();
      registerScopedFamily('chinook', workbench.registry, workbench.engine.executors);
      const node = addNode(workbench, definition.id);

      const outcome = await executor.invokeTool(node, { tableName: 'Artist' }, contextFor(node.id));

      expect(outcome.ok).toBe(false);
      if (outcome.ok) return;
      expect(outcome.error).toMatch(/database/i);
    });
  }
});
