import { beforeEach, describe, expect, it } from 'vitest';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';
import type { Workbench } from '@app/Workbench';
import { DEFAULT_MAX_SUBTASKS, ORCHESTRATOR_TYPE, orchestratorExecutor, orchestratorNode } from './OrchestratorNode';
import { WORKER_TYPE, workerExecutor, workerNode } from './WorkerNode';
import {
  FORMAT_REPORT_TYPE,
  formatReportExecutor,
  formatReportNode,
  type FormatReportNodeModel,
} from './FormatReportNode';

const emptyData = (definition: { fields: readonly { key: string; defaultValue?: unknown }[] }) =>
  Object.fromEntries(definition.fields.map((f) => [f.key, f.defaultValue ?? null])) as never;

/**
 * The graph-engineering half of the orchestrator ladder
 * (`backend/dyflow/abc/orchestrator.py`): these three node types are what a
 * developer actually drags onto the canvas to build the fan-out/join
 * documented in `.scratch/fullstack-langgraph/decisions/loop-graph-harness.md`.
 */
describe('orchestrator + worker — the fan-out declaration', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('exposes a bounded max-subtasks field, defaulting to the backend cap', () => {
    const field = orchestratorNode.fields.find((f) => f.key === 'maxSubtasks');
    expect(field?.defaultValue).toBe(DEFAULT_MAX_SUBTASKS);
  });

  it('declares instruction, feedback and a workers fan-out bus', () => {
    const ports = orchestratorNode.ports(emptyData(orchestratorNode));
    const instruction = ports.find((p) => p.id === 'instruction');
    const feedback = ports.find((p) => p.id === 'feedback');
    const workers = ports.find((p) => p.id === 'workers');

    expect(instruction).toMatchObject({ direction: 'in', type: 'text' });
    expect(feedback).toMatchObject({ direction: 'in', type: 'feedback' });
    // A bus since ticket 37: each wire declares one worker archetype the
    // supervisor can label subtasks for (`CompiledPlan.fan_out` keeps them
    // in edge order).
    expect(workers).toMatchObject({ direction: 'out', type: 'worker', maxConnections: null });
  });

  it('lets an orchestrator wire its workers port to a Worker node', () => {
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const worker = addNode(workbench, TYPE.worker);

    const verdict = workbench.controller.edges.connect(
      { nodeId: orchestrator.id, portId: 'workers' },
      { nodeId: worker.id, portId: 'dispatch' },
    );

    expect(verdict.ok).toBe(true);
  });

  it('lets an orchestrator wire a second worker archetype (ticket 37)', () => {
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const weather = addNode(workbench, TYPE.worker);
    const countries = addNode(workbench, TYPE.worker, { at: { x: 200, y: 0 } });

    workbench.controller.edges.connect(
      { nodeId: orchestrator.id, portId: 'workers' },
      { nodeId: weather.id, portId: 'dispatch' },
    );
    const second = workbench.controller.edges.connect(
      { nodeId: orchestrator.id, portId: 'workers' },
      { nodeId: countries.id, portId: 'dispatch' },
    );

    expect(second.ok).toBe(true);
  });

  it('refuses a workers edge into anything but a worker-typed port', () => {
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const agent = addNode(workbench, TYPE.agent);

    const verdict = workbench.controller.edges.connect(
      { nodeId: orchestrator.id, portId: 'workers' },
      { nodeId: agent.id, portId: 'prompt' },
    );

    // `worker` only accepts `worker` (the port-type default), so this is not
    // a fan-out edge silently reinterpreted as control flow.
    expect(verdict.ok).toBe(false);
  });

  it('a grader can send feedback into the orchestrator, closing the replan loop', () => {
    const orchestrator = addNode(workbench, TYPE.orchestrator);
    const grader = addNode(workbench, TYPE.grader);

    const verdict = workbench.controller.edges.connect(
      { nodeId: grader.id, portId: 'revise' },
      { nodeId: orchestrator.id, portId: 'feedback' },
    );

    expect(verdict.ok).toBe(true);
  });

  it('the worker accepts tool and skill bindings like the Agent node', () => {
    const ports = workerNode.ports(emptyData(workerNode));
    expect(ports.find((p) => p.id === 'skill')?.type).toBe('skill');
    expect(ports.find((p) => p.id === 'tools')?.type).toBe('tool');
  });

  it('the worker exposes a result output, not a raw dispatch echo', () => {
    const ports = workerNode.ports(emptyData(workerNode));
    expect(ports.find((p) => p.id === 'result')).toMatchObject({ direction: 'out', type: 'result' });
  });

  it('both refuse to execute in the browser preview — Python owns the fan-out', async () => {
    const ctx = { log: () => {}, input: () => undefined, node: undefined } as never;

    const orchestratorResult = await orchestratorExecutor.execute(ctx);
    const workerResult = await workerExecutor.execute(ctx);

    expect(orchestratorResult.ok).toBe(false);
    expect(workerResult.ok).toBe(false);
  });
});

/**
 * `function.format_report` — a deterministic step, never a tool. Unlike its
 * three siblings above it genuinely runs in the browser preview, since
 * joining text needs no model and no LangGraph runtime.
 */
describe('format report — a function, not a tool', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('defaults its title rather than rendering a blank heading', () => {
    const node = addNode(workbench, TYPE.formatReport) as FormatReportNodeModel;
    expect(node.reportTitle).toBe('Report');
  });

  it('uses the configured title once set', () => {
    const node = addNode(workbench, TYPE.formatReport);
    workbench.controller.nodes.setField(node.id, 'reportTitle', 'Chinook revenue report');
    const reread = workbench.model.node(node.id) as FormatReportNodeModel;
    expect(reread.reportTitle).toBe('Chinook revenue report');
  });

  it('joins an upstream result into a Markdown report', async () => {
    const node = addNode(workbench, TYPE.formatReport) as FormatReportNodeModel;
    workbench.controller.nodes.setField(node.id, 'reportTitle', 'Chinook revenue report');
    const reread = workbench.model.node(node.id) as FormatReportNodeModel;

    const ctx = {
      log: () => {},
      input: () => 'Genre X leads by revenue.',
      node: reread,
    } as never;

    const outcome = await formatReportExecutor.execute(ctx);

    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.value.report).toContain('# Chinook revenue report');
      expect(outcome.value.report).toContain('Genre X leads by revenue.');
    }
  });

  it('is a distinct node type from a tool, not a flag on one type', () => {
    // The whole point of the function/tool split: it must be impossible to
    // configure one node type into the other's role.
    expect(formatReportNode.id).not.toBe(WORKER_TYPE);
    expect(formatReportNode.category).toBe('output');
  });
});

describe('catalogue registration', () => {
  it('registers all three under their documented ids', () => {
    const workbench = makeWorkbench();
    const ids = workbench.registry.nodeTypes.list().map((n) => n.id);
    expect(ids).toContain(ORCHESTRATOR_TYPE);
    expect(ids).toContain(WORKER_TYPE);
    expect(ids).toContain(FORMAT_REPORT_TYPE);
  });
});
