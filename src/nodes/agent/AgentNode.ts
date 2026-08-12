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
          onCard: false,
          group: 'Judgement',
          advanced: true,
        },
        {
          // LangChain's prebuilt SummarizationMiddleware (ticket 66): when
          // the conversation bloats, older turns are summarized by the
          // model and the recent tail kept verbatim.
          kind: 'toggle',
          key: 'summarize',
          label: 'Summarize long context',
          defaultValue: false,
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
          onCard: false,
          group: 'Prompt',
        },
        // The one extend/replace switch, shared with the other four
        // model-driven types. It governs the rules typed above *and* the
        // skill wired to the port below — never the locked machinery.
        rulesModeField(),
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
          description: 'A grader’s rejection, to revise against.',
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
