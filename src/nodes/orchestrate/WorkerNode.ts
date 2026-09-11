import { Err, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { BINDING_SIDE } from '@core/model/contracts/ports';
import type { ExecutionContext, INodeExecutor, PortOutputs } from '@core/execution/INodeExecutor';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import { CATEGORY, PORT } from '../vocabulary';
import { modelField } from '../modelField';
import { SKILL_PORT, rulesModeField } from '../skillLayer';

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

export function createWorkerNode(providers: ProviderRegistry): INodeDefinition {
  return defineNode(
    {
      id: WORKER_TYPE,
      // `async def` on the Python side, so a timeout can interrupt it —
      // see `NodeSpec.interruptible` and `langchain-drift-watch/02`.
      interruptible: true,
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
        modelField(providers),
        {
          kind: 'textarea',
          key: 'role',
          label: 'Role',
          placeholder: 'What this worker archetype handles, e.g. "weather and forecast questions"',
          minRows: 3,
          maxRows: 10,
          defaultValue: '',
          onCard: false,
          // One string, two audiences (gallery ticket 16). It is shown to the
          // supervisor's labelling model alongside the node's title — the
          // description half of the archetype roster — *and* it is context in
          // this worker's own system prompt, so what you type here changes
          // how this worker answers. It used to reach the labeller only: a
          // card reading "at most three short bullet points" returned a
          // ten-row table, live, because the text was never sent. Context and
          // not a rules layer, so `rulesMode: replace` and a wired skill
          // customise behaviour without deleting the worker's identity.
          //
          // The title itself (slugified) is the dispatch key; see
          // `backend/openstategraph/abc/orchestrator.py`'s `archetype_key`.
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
        // Extend, by default, rather than replace: the worker's built-in tool
        // directive is what stopped it answering a database question from
        // parametric memory, so a wired skill adds to it unless the developer
        // says otherwise.
        rulesModeField(),
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
        // The same declaration the other four model-driven types use
        // (`../skillLayer`). A worker with no skill wired shows no symptom at
        // all, which is exactly why the gap had to be looked for rather than
        // waited for.
        { ...SKILL_PORT },
        {
          id: 'tools',
          direction: 'in',
          type: PORT.tool,
          label: 'worker tools',
          side: BINDING_SIDE.consumer,
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
}

/**
 * Browser-preview executor — refuses, like the Orchestrator's.
 *
 * A worker's dispatch is a Python-runtime `Send` task (ticket 07 bars the
 * browser from executing); refusing with a clear message beats the silent
 * skip a `standard` node with no executor would otherwise get.
 */
export const workerExecutor: INodeExecutor = {
  id: WORKER_TYPE,
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
