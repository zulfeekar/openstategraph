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

export const ORCHESTRATOR_TYPE = 'orchestrate.supervisor';

const FIELD_MAX_SUBTASKS = 'maxSubtasks';

/**
 * The supervisor's inline rules — the one layer `rulesMode` switches over.
 *
 * **Not `instruction`, which is what the backend used to read.** `instruction`
 * is this node's *input port* id, and a port id is not a data key: nothing on
 * this card, in the inspector or in a document could ever write it, so
 * `_orchestrator`'s `rules=` argument was `""` for every supervisor ever built.
 * The two names sat one line apart in the same node and read as the same thing,
 * which is precisely why the spelling here matches the layer's name in
 * `docs/decisions/skill-layer.md` — the node's own rules field — and matches the
 * Router's `rules` rather than inventing a fifth spelling.
 */
const FIELD_RULES = 'rules';

/** Mirrors `MAX_SUBTASKS` in `backend/openstategraph/abc/orchestrator.py`. */
export const DEFAULT_MAX_SUBTASKS = 8;

export class OrchestratorNodeModel extends AbstractNodeModel {
  get maxSubtasks(): number {
    return this.getNumber(FIELD_MAX_SUBTASKS, DEFAULT_MAX_SUBTASKS);
  }

  /**
   * The one part of the supervisor's prompt the developer writes — and the
   * switch between the two decomposition strategies: empty keeps the free
   * deterministic splitter, anything here buys a planning call.
   */
  get rules(): string {
    return this.getText(FIELD_RULES);
  }
}

/**
 * Splits one instruction into a bounded list of subtasks and fans them out.
 *
 * Mirrors `IOrchestrator -> BaseOrchestrator -> {Orchestrator,
 * PlanningOrchestrator}` (`backend/openstategraph/abc/orchestrator.py`).
 * Decomposition is deterministic (numbered lists, semicolons, "and") until
 * *Planning rules* are written, so this node works with no model
 * configuration at all and pays for a planning call only when a developer
 * asked for one. It never runs the subtasks itself: the
 * `workers` port is a **fan-out declaration**, not control flow, matching
 * `WorkflowCompiler`'s `worker`-typed port category. An edge from `workers`
 * becomes `add_conditional_edges(...) -> Send(...)` in the compiled graph,
 * never a `workflow.json` graph edge — the same reason `tool`/`skill` links
 * are bindings rather than edges.
 *
 * `feedback` closes the same loop the Grader's `revise` output opens: a
 * rejected attempt re-enters the orchestrator, which replans rather than
 * merely retrying — the rejection is passed *into* the split, so a supervisor
 * with planning rules can come back with a different division of labour
 * rather than the same one re-dispatched (gallery ticket 23) — and,
 * critically, plans under a fresh generation so its
 * subtask ids never collide with the rejected attempt's
 * (`backend/tests/test_orchestrator.py`, "a later generation never reuses an
 * earlier one's ids").
 */
export function createOrchestratorNode(providers: ProviderRegistry): INodeDefinition {
  return defineNode(
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
        modelField(providers),
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
        // The supervisor drives a model too, so it composes a prompt and takes
        // the same skill layer as the other four. Writing rules here is what
        // *turns the planning call on* — see the placeholder's note below.
        {
          kind: 'textarea',
          key: FIELD_RULES,
          label: 'Planning rules',
          // Rules *only*: the preamble and output contract are locked on the
          // Python base and are deliberately not fields. They live in
          // `BaseOrchestrator.PROMPT` — one `SystemPrompt` ClassVar since
          // install-experience 19, which deleted the separate `PREAMBLE` and
          // `OUTPUT_CONTRACT` symbols this comment used to name (ticket 38).
          // Unlike the Router and Grader, nothing here mirrors their text, so
          // there is nothing for `test_prompt_mirror_contract.py` to pin.
          //
          // **This text now steers the split as well as the dispatch**
          // (gallery ticket 15). It used to reach the archetype-*labelling*
          // call alone, so the shipped `team` template's "Split the task into
          // the smallest set of independent subtasks." changed nothing at all
          // and the field was labelled for the only job it could do. With
          // rules written here the supervisor makes one planning call; with
          // the field empty it keeps the deterministic splitter (numbered
          // lists, semicolons, "and"), which is free and reproducible and is
          // still the right answer for a punctuated brief.
          placeholder:
            'Split the brief into independent subtasks a worker can answer alone. ' +
            'Anything needing SQL goes to the analyst; web lookups go to the researcher.',
          defaultValue: '',
          minRows: 3,
          maxRows: 14,
          // Off the card, with the switch that modifies it: the card shows a
          // derived intent line, never this text (`skillLayer.ts` — "the mode
          // rides where the rules ride").
          onCard: false,
          group: 'Prompt',
        },
        rulesModeField(),
      ],
      ports: [
        {
          id: 'instruction',
          direction: 'in',
          type: PORT.text,
          label: 'instruction',
          required: true,
          // An agent that plans, then an orchestrator that decomposes the plan,
          // is the same chaining case — see `AgentNode`'s `prompt` port.
          accepts: [PORT.text, PORT.result],
          description: 'The instruction to decompose into subtasks.',
        },
        {
          id: 'feedback',
          direction: 'in',
          type: PORT.feedback,
          label: 'feedback',
          description:
            'A grader’s rejection. Replans under a fresh generation, rather than retrying.',
        },
        // One declaration, in `../skillLayer`.
        { ...SKILL_PORT },
        {
          id: 'workers',
          direction: 'out',
          type: PORT.worker,
          label: 'workers',
          // A fan-out declaration, not control flow — and since ticket 37 a
          // *bus*: each wire declares one worker archetype
          // (`CompiledPlan.fan_out` records them in edge order), and the
          // supervisor labels every subtask with the archetype it should
          // dispatch to. One wire is still the common case and behaves
          // exactly as before.
          maxConnections: null,
          required: true,
          side: BINDING_SIDE.consumer,
          appearance: 'pill',
          description: 'The worker archetype nodes subtasks are dispatched to.',
        },
      ],
    },
    OrchestratorNodeModel,
  );
}

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
  id: ORCHESTRATOR_TYPE,
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
