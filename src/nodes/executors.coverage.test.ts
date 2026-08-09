import { describe, expect, it } from 'vitest';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';
import {
  isToolExecutor,
  type ExecutionContext,
  type INodeExecutor,
} from '@core/execution/INodeExecutor';
import type { Workbench } from '@app/Workbench';
import { textInputExecutor } from './inputs/TextInputNode';
import { markdownFileExecutor } from './inputs/MarkdownFileNode';
import { formattedOutputExecutor } from './output/FormattedOutputNode';
import { formatReportExecutor } from './orchestrate/FormatReportNode';
import { orchestratorExecutor } from './orchestrate/OrchestratorNode';
import { workerExecutor } from './orchestrate/WorkerNode';
import { humanApprovalExecutor } from './routing/HumanApprovalNode';
import { subgraphExecutor } from './compose/SubgraphNode';
import { teamExecutor } from './compose/TeamNode';
import { redditSearchExecutor, redditSearchNode } from './tools/RedditSearchNode';
import {
  executeSqlExecutor,
  executeSqlNode,
  getAllTablesExecutor,
  getAllTablesNode,
  getTableSchemaExecutor,
  getTableSchemaNode,
} from './tools/ChinookDatabaseNode';
import { TABULAR_NODES } from './tools/TabularDataNode';
import { registerChinookNodes } from './workflowScoped';
import { PLATFORM_TOOL_NODES } from './tools/PlatformToolsNode';

/**
 * Every executor's browser-preview behaviour, exercised directly (coverage
 * push): honest refusals refuse with a reason, dataflow stubs produce their
 * declared ports, and tool bodies answer from their local implementations.
 */

function ctxFor(
  workbench: Workbench,
  nodeId: string,
  inputs: Record<string, unknown> = {},
): ExecutionContext {
  const node = workbench.model.node(nodeId);
  if (!node) throw new Error('missing node');
  return {
    node,
    workflow: workbench.model,
    providers: workbench.providers,
    signal: new AbortController().signal,
    input: <T>(port: string) => inputs[port] as T | undefined,
    inputs: <T>(port: string) =>
      (Array.isArray(inputs[port])
        ? inputs[port]
        : inputs[port] === undefined
          ? []
          : [inputs[port]]) as T[],
    toolsOn: () => [],
    invokeTool: async () => ({ ok: true, value: 'stub' }) as const,
    log: () => undefined,
    reportUsage: () => undefined,
  };
}

describe('dataflow executors', () => {
  it('text input publishes its prompt', async () => {
    const workbench = makeWorkbench();
    const id = addNode(workbench, TYPE.textInput, { data: { prompt: 'hello flows' } });
    const outcome = await textInputExecutor.execute(ctxFor(workbench, id.id));
    expect(outcome.ok && outcome.value['text']).toBe('hello flows');
  });

  it('markdown file publishes its content as skill text', async () => {
    const workbench = makeWorkbench();
    const id = addNode(workbench, TYPE.markdownFile, { data: { content: '# rules' } });
    const outcome = await markdownFileExecutor.execute(ctxFor(workbench, id.id));
    expect(outcome.ok).toBe(true);
  });

  it('formatted output renders whatever arrives', async () => {
    const workbench = makeWorkbench();
    const id = addNode(workbench, TYPE.output);
    const outcome = await formattedOutputExecutor.execute(
      ctxFor(workbench, id.id, { result: '**bold**' }),
    );
    expect(outcome.ok).toBe(true);
  });

  it('formatted output refuses an empty run honestly', async () => {
    const workbench = makeWorkbench();
    const id = addNode(workbench, TYPE.output);
    const outcome = await formattedOutputExecutor.execute(ctxFor(workbench, id.id));
    expect(outcome.ok).toBe(false);
  });

  it('format report joins incoming candidates', async () => {
    const workbench = makeWorkbench();
    const id = addNode(workbench, 'function.format_report');
    const outcome = await formatReportExecutor.execute(
      ctxFor(workbench, id.id, { candidate: ['a', 'b'] }),
    );
    expect(outcome.ok).toBe(true);
  });
});

describe('honest backend-only refusals', () => {
  const cases: Array<[string, { execute: (ctx: ExecutionContext) => Promise<unknown> }, string]> = [
    ['orchestrator', orchestratorExecutor, 'orchestrate.supervisor'],
    ['worker', workerExecutor, 'orchestrate.worker'],
    ['human approval', humanApprovalExecutor, 'human.approval'],
  ];
  for (const [label, executor, type] of cases) {
    it(`${label} refuses in the browser preview`, async () => {
      const workbench = makeWorkbench();
      const id = addNode(workbench, type);
      const outcome = (await executor.execute(ctxFor(workbench, id.id))) as { ok: boolean };
      expect(outcome.ok).toBe(false);
    });
  }

  it('subgraph and team refuse, naming the slug when set', async () => {
    const workbench = makeWorkbench();
    const bare = addNode(workbench, 'workflow.subgraph');
    const named = addNode(workbench, 'team.workflow', { data: { workflow: 'chinook-metrics-team' } });
    const bareOut = await subgraphExecutor.execute(ctxFor(workbench, bare.id));
    const namedOut = await teamExecutor.execute(ctxFor(workbench, named.id));
    expect(bareOut.ok).toBe(false);
    expect(namedOut.ok).toBe(false);
    if (!namedOut.ok) expect(namedOut.error).toContain('chinook-metrics-team');
  });

  it('every platform/web prebuilt refuses toward Chat', async () => {
    const workbench = makeWorkbench();
    for (const entry of PLATFORM_TOOL_NODES) {
      const id = addNode(workbench, entry.definition.id);
      const outcome = await entry.executor.execute(ctxFor(workbench, id.id));
      expect(outcome.ok).toBe(false);
    }
  });
});

describe('local tool bodies', () => {
  function scopedWorkbench(): Workbench {
    const workbench = makeWorkbench();
    // Chinook + tabular are workflow-scoped, not in the default catalogue.
    registerChinookNodes(workbench.registry, workbench.engine.executors);
    for (const entry of TABULAR_NODES) {
      workbench.registry.nodeTypes.upsert(entry.definition);
      workbench.engine.executors.upsert(entry.executor);
    }
    return workbench;
  }

  const chinook: Array<[{ id: string }, INodeExecutor]> = [
    [getAllTablesNode, getAllTablesExecutor],
    [getTableSchemaNode, getTableSchemaExecutor],
    [executeSqlNode, executeSqlExecutor],
  ];

  it('chinook tools answer from their sample data', async () => {
    const workbench = scopedWorkbench();
    for (const [definition, executor] of chinook) {
      if (!isToolExecutor(executor)) throw new Error('not a tool');
      const node = addNode(workbench, definition.id);
      expect(executor.describeTool(node).name.length).toBeGreaterThan(0);
    }
    const [tablesDef, tablesExec] = chinook[0]!;
    if (!isToolExecutor(tablesExec)) throw new Error('not a tool');
    const node = addNode(workbench, tablesDef.id);
    const outcome = await tablesExec.invokeTool(node, {}, ctxFor(workbench, node.id));
    expect(outcome.ok && outcome.value).toContain('Artist');
  });

  it('tabular tools describe themselves and answer their stubs', async () => {
    const workbench = scopedWorkbench();
    for (const entry of TABULAR_NODES) {
      if (!isToolExecutor(entry.executor)) throw new Error('not a tool');
      const id = addNode(workbench, entry.definition.id);
      const node = workbench.model.node(id.id)!;
      expect(entry.executor.describeTool(node).name.length).toBeGreaterThan(0);
      const outcome = await entry.executor.invokeTool(
        node,
        { query: 'SELECT 1', fileName: 'vgsales.csv', nRows: 5, maxRows: 10 },
        ctxFor(workbench, id.id),
      );
      expect(typeof outcome.ok).toBe('boolean');
    }
  });

  it('tabular query stub refuses non-SELECT statements', async () => {
    const workbench = scopedWorkbench();
    const query = TABULAR_NODES.find((e) => e.definition.id === 'tool.tabular-query')!;
    if (!isToolExecutor(query.executor)) throw new Error('not a tool');
    const id = addNode(workbench, query.definition.id);
    const node = workbench.model.node(id.id)!;
    const outcome = await query.executor.invokeTool(
      node,
      { query: 'DROP TABLE vgsales' },
      ctxFor(workbench, id.id),
    );
    expect(outcome.ok).toBe(false);
  });

  it('reddit search falls back to labelled sample data offline', async () => {
    const workbench = makeWorkbench();
    const node = addNode(workbench, redditSearchNode.id);
    if (!isToolExecutor(redditSearchExecutor)) throw new Error('not a tool');
    const outcome = await redditSearchExecutor.invokeTool(
      node,
      { query: 'typescript' },
      ctxFor(workbench, node.id),
    );
    expect(outcome.ok).toBe(true);
  });
});
