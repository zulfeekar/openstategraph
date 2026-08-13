import { Err, Ok, type Result } from '@core/kernel/Result';
import {
  AbstractLLMProvider,
  type CompletionRequest,
  type CompletionResult,
  type ModelDescriptor,
  type StopReason,
  type ToolCall,
} from './ILLMProvider';

/**
 * Ollama cloud — the default, matching the backend's `default_endpoint`.
 *
 * This used to be `http://localhost:11434`, which quietly made the preview a
 * *local* provider while the project's standing rule is that Ollama means
 * cloud. A developer running their own daemon still gets it by naming the host
 * in "Models and credentials" — one explicit act rather than a default.
 */
const DEFAULT_HOST = 'https://ollama.com';

/* ---- Ollama wire types (only the fields we consume) ---- */

interface OllamaToolCall {
  function: { name: string; arguments: Record<string, unknown> };
}

interface OllamaChatResponse {
  message?: { content?: string; tool_calls?: OllamaToolCall[]; thinking?: string };
  done_reason?: string;
  prompt_eval_count?: number;
  eval_count?: number;
}

interface OllamaTagsResponse {
  models?: { name: string; model?: string; details?: { parameter_size?: string } }[];
}

/**
 * Ollama — cloud by default, or a daemon you name.
 *
 * **Two ways to be configured, and they coexist**, mirroring the backend's
 * `env_vars=("OLLAMA_API_KEY", "OLLAMA_HOST")`: an API key reaches the cloud,
 * a base URL reaches a daemon you run. Either is enough, which is why
 * `isConfigured` is overridden below.
 *
 * This used to declare `requiresApiKey = false` and so was *always* reported
 * as configured. That was not keyless, it was **ambient**: the cloud was
 * reached through a local daemon holding its own credentials. It also left the
 * credentials dialog with no field to type `OLLAMA_API_KEY` into, while the
 * onboarding hint told people to add their Ollama cloud key there.
 *
 * A daemon you run still has to allow browser origins. Ollama rejects
 * cross-origin requests by default, and the failure is indistinguishable from
 * "not running" at the `fetch` level, so the error path below names both
 * causes and the exact fix.
 *
 * Uses `fetch` rather than an SDK deliberately: the two endpoints needed here
 * are trivial, and this keeps the bundle light for users who never touch it.
 */
export class OllamaProvider extends AbstractLLMProvider {
  readonly id = 'ollama';
  readonly label = 'Ollama';
  readonly requiresApiKey = true;
  override readonly credentialsHint =
    'An API key from ollama.com, or the address of a daemon you run ' +
    '(started with OLLAMA_ORIGINS="*" so the browser can reach it)';
  override readonly allowsCustomModel = true;
  // The host is the caller's choice, so the credentials dialog offers a
  // base-url field. Declared here rather than detected there — see
  // `ILLMProvider.configurableEndpoint`.
  override readonly configurableEndpoint = true;
  override readonly runtimeCredentialKey = 'OLLAMA_API_KEY';

  /**
   * Either signal is enough — a key for the cloud, or a host of your own.
   *
   * The inherited rule is `!requiresApiKey || hasApiKey()`, which cannot
   * express "or a host". Ollama is the only provider reachable two ways, so
   * this is an override rather than a change to the base: a vendor with one
   * way to be configured should keep the simpler rule.
   */
  override isConfigured(): boolean {
    return this.hasApiKey() || this.baseUrl != null;
  }

  private discovered: readonly ModelDescriptor[] | null = null;

  /** Common local tags, replaced by whatever is actually pulled. */
  private readonly seed: readonly ModelDescriptor[] = [
    'llama3.2',
    'qwen2.5',
    'mistral',
    'gemma2',
  ].map((id) => ({
    id,
    label: id,
    providerId: 'ollama',
    contextWindow: 32_768,
    maxOutputTokens: 8_192,
    supportsTools: true,
  }));

  get models(): readonly ModelDescriptor[] {
    return this.discovered ?? this.seed;
  }

  private get host(): string {
    return (this.baseUrl ?? DEFAULT_HOST).replace(/\/$/, '');
  }

  /**
   * `Authorization: Bearer` when a key is held, nothing when it is not.
   *
   * The same header the `ollama` client sends, and the reason the key matters
   * now: with the cloud as the default host, a request without it is a 401. A
   * daemon you run typically wants no header at all, so an absent key sends
   * none rather than an empty one.
   */
  private get headers(): Record<string, string> {
    return this.hasApiKey() ? { authorization: `Bearer ${this.apiKey ?? ''}` } : {};
  }

  /**
   * Reads the available models from `/api/tags`, **cloud first**.
   *
   * Ollama lists locally pulled models and cloud-hosted ones together, and the
   * distinction matters more than it looks: a local `llama3.1:8b` could not hold
   * structured output at all here, took minutes per run, and answered a database
   * question from parametric knowledge. The same workflow on a `-cloud` model
   * wrote correct SQL in 23 seconds.
   *
   * So cloud models are sorted to the top and labelled, and local ones are marked
   * as such rather than silently offered as equals. A developer can still pick a
   * local model — it just should not be the easy accident.
   */
  async listModels(): Promise<readonly ModelDescriptor[]> {
    try {
      const response = await fetch(`${this.host}/api/tags`, { headers: this.headers });
      if (!response.ok) return this.seed;
      const payload = (await response.json()) as OllamaTagsResponse;
      const found = (payload.models ?? []).map((model) => {
        const cloud = model.name.endsWith('-cloud') || model.name.includes(':cloud');
        const size = model.details?.parameter_size;
        return {
          id: model.name,
          label: cloud
            ? `${model.name} · cloud${size ? ` · ${size}` : ''}`
            : `${model.name}${size ? ` · ${size}` : ''} · local`,
          providerId: 'ollama',
          contextWindow: 32_768,
          maxOutputTokens: 8_192,
          supportsTools: true,
          cloud,
        };
      });
      // Stable: cloud before local, then alphabetical, so the ordering does not
      // shift between reads and the first option is always a capable one.
      const sorted = [...found].sort(
        (a, b) => Number(b.cloud) - Number(a.cloud) || a.id.localeCompare(b.id),
      );
      if (sorted.length > 0) {
        this.discovered = sorted.map(({ cloud: _cloud, ...rest }) => rest);
      }
      return this.models;
    } catch {
      return this.seed;
    }
  }

  /** True when the daemon answers — used by the credentials dialog. */
  async probe(): Promise<boolean> {
    try {
      const response = await fetch(`${this.host}/api/tags`, { headers: this.headers });
      return response.ok;
    } catch {
      return false;
    }
  }

  async complete(request: CompletionRequest): Promise<Result<CompletionResult, string>> {
    const { system, messages } = this.splitSystem(request);

    const body = {
      model: request.model,
      stream: false,
      options: { num_predict: request.maxTokens },
      // Ollama spells reasoning depth `think`, and it takes a level string on
      // the models that have one. Omitted unless a tier was chosen — sending
      // `think` to a model with no thinking is an error, not a no-op.
      //
      // Worth stating that this is the *browser preview* path. A run through
      // the backend goes to `ChatOllama`, which has no `reasoning_effort`
      // parameter at all and would silently drop the value; that is handled
      // where it happens, in `openstategraph/reasoning.py`, and reported.
      ...(request.effort ? { think: request.effort } : {}),
      messages: [
        ...(system ? [{ role: 'system', content: system }] : []),
        ...messages.map((message) => ({
          // Ollama has no dedicated tool role in its chat history; a result
          // is fed back as a tool-authored message keyed by name.
          role: message.role === 'tool' ? 'tool' : message.role,
          content: message.content,
          ...(message.name ? { name: message.name } : {}),
        })),
      ],
      ...(request.tools && request.tools.length > 0
        ? {
            tools: request.tools.map((tool) => ({
              type: 'function',
              function: {
                name: tool.name,
                description: tool.description,
                parameters: tool.parameters,
              },
            })),
          }
        : {}),
    };

    try {
      const response = await fetch(`${this.host}/api/chat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', ...this.headers },
        body: JSON.stringify(body),
        ...(request.signal ? { signal: request.signal } : {}),
      });

      if (!response.ok) {
        const detail = await response.text().catch(() => '');
        if (response.status === 404) {
          return Err(
            `Ollama has no model "${request.model}" — pull it first: ollama pull ${request.model}`,
          );
        }
        return Err(`Ollama returned ${response.status}${detail ? `: ${truncate(detail)}` : ''}`);
      }

      const payload = (await response.json()) as OllamaChatResponse;

      const toolCalls: ToolCall[] = (payload.message?.tool_calls ?? []).map((call, index) => ({
        // Ollama does not mint call ids; synthesise stable ones so the
        // tool-result pairing works the same as with the other providers.
        id: `ollama-call-${index}`,
        name: call.function.name,
        arguments: call.function.arguments ?? {},
      }));

      const inputTokens = payload.prompt_eval_count ?? 0;
      const outputTokens = payload.eval_count ?? 0;

      return Ok({
        text: payload.message?.content ?? '',
        toolCalls,
        usage: { inputTokens, outputTokens, totalTokens: inputTokens + outputTokens },
        stopReason: mapDoneReason(payload.done_reason, toolCalls.length > 0),
        ...(payload.message?.thinking ? { reasoning: payload.message.thinking } : {}),
      });
    } catch (error) {
      if (error instanceof Error && error.message.includes('Failed to fetch')) {
        // Two different fixes behind one indistinguishable `fetch` failure, so
        // name the one that matches the host actually in use rather than
        // offering both and making the reader choose.
        return Err(
          this.baseUrl == null
            ? `Couldn't reach Ollama cloud at ${this.host}. Check your connection, or set a host in Models and credentials to use your own daemon.`
            : `Couldn't reach Ollama at ${this.host}. Start it with OLLAMA_ORIGINS="*" to allow browser requests.`,
        );
      }
      return Err(this.describeError(error));
    }
  }
}

function mapDoneReason(reason: string | undefined, hasToolCalls: boolean): StopReason {
  if (hasToolCalls) return 'tool_use';
  if (reason === 'length') return 'max_tokens';
  return 'end_turn';
}

function truncate(text: string, max = 160): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}
