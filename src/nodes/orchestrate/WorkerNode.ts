import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type {
  ExecutionContext,
  INodeExecutor,
  PortOutputs,
} from '@core/execution/INodeExecutor';
import { CATEGORY, PORT } from '../vocabulary';

export const WORKER_TYPE = 'orchestrate.worker';

/**
 * Runs one dispatched subtask.
 *
 * There is exactly one `Worker` node on a canvas per orchestrator, wired
 * from its `workers` fan-out port — but at runtime it runs once **per
 * dispatched `Send`**, each with only that task's `task_id`/`task_instruction`
 * in scope. This is the isolation ticket 08 already documents for subagents,
 * made concrete: a worker never sees the parent's message history or graph
 * state, only the payload it was sent (verified directly against the
 * installed LangGraph: a `Send` payload *replaces*, not merges with, the
 * dispatched node's visible state).
 *
 * Takes `tool`/`skill` bindings exactly like the Agent node, because a
 * worker with tools but no directive skill text was found live to answer
 * from parametric knowledge rather than calling them — see the "not done"
 * section of `.scratch/fullstack-langgraph/decisions/loop-graph-harness.md`.
 * The runtime instances a single worker node produces are **view state**,
 * never document state (ticket 27) — nothing about a specific dispatch is
 * ever written back into `workflow.json`.
 */
export class WorkerNodeModel extends AbstractNodeModel {}

export const workerNode: INodeDefinition = defineNode(
  {
    id: WORKER_TYPE,
    category: CATEGORY.agent,
    label: 'Worker',
    description: 'Runs one subtask dispatched by an orchestrator.',
    iconId: 'node-worker',
    accent: 'blue',
    keywords: ['worker', 'subagent', 'dispatch', 'task', 'send', 'fan-out'],
    defaultSize: { width: 252, height: 200 },
    // One Worker node per *archetype* (ticket 37): an orchestrator may wire
    // several, each a different kind of specialist. The runtime still
    // multiplies each into N task instances, and that multiplication is
    // never a second node on the canvas.
    maxInstances: undefined,
    fields: [
      {
        kind: 'textarea',
        key: 'role',
        label: 'Role',
        placeholder: 'What this worker archetype handles, e.g. "weather and forecast questions"',
        defaultValue: '',
        onCard: false,
        // Shown to the supervisor's labelling model alongside the node's
        // title — the description half of the archetype roster. The title
        // itself (slugified) is the dispatch key; see
        // `backend/dyflow/abc/orchestrator.py`'s `archetype_key`.
      },
      {
        kind: 'toggle',
        key: 'default',
        label: 'Default worker',
        defaultValue: false,
        onCard: false,
        // Where unlabelled or unrecognised subtasks land. With no card
        // claiming it, the first wired archetype is the default; two claims
        // is a validator warning (`singleDefaultWorkerRule`).
      },
    ],
    ports: [
      {
        id: 'dispatch',
        direction: 'in',
        type: PORT.worker,
        label: 'dispatch',
        required: true,
        description: 'Subtasks dispatched by an orchestrator’s fan-out.',
      },
      {
        id: 'skill',
        direction: 'in',
        type: PORT.skill,
        label: 'skill',
        description: 'System instruction that shapes how the worker approaches its task.',
      },
      {
        id: 'tools',
        direction: 'in',
        type: PORT.tool,
        label: 'worker tools',
        side: 'bottom',
        appearance: 'pill',
        maxConnections: null,
        description: 'Tools this worker may call.',
      },
      {
        id: 'result',
        direction: 'out',
        type: PORT.result,
        label: 'result',
        description: 'This subtask’s answer, keyed by its subtask id when joined downstream.',
      },
    ],
  },
  WorkerNodeModel,
);

/**
 * Browser-preview executor — refuses, like the Orchestrator's.
 *
 * A worker's dispatch is a Python-runtime `Send` task (ticket 07 bars the
 * browser from executing); refusing with a clear message beats the silent
 * skip a `standard` node with no executor would otherwise get.
 */
export const workerExecutor: INodeExecutor = {
  id: workerNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('Worker dispatch is evaluated by the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This Worker runs as a LangGraph Send task in the Python runtime. Use “Run” ' +
          'against the backend to evaluate it.',
      ),
    );
  },
};
