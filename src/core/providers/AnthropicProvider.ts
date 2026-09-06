// Type-only: the SDK is ~300kB and most sessions never touch it, so the
// implementation is pulled in on first use via a dynamic import below.
import type Anthropic from '@anthropic-ai/sdk';
import { Err, Ok, type Result } from '@core/kernel/Result';
import {
  AbstractLLMProvider,
  type CompletionRequest,
  type CompletionResult,
  type LLMMessage,
  type ModelDescriptor,
  type StopReason,
  type ToolCall,
} from './ILLMProvider';

/**
 * Below this ceiling, extended thinking is switched off.
 *
 * `max_tokens` bounds thinking *and* answer text together on the current
 * Claude models, and thinking is on by default. A small token budget with
 * thinking enabled produces a response that is nearly all reasoning
 * followed by a truncated answer — so a budget this low disables thinking
 * rather than silently overriding the user's setting.
 */
const THINKING_FLOOR = 4096;

/**
 * Mitigations required when thinking is disabled.
 *
 * With reasoning off, the model occasionally writes a tool call into its
 * visible text instead of emitting a structured tool-use block (the call
 * then silently never runs), and can leak internal XML tags. These two
 * lines are the documented fixes; the second is deliberately generic
 * because naming the tags is measurably less effective.
 */
const NO_THINKING_GUARDRAILS = [
  'You may say a brief sentence before using a tool.',
  'Do not include internal or system XML tags in your response.',
].join(' ');

export class AnthropicProvider extends AbstractLLMProvider {
  readonly id = 'anthropic';
  readonly label = 'Anthropic';
  readonly requiresApiKey = true;
  override readonly credentialsHint = 'console.anthropic.com → API keys';
  override readonly runtimeCredentialKey = 'ANTHROPIC_API_KEY';
  /**
   * Transmitted below as `output_config.effort`, which is why this adapter can
   * declare them at all. Declared once for the provider rather than repeated
   * on each descriptor: every model in this catalogue is a current-generation
   * reasoning model, so a per-model copy would be four identical lists that
   * can drift.
   */
  override readonly reasoningEffortLevels = ['low', 'medium', 'high', 'max'] as const;

  readonly models: readonly ModelDescriptor[] = [
    {
      id: 'claude-opus-5',
      label: 'Claude Opus 5',
      providerId: 'anthropic',
      contextWindow: 1_000_000,
      maxOutputTokens: 128_000,
      supportsTools: true,
    },
    {
      id: 'claude-sonnet-5',
      label: 'Claude Sonnet 5',
      providerId: 'anthropic',
      contextWindow: 1_000_000,
      maxOutputTokens: 128_000,
      supportsTools: true,
    },
    {
      id: 'claude-opus-4-8',
      label: 'Claude Opus 4.8',
      providerId: 'anthropic',
      contextWindow: 1_000_000,
      maxOutputTokens: 128_000,
      supportsTools: true,
    },
    {
      id: 'claude-haiku-4-5',
      label: 'Claude Haiku 4.5',
      providerId: 'anthropic',
      contextWindow: 200_000,
      maxOutputTokens: 64_000,
      supportsTools: true,
    },
  ];

  private client: Promise<Anthropic> | null = null;
  private clientKey: string | null = null;

  /**
   * The requested tier if this adapter declares it, else the model's default.
   *
   * A tier this adapter never declared is *dropped*, not forwarded: the SDK
   * types `effort` as a closed union and the API rejects anything outside it,
   * so forwarding a stale or foreign spelling (`minimal`, which Gemini has and
   * Anthropic does not) would turn a configuration choice into a failed run.
   * The editor already filters the picker to `reasoningEffortLevels`; this is
   * the same rule enforced where the request is actually built, because a
   * document saved before a catalogue change can still carry the old value.
   */
  private effortFor(request: CompletionRequest): 'low' | 'medium' | 'high' | 'max' {
    const wanted = request.effort;
    const declared = this.reasoningEffortLevels;
    return wanted && (declared as readonly string[]).includes(wanted)
      ? (wanted as 'low' | 'medium' | 'high' | 'max')
      : 'high';
  }

  async complete(request: CompletionRequest): Promise<Result<CompletionResult, string>> {
    if (!this.hasApiKey()) return Err('Add an Anthropic API key to run this model');

    const { system, messages } = this.splitSystem(request);
    // Reasoning is on by default on the current models; only turn it off
    // when the budget genuinely cannot accommodate it.
    const thinkingEnabled = request.maxTokens >= THINKING_FLOOR;

    const systemPrompt = thinkingEnabled
      ? system
      : [system, NO_THINKING_GUARDRAILS].filter(Boolean).join('\n\n');

    try {
      const client = await this.clientFor();
      const response = await client.messages.create(
        {
          model: request.model,
          max_tokens: request.maxTokens,
          // Sampling parameters are rejected on the current models — depth
          // is controlled through effort, not temperature.
          output_config: { effort: this.effortFor(request) },
          thinking: thinkingEnabled ? { type: 'adaptive' } : { type: 'disabled' },
          ...(systemPrompt ? { system: systemPrompt } : {}),
          ...(request.tools && request.tools.length > 0
            ? {
                tools: request.tools.map((tool) => ({
                  name: tool.name,
                  description: tool.description,
                  input_schema: tool.parameters,
                })),
              }
            : {}),
          messages: this.toAnthropicMessages(messages),
        },
        { signal: request.signal },
      );

      const usage = {
        inputTokens: response.usage.input_tokens,
        outputTokens: response.usage.output_tokens,
        totalTokens: response.usage.input_tokens + response.usage.output_tokens,
        ...(response.usage.cache_read_input_tokens != null
          ? { cachedTokens: response.usage.cache_read_input_tokens }
          : {}),
      };

      // Safety classifiers can decline a request and still return 200 with
      // an empty content array — check the stop reason before reading it.
      if (response.stop_reason === 'refusal') {
        return Err(
          `Anthropic declined this request${
            response.stop_details?.category ? ` (${response.stop_details.category})` : ''
          }`,
        );
      }

      let text = '';
      let reasoning = '';
      const toolCalls: ToolCall[] = [];

      for (const block of response.content) {
        switch (block.type) {
          case 'text':
            text += block.text;
            break;
          case 'thinking':
            reasoning += block.thinking;
            break;
          case 'tool_use':
            toolCalls.push({
              id: block.id,
              name: block.name,
              // The SDK exposes `input` already parsed — never re-parse or
              // string-match the serialized form, whose escaping varies.
              arguments: (block.input ?? {}) as Record<string, unknown>,
            });
            break;
          default:
            break;
        }
      }

      return Ok({
        text,
        toolCalls,
        usage,
        stopReason: mapStopReason(response.stop_reason),
        ...(reasoning ? { reasoning } : {}),
      });
    } catch (error) {
      return Err(this.describeError(error));
    }
  }

  /** True when the current budget forces reasoning off. */
  thinkingDisabledAt(maxTokens: number): boolean {
    return maxTokens < THINKING_FLOOR;
  }

  /**
   * Loads the SDK on first use and caches the client per key.
   *
   * Cached so a run doesn't construct a client per node, keyed so a changed
   * credential takes effect immediately, and dynamically imported so the
   * vendor bundle stays out of the initial page load.
   */
  private clientFor(): Promise<Anthropic> {
    if (!this.client || this.clientKey !== this.apiKey) {
      this.clientKey = this.apiKey;
      const apiKey = this.apiKey ?? '';
      const baseUrl = this.baseUrl;
      this.client = import('@anthropic-ai/sdk').then(
        ({ default: AnthropicSDK }) =>
          new AnthropicSDK({
            apiKey,
            ...(baseUrl ? { baseURL: baseUrl } : {}),
            // The key lives in this browser session only. Phase 2 moves
            // inference behind the LangGraph backend, which removes the need
            // for direct browser access entirely.
            dangerouslyAllowBrowser: true,
            maxRetries: 2,
          }),
      );
    }
    return this.client;
  }

  /**
   * Maps neutral messages onto Anthropic's shape.
   *
   * Tool results must arrive as `tool_result` blocks in a *user* turn, and
   * consecutive same-role turns are merged, since the API expects the
   * conversation to read as alternating turns.
   */
  private toAnthropicMessages(messages: readonly LLMMessage[]): Anthropic.MessageParam[] {
    const result: Anthropic.MessageParam[] = [];

    for (const message of messages) {
      if (message.role === 'tool') {
        const block: Anthropic.ToolResultBlockParam = {
          type: 'tool_result',
          tool_use_id: message.toolCallId ?? '',
          content: message.content,
        };
        const last = result.at(-1);
        if (last?.role === 'user' && Array.isArray(last.content)) {
          last.content.push(block);
        } else {
          result.push({ role: 'user', content: [block] });
        }
        continue;
      }

      const role: 'user' | 'assistant' = message.role === 'assistant' ? 'assistant' : 'user';

      const blocks: Anthropic.ContentBlockParam[] = [];
      if (message.content.trim().length > 0) {
        blocks.push({ type: 'text', text: message.content });
      }
      // Replay the assistant's tool calls as tool_use blocks so the
      // tool_result blocks in the following turn have something to pair with.
      for (const call of message.toolCalls ?? []) {
        blocks.push({
          type: 'tool_use',
          id: call.id,
          name: call.name,
          input: call.arguments,
        });
      }
      if (blocks.length === 0) continue;

      const last = result.at(-1);
      if (last?.role === role && Array.isArray(last.content)) {
        last.content.push(...blocks);
      } else {
        result.push({ role, content: blocks });
      }
    }

    return result;
  }
}

function mapStopReason(reason: string | null): StopReason {
  switch (reason) {
    case 'tool_use':
      return 'tool_use';
    case 'max_tokens':
      return 'max_tokens';
    case 'refusal':
      return 'refusal';
    default:
      return 'end_turn';
  }
}
