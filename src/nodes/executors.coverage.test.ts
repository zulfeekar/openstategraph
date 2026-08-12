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
    const named = addNode(workbench, 'team.workflow', { data: { workflow: 'some-team-package' } });
    const bareOut = await subgraphExecutor.execute(ctxFor(workbench, bare.id));
    const namedOut = await teamExecutor.execute(ctxFor(workbench, named.id));
    expect(bareOut.ok).toBe(false);
    expect(namedOut.ok).toBe(false);
    if (!namedOut.ok) expect(namedOut.error).toContain('some-team-package');
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
    // Chinook is workflow-scoped, not in the default catalogue.
    registerChinookNodes(workbench.registry, workbench.engine.executors);
    return workbench;
  }

  const chinook: Array<[{ id: string }, INodeExecutor]> = [
    [getAllTablesNode, getAllTablesExecutor],
    [getTableSchemaNode, getTableSchemaExecutor],
    [executeSqlNode, executeSqlExecutor],
  ];

  it('chinook tools all describe themselves', async () => {
    const workbench = scopedWorkbench();
    for (const [definition, executor] of chinook) {
      if (!isToolExecutor(executor)) throw new Error('not a tool');
      const node = addNode(workbench, definition.id);
      expect(executor.describeTool(node).name.length).toBeGreaterThan(0);
    }
  });

  /**
   * The two schema-shaped tools refuse rather than answering from a copy of
   * the database — see `ChinookDatabaseNode.ts`'s header and its own test.
   * The query tool still simulates *rows*, which is a different claim.
   */
  it('the chinook query tool still simulates rows offline', async () => {
    const workbench = scopedWorkbench();
    const [queryDef, queryExec] = chinook[2]!;
    if (!isToolExecutor(queryExec)) throw new Error('not a tool');
    const node = addNode(workbench, queryDef.id);
    const outcome = await queryExec.invokeTool(
      node,
      { sqlQuery: 'SELECT * FROM Artist' },
      ctxFor(workbench, node.id),
    );
    expect(outcome.ok && outcome.value).toContain('Artist');
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
