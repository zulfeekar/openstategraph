import { Err, Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { BINDING_SIDE } from '@core/model/contracts/ports';
import type {
  ExecutionContext,
  INodeExecutor,
  PortOutputs,
  ToolHandle,
} from '@core/execution/INodeExecutor';
import type { LLMMessage } from '@core/providers/ILLMProvider';
import { ProviderRegistry } from '@core/providers/ProviderRegistry';
import { CATEGORY, PORT } from '../vocabulary';
import { MODEL_FIELD_KEY, modelField, resolveModelSelection } from '../modelField';
import { effortFrom } from '../effortField';
import { SKILL_PORT, rulesModeField } from '../skillLayer';

const FIELD_MODEL = MODEL_FIELD_KEY;
const FIELD_BUDGET = 'tokenBudget';
const FIELD_TIER = 'tier';
const FIELD_SYSTEM_PROMPT = 'systemPrompt';
const FIELD_SUBAGENTS = 'subagents';

/**
 * The worker every deep agent already carries.
 *
 * `create_deep_agent` auto-adds it unless the caller declares a subagent of
 * this name, and disabling it needs a harness profile this product does not
 * register. So the decision `organisms-first-class/84` records is **name it**,
 * not "quietly have one": a `task` tool that can already delegate to an
 * anonymous worker nobody configured is a capability a developer cannot see.
 */
const GENERAL_PURPOSE_SUBAGENT = 'general-purpose';

/** How many workers one agent may declare. Rows the model must choose between. */
const MAX_SUBAGENTS = 8;

const SUBAGENTS_NOTE =
  'On the deep agent runtime this agent can hand work to a named worker and ' +
  `get one answer back. It already carries one, "${GENERAL_PURPOSE_SUBAGENT}", ` +
  "with this agent's own tools; declare a subagent of that name to replace " +
  'it. A worker is given a task and reports a result — it never sees this ' +
  "agent's conversation or the workflow's state, though the run's context " +
  'does reach its tools.';

/**
 * Turns before the loop is cut off.
 *
 * A model that keeps requesting tools without ever answering would
 * otherwise spend the user's tokens indefinitely. Six is enough for a
 * genuine multi-tool chain and short enough to notice.
 */
const MAX_TURNS = 6;

export class AgentNodeModel extends AbstractNodeModel {
  get modelSelection(): string {
    return this.getText(FIELD_MODEL);
  }

  /** react | deep | custom — which agent-family tier the backend builds. */
  get tier(): string {
    return this.getText(FIELD_TIER) || 'react';
  }

  /** The developer's system-prompt rules. Composed, never the whole prompt. */
  get systemPrompt(): string {
    return this.getText(FIELD_SYSTEM_PROMPT);
  }

  get tokenBudget(): number {
    return this.getNumber(FIELD_BUDGET, 500);
  }
}

/**
 * Builds the AI Agent definition.
 *
 * Takes the provider registry so the model picker reflects what is actually
 * available — including models discovered from the user's own account — and
 * so the node has no static knowledge of any vendor.
 */
export function createAgentNode(providers: ProviderRegistry): INodeDefinition {
  return defineNode(
    {
      id: 'agent.llm',
      category: CATEGORY.agent,
      label: 'AI Agent',
      description: 'Runs an LLM with tool calling.',
      iconId: 'node-agent',
      accent: 'indigo',
      keywords: ['llm', 'model', 'claude', 'gpt', 'ollama', 'reason'],
      defaultSize: { width: 252, height: 220 },
      maxInstances: undefined,
      fields: [
        // One descriptor, shared with every other family that drives a model
        // (`../modelField`). It used to be declared here and nowhere else,
        // which is how five other node types ended up with no picker at all
        // while the backend read the key for all six.
        modelField(providers),
        {
          kind: 'slider',
          key: FIELD_BUDGET,
          label: 'Token budget',
          min: 500,
          max: 16_000,
          step: 100,
          defaultValue: 500,
          format: (value) => `· ${value.toLocaleString()}`,
        },
        {
          // deepagents' RubricMiddleware (beta): what "done" looks like. A
          // grader sub-agent judges the transcript against this and the
          // agent iterates until satisfied (max 3 rounds). Distinct from a
          // Grader *node*: this loop is inside the agent.
          kind: 'textarea',
          key: 'rubric',
          label: 'Rubric (self-grading)',
          placeholder: 'e.g. tests pass; cites a figure from the rows; under 200 words',
          defaultValue: '',
          minRows: 3,
          maxRows: 10,
          onCard: false,
          group: 'Judgement',
          advanced: true,
        },
        {
          // LangChain's prebuilt SummarizationMiddleware (ticket 66): when
          // the conversation bloats, older turns are summarized by the
          // model and the recent tail kept verbatim.
          //
          // **On by default** (owner, 2026-08-15). Off meant "we have
          // summarization" was true of a feature no default install ever
          // used — and the middleware it switched on was built with no
          // trigger, so even turning it on got nothing. The threshold lives
          // where the toggle becomes middleware, in the compiler
          // (`node_runtime.SUMMARIZE_FRACTION` / `SUMMARIZE_TOKENS`), never
          // here: a number on the card would be a second place to say it.
          //
          // Flipping a default does **not** rewrite existing documents.
          // `defaultsFrom` materialises every default into `data`, so an
          // agent saved before today carries a literal `false` and keeps it;
          // the backend reads *absent* as on and an explicit `false` as off.
          // Opening a document must never change what it does — the same
          // rule `withMigratedRulesMode` states in `skillLayer`.
          kind: 'toggle',
          key: 'summarize',
          label: 'Summarize long context',
          defaultValue: true,
          onCard: false,
          group: 'Context',
          advanced: true,
        },
        {
          // Mirrors Router/Grader's tier select — the backend's
          // agent_node_for_tier reads this exact key, so an agent can be a
          // plain ReAct loop or a deep-agent harness by configuration.
          kind: 'select',
          key: FIELD_TIER,
          label: 'Runtime',
          defaultValue: 'react',
          onCard: false,
          group: 'Runtime',
          options: [
            { value: 'react', label: 'Agent · create_agent' },
            { value: 'deep', label: 'Deep agent · create_deep_agent' },
            { value: 'custom', label: 'Custom · hand-written node' },
          ],
        },
        {
          // The *rules* half of the composed prompt. The machinery (context
          // from the skill port, ordering) is owned by the backend's
          // resolve_prompt() — this field can shape the agent's behaviour
          // but never break its plumbing.
          kind: 'textarea',
          key: FIELD_SYSTEM_PROMPT,
          label: 'System prompt',
          placeholder: 'e.g. You are a data analyst. Cite figures from the tools.',
          defaultValue: '',
          // The longest prose the editor holds, so it gets the most room.
          minRows: 4,
          maxRows: 20,
          onCard: false,
          group: 'Prompt',
        },
        // The one extend/replace switch, shared with the other four
        // model-driven types. It governs the rules typed above *and* the
        // skill wired to the port below — never the locked machinery.
        rulesModeField(),
        {
          // `organisms-first-class/84`. The deep runtime's `subagents`
          // parameter existed and nothing ever filled it, so every deep agent
          // could delegate to exactly one anonymous worker.
          //
          // **Declared here, on the node's own data, and deliberately not as
          // canvas nodes wired to a bus.** A subagent is not a step in this
          // graph: it never joins the shared state, never appears in a
          // superstep, and its result reaches the agent as a tool result.
          // Drawing it would say the opposite of every one of those. It is
          // also not a *workflow node* — `CLAUDE.md` fixes that word for
          // another workflow run as one isolated step, with its own package,
          // slug and mount — and blurring the two would cost the vocabulary
          // its only distinction.
          //
          // A row is three strings and a tool choice, which is exactly a
          // `deepagents.SubAgent`, so it travels in `workflow.json` as data
          // with no host-language code in it.
          kind: 'readonly',
          key: 'subagentsNote',
          label: 'Delegation',
          defaultValue: SUBAGENTS_NOTE,
          onCard: false,
          group: 'Delegation',
          advanced: true,
        },
        {
          kind: 'repeatable-group',
          key: FIELD_SUBAGENTS,
          label: 'Subagents',
          hint:
            'Deep agent runtime only. Each subagent is a separate worker: it ' +
            'is given a task and reports a result, and never sees this ' +
            "agent's conversation.",
          defaultValue: [],
          addLabel: 'Add subagent',
          maxRows: MAX_SUBAGENTS,
          onCard: false,
          group: 'Delegation',
          advanced: true,
          fields: [
            {
              kind: 'text',
              key: 'name',
              label: 'Name',
              placeholder: 'e.g. researcher',
              hint: `What the agent delegates to. Naming one "${GENERAL_PURPOSE_SUBAGENT}" replaces the built-in worker.`,
              defaultValue: '',
              validate: (value) => (value.trim() ? null : 'Name required'),
            },
            {
              kind: 'text',
              key: 'description',
              label: 'When to use it',
              placeholder: 'e.g. Looks facts up in the wired tools and reports one number.',
              hint: 'How the agent decides to delegate. The model reads this and nothing else about the worker.',
              defaultValue: '',
              validate: (value) => (value.trim() ? null : 'Description required'),
            },
            {
              kind: 'textarea',
              key: 'systemPrompt',
              label: 'Worker instructions',
              placeholder: 'e.g. You research one question at a time. Answer with the figure only.',
              defaultValue: '',
              minRows: 3,
              maxRows: 12,
              validate: (value) => (value.trim() ? null : 'Instructions required'),
            },
            {
              // The library's own two states, and no third: a spec that omits
              // `tools` inherits the parent's, and one that passes `[]` has
              // none. A per-tool picker would need this node's wired tool
              // list, which is a port question and not a field question.
              kind: 'select',
              key: 'tools',
              label: 'Tools',
              defaultValue: 'inherit',
              options: [
                { value: 'inherit', label: "This agent's tools" },
                { value: 'none', label: 'No tools' },
              ],
            },
          ],
        },
      ],
      ports: [
        {
          id: 'prompt',
          direction: 'in',
          type: PORT.text,
          label: 'prompt',
          required: true,
          // Prompt chaining: an earlier agent's answer is a legitimate task
          // for the next one (generate → improve → polish). Declared on the
          // port, not on the `text` port type, so the affordance appears
          // exactly where it makes sense.
          accepts: [PORT.text, PORT.result],
          description: 'The task for the agent.',
        },
        // Declared once for every model-driven type (`../skillLayer`), with
        // the mode that governs it in `fields` above. It used to be spelled
        // out here and on the Worker, and nowhere else — while the backend
        // read `plan.skill_bindings` for five node types.
        { ...SKILL_PORT },
        {
          id: 'tools',
          direction: 'in',
          type: PORT.tool,
          label: 'agent tools',
          // Several tools converge here, so this port sits below the card as
          // a shared bus rather than as one more row in the footer.
          side: BINDING_SIDE.consumer,
          appearance: 'pill',
          // Unlimited. `null`, not `Infinity`, so the descriptor survives JSON.
          maxConnections: null,
          description: 'Tools the agent may call.',
        },
        {
          id: 'feedback',
          direction: 'in',
          type: PORT.feedback,
          label: 'feedback',
          // The other half of the only legal cycle. A grader's `revise` output
          // is the sole `feedback` source, and `acyclicRule` permits a loop only
          // when it closes on one — so the type system gates the cycle, and an
          // accidental loop stays impossible to draw.
          //
          // The rejection is always written *about an answer*, and this agent
          // need not be the one that wrote it (`organisms-first-class/37`): an
          // agent two steps upstream may take the same sentence as a reason to
          // ask a different question. Which one it is, the compiler derives
          // from the edges (`organisms-first-class/54`) — an agent that did not
          // produce the judged text is never told it did, so this no longer
          // asks the developer to correct the preamble in their Rules.
          description:
            'A grader’s rejection of the answer. If this agent wrote that answer it is ' +
            'asked to revise it; if it feeds the node that did, it is asked to change ' +
            'what it produces instead.',
        },
        {
          id: 'result',
          direction: 'out',
          type: PORT.result,
          label: 'result',
          description: 'The agent’s final answer.',
        },
      ],
    },
    AgentNodeModel,
  );
}

/**
 * The agent loop.
 *
 * Runs completion → tool calls → completion until the model answers without
 * requesting a tool. Tool invocation is delegated back to the engine, so
 * this executor never learns what any individual tool does — which is what
 * lets a new tool node work with the agent the moment it is linked.
 */
export const agentExecutor: INodeExecutor = {
  id: 'agent.llm',

  async execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
    const node = ctx.node as AgentNodeModel;

    // An empty selection means "the workflow's model" — the same rule the
    // backend applies — which in this offline preview resolves to the mock
    // simulator when the document names none.
    const selection = resolveModelSelection(node.modelSelection, ctx.workflow.settings);
    const resolved = ctx.providers.resolve(selection);
    if (!resolved) return Err(`Unknown model "${selection}"`);
    const { provider, modelId } = resolved;

    if (!provider.isConfigured()) {
      return Err(`${provider.label} needs an API key before it can run`);
    }

    const prompt = (ctx.input<string>('prompt') ?? '').trim();
    if (prompt.length === 0) return Err('No prompt is connected to the agent');

    const skill = (ctx.input<string>('skill') ?? '').trim();
    const handles = ctx.toolsOn('tools');
    const specs = handles.map((handle) => handle.spec);
    const byName = new Map<string, ToolHandle>(handles.map((handle) => [handle.spec.name, handle]));

    ctx.log(`${provider.label} · ${modelId}`);
    if (specs.length > 0) {
      ctx.log(`Tools available: ${specs.map((spec) => spec.name).join(', ')}`);
    }

    const messages: LLMMessage[] = [{ role: 'user', content: prompt }];
    let answer = '';

    for (let turn = 1; turn <= MAX_TURNS; turn += 1) {
      if (ctx.signal.aborted) return Err('Run cancelled');

      const completion = await provider.complete({
        model: modelId,
        messages,
        maxTokens: node.tokenBudget,
        signal: ctx.signal,
        // Omitted when nothing was chosen — see `effortFrom`. The adapters
        // each decide what to do with a tier their vendor may not have; none
        // of them forwards one blindly.
        ...(effortFrom(node.data) ? { effort: effortFrom(node.data) } : {}),
        ...(skill ? { system: skill } : {}),
        // Withhold the tool list on the final permitted turn so the model
        // is obliged to answer rather than requesting yet another call.
        ...(specs.length > 0 && turn < MAX_TURNS ? { tools: specs } : {}),
      });

      if (!completion.ok) return Err(completion.error);
      const result = completion.value;
      ctx.reportUsage(result.usage);

      if (result.stopReason === 'refusal') {
        return Err('The model declined this request');
      }

      if (result.toolCalls.length === 0) {
        answer = result.text.trim();
        if (result.stopReason === 'max_tokens') {
          ctx.log(`Answer was cut off at the ${node.tokenBudget.toLocaleString()} token budget`);
        }
        break;
      }

      messages.push({
        role: 'assistant',
        content: result.text,
        toolCalls: result.toolCalls,
      });

      for (const call of result.toolCalls) {
        const handle = byName.get(call.name);
        if (!handle) {
          // Report the miss back to the model rather than failing the run;
          // it can recover by choosing a tool that exists.
          messages.push({
            role: 'tool',
            content: `No tool named "${call.name}" is connected.`,
            toolCallId: call.id,
            name: call.name,
          });
          continue;
        }

        ctx.log(`→ ${call.name}(${summarise(call.arguments)})`);
        const outcome = await ctx.invokeTool(handle, call.arguments);
        messages.push({
          role: 'tool',
          content: outcome.ok ? outcome.value : `Tool failed: ${outcome.error}`,
          toolCallId: call.id,
          name: call.name,
        });
        if (!outcome.ok) ctx.log(`✗ ${call.name}: ${outcome.error}`);
      }
    }

    if (answer.length === 0) {
      return Err(`The agent used all ${MAX_TURNS} turns without producing an answer`);
    }

    return Ok({ result: answer });
  },
};

function summarise(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 0) return '';
  return entries
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join(', ');
}
