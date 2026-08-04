// Type-only, with the implementation dynamically imported on first use —
// see `clientFor`. Keeps the vendor bundle off the initial page load.
import type OpenAI from 'openai';
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
 * OpenAI adapter.
 *
 * The seed model list is only a starting point — `listModels` replaces it
 * from the account's own `/v1/models` once a key is present, and the agent
 * node also accepts a free-text model id. Hardcoding a model catalogue is
 * how an LLM integration goes stale; letting the account be the source of
 * truth means new models work the day they ship.
 */
export class OpenAIProvider extends AbstractLLMProvider {
  readonly id = 'openai';
  readonly label = 'OpenAI';
  readonly requiresApiKey = true;
  override readonly credentialsHint = 'platform.openai.com → API keys';
  override readonly allowsCustomModel = true;

  private discovered: readonly ModelDescriptor[] | null = null;

  private readonly seed: readonly ModelDescriptor[] = [
    'gpt-4.1',
    'gpt-4.1-mini',
    'gpt-4o',
    'gpt-4o-mini',
  ].map((id) => ({
    id,
    label: id,
    providerId: 'openai',
    contextWindow: 128_000,
    maxOutputTokens: 16_384,
    supportsTools: true,
  }));

  get models(): readonly ModelDescriptor[] {
    return this.discovered ?? this.seed;
  }

  /** Replaces the seed list with the models this key can actually reach. */
  async listModels(): Promise<readonly ModelDescriptor[]> {
    if (!this.hasApiKey()) return this.seed;
    try {
      const client = await this.clientFor();
      const page = await client.models.list();
      const chatModels = page.data
        // The list includes embeddings, audio and moderation models; keep
        // the GPT/o-series families that can serve a chat completion.
        .filter((model) => /^(gpt|o\d|chatgpt)/i.test(model.id))
        .map((model) => ({
          id: model.id,
          label: model.id,
          providerId: 'openai',
          contextWindow: 128_000,
          maxOutputTokens: 16_384,
          supportsTools: true,
        }))
        .sort((a, b) => a.id.localeCompare(b.id));
      if (chatModels.length > 0) this.discovered = chatModels;
      return this.models;
    } catch {
      // Discovery is a convenience; a failure must not block a run.
      return this.seed;
    }
  }

  async complete(request: CompletionRequest): Promise<Result<CompletionResult, string>> {
    if (!this.hasApiKey()) return Err('Add an OpenAI API key to run this model');

    try {
      const client = await this.clientFor();
      const response = await client.chat.completions.create(
        {
          model: request.model,
          max_completion_tokens: request.maxTokens,
          messages: this.toOpenAIMessages(request),
          ...(request.tools && request.tools.length > 0
            ? {
                tools: request.tools.map((tool) => ({
                  type: 'function' as const,
                  function: {
                    name: tool.name,
                    description: tool.description,
                    parameters: tool.parameters,
                  },
                })),
              }
            : {}),
        },
        { signal: request.signal },
      );

      const choice = response.choices[0];
      if (!choice) return Err('OpenAI returned no choices');

      const toolCalls: ToolCall[] = (choice.message.tool_calls ?? [])
        .filter((call): call is typeof call & { type: 'function' } => call.type === 'function')
        .map((call) => ({
          id: call.id,
          name: call.function.name,
          // Arguments arrive as a JSON *string* here, unlike Anthropic's
          // pre-parsed object. A malformed payload becomes an empty object
          // so the tool can report a useful error instead of the run dying.
          arguments: safeParse(call.function.arguments),
        }));

      return Ok({
        text: choice.message.content ?? '',
        toolCalls,
        usage: {
          inputTokens: response.usage?.prompt_tokens ?? 0,
          outputTokens: response.usage?.completion_tokens ?? 0,
          totalTokens: response.usage?.total_tokens ?? 0,
          ...(response.usage?.prompt_tokens_details?.cached_tokens != null
            ? { cachedTokens: response.usage.prompt_tokens_details.cached_tokens }
            : {}),
        },
        stopReason: mapFinishReason(choice.finish_reason),
      });
    } catch (error) {
      return Err(this.describeError(error));
    }
  }

  private client: Promise<OpenAI> | null = null;
  private clientKey: string | null = null;

  /** Loads the SDK on first use; cached per key. */
  private clientFor(): Promise<OpenAI> {
    if (!this.client || this.clientKey !== this.apiKey) {
      this.clientKey = this.apiKey;
      const apiKey = this.apiKey ?? '';
      const baseUrl = this.baseUrl;
      this.client = import('openai').then(
        ({ default: OpenAISDK }) =>
          new OpenAISDK({
            apiKey,
            ...(baseUrl ? { baseURL: baseUrl } : {}),
            dangerouslyAllowBrowser: true,
            maxRetries: 2,
          }),
      );
    }
    return this.client;
  }

  private toOpenAIMessages(
    request: CompletionRequest,
  ): OpenAI.Chat.Completions.ChatCompletionMessageParam[] {
    const messages: OpenAI.Chat.Completions.ChatCompletionMessageParam[] = [];
    // OpenAI keeps the system prompt inline as the first message, so the
    // split here is only used to hoist it to the front.
    const { system, messages: rest } = this.splitSystem(request);
    if (system) messages.push({ role: 'system', content: system });

    for (const message of rest) {
      messages.push(toOpenAIMessage(message));
    }
    return messages;
  }
}

function toOpenAIMessage(
  message: LLMMessage,
): OpenAI.Chat.Completions.ChatCompletionMessageParam {
  switch (message.role) {
    case 'tool':
      return {
        role: 'tool',
        tool_call_id: message.toolCallId ?? '',
        content: message.content,
      };
    case 'assistant':
      return {
        role: 'assistant',
        content: message.content,
        // Echoed back so the following `tool` messages have a call to
        // attach to; OpenAI rejects an orphaned tool_call_id.
        ...(message.toolCalls && message.toolCalls.length > 0
          ? {
              tool_calls: message.toolCalls.map((call) => ({
                id: call.id,
                type: 'function' as const,
                function: {
                  name: call.name,
                  arguments: JSON.stringify(call.arguments),
                },
              })),
            }
          : {}),
      };
    default:
      return { role: 'user', content: message.content };
  }
}

function mapFinishReason(reason: string | null): StopReason {
  switch (reason) {
    case 'tool_calls':
    case 'function_call':
      return 'tool_use';
    case 'length':
      return 'max_tokens';
    case 'content_filter':
      return 'refusal';
    default:
      return 'end_turn';
  }
}

function safeParse(json: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(json) as unknown;
    return typeof parsed === 'object' && parsed !== null
      ? (parsed as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}
