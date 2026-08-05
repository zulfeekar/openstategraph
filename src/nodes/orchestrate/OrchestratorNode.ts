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

export const ORCHESTRATOR_TYPE = 'orchestrate.supervisor';

const FIELD_MAX_SUBTASKS = 'maxSubtasks';

/** Mirrors `MAX_SUBTASKS` in `backend/dyflow/abc/orchestrator.py`. */
export const DEFAULT_MAX_SUBTASKS = 8;

export class OrchestratorNodeModel extends AbstractNodeModel {
  get maxSubtasks(): number {
    return this.getNumber(FIELD_MAX_SUBTASKS, DEFAULT_MAX_SUBTASKS);
  }
}

/**
 * Splits one instruction into a bounded list of subtasks and fans them out.
 *
 * Mirrors `IOrchestrator -> BaseOrchestrator -> Orchestrator`
 * (`backend/dyflow/abc/orchestrator.py`) — decomposition is deterministic by
 * default (numbered lists, semicolons, "and"), so this node works with no
 * model configuration at all. It never runs the subtasks itself: the
 * `workers` port is a **fan-out declaration**, not control flow, matching
 * `WorkflowCompiler`'s `worker`-typed port category. An edge from `workers`
 * becomes `add_conditional_edges(...) -> Send(...)` in the compiled graph,
 * never a `workflow.json` graph edge — the same reason `tool`/`skill` links
 * are bindings rather than edges.
 *
 * `feedback` closes the same loop the Grader's `revise` output opens: a
 * rejected attempt re-enters the orchestrator, which replans rather than
 * merely retrying, and — critically — plans under a fresh generation so its
 * subtask ids never collide with the rejected attempt's
 * (`backend/tests/test_orchestrator.py`, "a later generation never reuses an
 * earlier one's ids").
 */
export const orchestratorNode: INodeDefinition = defineNode(
  {
    id: ORCHESTRATOR_TYPE,
    category: CATEGORY.agent,
    label: 'Orchestrator',
    description: 'Splits an instruction into subtasks and fans them out to workers.',
    iconId: 'node-orchestrator',
    accent: 'blue',
    keywords: ['orchestrate', 'fan-out', 'send', 'subtasks', 'plan', 'supervisor', 'split'],
    defaultSize: { width: 260, height: 200 },
    fields: [
      {
        kind: 'slider',
        key: FIELD_MAX_SUBTASKS,
        label: 'Max subtasks',
        defaultValue: DEFAULT_MAX_SUBTASKS,
        min: 1,
        max: 16,
        step: 1,
        onCard: false,
        // A runaway split (a 500-item numbered list) must not fan out to 500
        // workers — bounding here is cheaper and more reliable than trusting
        // the instruction author to self-limit.
        format: (value) => `· ${value} max`,
      },
    ],
    ports: [
      {
        id: 'instruction',
        direction: 'in',
        type: PORT.text,
        label: 'instruction',
        required: true,
        description: 'The instruction to decompose into subtasks.',
      },
      {
        id: 'feedback',
        direction: 'in',
        type: PORT.feedback,
        label: 'feedback',
        description: 'A grader’s rejection. Replans under a fresh generation, rather than retrying.',
      },
      {
        id: 'workers',
        direction: 'out',
        type: PORT.worker,
        label: 'workers',
        // A fan-out declaration, not control flow — the compiler records at
        // most one dispatch target per orchestrator (`CompiledPlan.fan_out`
        // is keyed by orchestrator id), so this is a single wire, not a bus.
        maxConnections: 1,
        required: true,
        side: 'bottom',
        appearance: 'pill',
        description: 'The worker node subtasks are dispatched to.',
      },
    ],
  },
  OrchestratorNodeModel,
);

/**
 * Browser-preview executor — deliberately refuses, like the Router's.
 *
 * An orchestrator compiles to `add_conditional_edges` returning `Send`
 * objects in the **Python** runtime (ticket 07 bars the browser from
 * executing). It exists rather than being omitted because a `standard` node
 * with no registered executor is silently skipped by the preview engine — a
 * run would look successful while no fan-out ever happened.
 */
export const orchestratorExecutor: INodeExecutor = {
  id: orchestratorNode.id,
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    ctx.log('Fan-out is evaluated by the Python runtime, not the browser preview.');
    return Promise.resolve(
      Err(
        'This Orchestrator compiles to a LangGraph Send fan-out and runs in the Python ' +
          'runtime. Use “Run” against the backend to evaluate it.',
      ),
    );
  },
};
