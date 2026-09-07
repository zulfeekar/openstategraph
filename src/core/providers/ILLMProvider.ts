import type { IIdentifiable } from '@core/kernel/Registry';
import type { Result } from '@core/kernel/Result';

/* ================================================================== *
 * Wire types — provider-neutral.
 *
 * Every concrete adapter translates between these and its vendor's
 * shape. Nothing above this layer knows which vendor is in play, which
 * is what lets phase 2 swap in a LangGraph/LangChain backend provider
 * without touching the executors or the UI.
 * ================================================================== */

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool';

export interface LLMMessage {
  readonly role: MessageRole;
  readonly content: string;
  /** Set on `tool` messages to pair a result with its call. */
  readonly toolCallId?: string;
  /** Tool name, for providers that key results by name rather than id. */
  readonly name?: string;
  /**
   * Tool calls the assistant made on this turn.
   *
   * Required for a multi-turn tool loop, not decorative: Anthropic rejects a
   * `tool_result` that has no matching `tool_use` earlier in the
   * conversation, so replaying an assistant turn as plain text would break
   * the second iteration of every agent run.
   */
  readonly toolCalls?: readonly ToolCall[];
}

/**
 * JSON Schema subset used for tool parameters.
 *
 * Mutable arrays and an open index signature on purpose: both vendor SDKs
 * type their schema parameter as a mutable, open-ended object, and a
 * `readonly` shape here would force a cast at every call site.
 */
export interface JSONSchema {
  type: 'object';
  properties: Record<string, unknown>;
  required?: string[];
  additionalProperties?: boolean;
  [key: string]: unknown;
}

export interface ToolSpec {
  readonly name: string;
  readonly description: string;
  readonly parameters: JSONSchema;
}

export interface ToolCall {
  readonly id: string;
  readonly name: string;
  readonly arguments: Record<string, unknown>;
}

export interface TokenUsage {
  readonly inputTokens: number;
  readonly outputTokens: number;
  readonly totalTokens: number;
  /** Cached prompt tokens, where the provider reports them. */
  readonly cachedTokens?: number;
}

export const ZERO_USAGE: TokenUsage = { inputTokens: 0, outputTokens: 0, totalTokens: 0 };

export function addUsage(a: TokenUsage, b: TokenUsage): TokenUsage {
  return {
    inputTokens: a.inputTokens + b.inputTokens,
    outputTokens: a.outputTokens + b.outputTokens,
    totalTokens: a.totalTokens + b.totalTokens,
    ...(a.cachedTokens != null || b.cachedTokens != null
      ? { cachedTokens: (a.cachedTokens ?? 0) + (b.cachedTokens ?? 0) }
      : {}),
  };
}

export type StopReason = 'end_turn' | 'tool_use' | 'max_tokens' | 'refusal' | 'error';

/**
 * How hard a model should think before answering. A provider's own spelling.
 *
 * A string rather than a union — see `CompletionRequest.effort`. The set of
 * valid values for any given call comes from `reasoningEffortLevels`, which is
 * declared by the provider that will receive it.
 */
export type ReasoningEffort = string;

/**
 * Tiers a model or a provider accepts, in the three states that actually
 * exist.
 *
 * The three-way distinction is the feature, not a nicety. Collapsing it to a
 * boolean forces one of two lies: an unknown model is either promised a
 * control that will be dropped, or refused one that would have worked.
 *
 * - a non-empty array — these tiers, and only these.
 * - `[]` — this model does not reason. Certain.
 * - `undefined` — **not known here.** The runtime decides, and says what it
 *   decided (`openstategraph/reasoning.py`).
 */
export type ReasoningEffortLevels = readonly ReasoningEffort[] | undefined;

export interface CompletionRequest {
  readonly model: string;
  readonly messages: readonly LLMMessage[];
  /** Extracted from the message list by adapters whose API separates it. */
  readonly system?: string;
  readonly tools?: readonly ToolSpec[];
  readonly maxTokens: number;
  /**
   * Reasoning depth, mapped per provider. Deliberately not `temperature`:
   * the current Claude models reject sampling parameters outright, so the
   * neutral surface exposes the control that all providers can honour.
   *
   * Not a closed union, because the tiers are the *provider's* vocabulary and
   * they genuinely differ — Anthropic publishes `max` and `xhigh` that OpenAI
   * has never had, Gemini publishes `minimal` that Anthropic rejects with a
   * validation error. A union here would be this repo hand-mirroring a list
   * that has a real source (`ILLMProvider.reasoningEffortLevels`), which
   * CLAUDE.md forbids, and would go stale on the next model release.
   */
  readonly effort?: ReasoningEffort;
  readonly signal?: AbortSignal;
}

export interface CompletionResult {
  readonly text: string;
  readonly toolCalls: readonly ToolCall[];
  readonly usage: TokenUsage;
  readonly stopReason: StopReason;
  /** Reasoning summary, when the provider returns one. */
  readonly reasoning?: string;
}

/** Model exposed by a provider, used to build the agent node's picker. */
export interface ModelDescriptor {
  readonly id: string;
  readonly label: string;
  readonly providerId: string;
  readonly contextWindow: number;
  readonly maxOutputTokens: number;
  readonly supportsTools: boolean;
  /**
   * Reasoning tiers **this model** accepts, where the provider knows them per
   * model. Omitted falls back to the provider's own declaration — most
   * catalogues are discovered at runtime (`listModels`) and know nothing more
   * about a freshly pulled id than its name.
   */
  readonly reasoningEffortLevels?: ReasoningEffortLevels;
}

/* ================================================================== *
 * The abstraction
 * ================================================================== */

export interface ILLMProvider extends IIdentifiable {
  readonly id: string;
  readonly label: string;
  readonly models: readonly ModelDescriptor[];
  /**
   * False for offline providers such as Mock.
   *
   * Ollama was here too until it turned out not to be keyless but *ambient* —
   * it borrowed a local daemon's own cloud credentials. A provider reachable
   * more than one way declares `true` and overrides `isConfigured`; see
   * `OllamaProvider`.
   */
  readonly requiresApiKey: boolean;
  /** Where to get a key, surfaced in the credentials dialog. */
  readonly credentialsHint?: string;

  /**
   * The environment variable this provider's key is called on the backend,
   * e.g. `ANTHROPIC_API_KEY`.
   *
   * Declared **by the provider**, so "Models and credentials" becomes the one
   * home for keys across both runtimes without the editor learning a
   * per-vendor mapping: a newly registered vendor names its own variable and
   * a backend run picks it up with no change anywhere else. Absent means "do
   * not forward" — the mock provider, for one.
   */
  readonly runtimeCredentialKey?: string;

  /**
   * Whether the agent node should offer a free-text model id.
   *
   * True for providers whose catalogue moves faster than this code can
   * track it — a new model must be usable without a release here.
   */
  readonly allowsCustomModel?: boolean;

  /**
   * Whether this provider is reached at a caller-chosen endpoint, and so
   * should be offered a base-url field in "Models and credentials".
   *
   * A *declared capability* rather than a check the dialog performs, because
   * the dialog used to ask `provider instanceof OllamaProvider` — a vendor
   * literal no third party could ever join, so a self-hosted or proxied
   * fourth provider had nowhere to put its host. Ollama declares it; anyone
   * else may.
   */
  readonly configurableEndpoint?: boolean;

  /**
   * Reasoning tiers **this adapter can transmit**, for models that reason.
   *
   * A declared capability of the adapter, not of the vendor: it answers "if I
   * put an effort on a request to you, will it reach the model", which is a
   * question only the code that builds the request can answer. Anthropic's
   * adapter sends `output_config.effort` and so declares its four; an adapter
   * that has no place to put the value declares `[]` and the editor stops
   * offering a control that reaches nothing.
   *
   * `undefined` means the adapter does not say — the tiers are offered and
   * the *runtime* is left to decide, loudly.
   */
  readonly reasoningEffortLevels?: ReasoningEffortLevels;

  /** True when the provider can actually be called right now. */
  isConfigured(): boolean;

  /**
   * Replaces the static model list with the account's real one.
   * Optional: offline providers have a fixed catalogue.
   */
  listModels?(): Promise<readonly ModelDescriptor[]>;

  /**
   * One turn of completion.
   *
   * Returns a `Result` rather than throwing: a bad key, a rate limit or a
   * refusal are all expected outcomes that the run log needs to render,
   * not exceptions that should unwind the scheduler.
   */
  complete(request: CompletionRequest): Promise<Result<CompletionResult, string>>;
}

/**
 * Shared behaviour for concrete providers.
 *
 * Holds the credential wiring and the error normalisation that every HTTP
 * adapter would otherwise duplicate — subclasses implement only the
 * vendor-specific request translation.
 */
export abstract class AbstractLLMProvider implements ILLMProvider {
  abstract readonly id: string;
  abstract readonly label: string;
  abstract readonly models: readonly ModelDescriptor[];
  abstract readonly requiresApiKey: boolean;
  readonly credentialsHint?: string;
  readonly allowsCustomModel?: boolean;
  readonly configurableEndpoint?: boolean;
  readonly runtimeCredentialKey?: string;
  readonly reasoningEffortLevels?: ReasoningEffortLevels;

  protected apiKey: string | null = null;
  /** Overridable endpoint — lets Ollama point at a non-default host. */
  protected baseUrl: string | null = null;

  setApiKey(key: string | null): void {
    this.apiKey = key?.trim() || null;
  }

  setBaseUrl(url: string | null): void {
    this.baseUrl = url?.trim() || null;
  }

  hasApiKey(): boolean {
    return this.apiKey != null && this.apiKey.length > 0;
  }

  isConfigured(): boolean {
    return !this.requiresApiKey || this.hasApiKey();
  }

  abstract complete(request: CompletionRequest): Promise<Result<CompletionResult, string>>;

  /**
   * Turns an unknown throw into a message a user can act on.
   *
   * Browser-direct calls fail in a small number of recognisable ways, and
   * "Failed to fetch" tells nobody anything — CORS and a missing local
   * server look identical to `fetch` but need completely different fixes.
   */
  protected describeError(error: unknown): string {
    if (error instanceof Error) {
      const status = (error as { status?: number }).status;
      if (status === 401) return `${this.label} rejected the API key`;
      if (status === 403) return `${this.label} denied access — check the key's permissions`;
      if (status === 404) return `${this.label} has no such model`;
      if (status === 429) return `${this.label} rate limit hit — retry shortly`;
      if (status != null && status >= 500) return `${this.label} is unavailable (${status})`;
      if (error.name === 'AbortError') return 'Run cancelled';
      if (error.message.includes('Failed to fetch')) {
        return `Couldn't reach ${this.label}. Check the endpoint is running and allows browser requests.`;
      }
      return error.message;
    }
    return String(error);
  }

  /** Splits a message list into the leading system prompt and the rest. */
  protected splitSystem(request: CompletionRequest): {
    system: string | undefined;
    messages: readonly LLMMessage[];
  } {
    const explicit = request.system?.trim();
    const systemParts = request.messages
      .filter((message) => message.role === 'system')
      .map((message) => message.content.trim())
      .filter(Boolean);
    if (explicit) systemParts.unshift(explicit);
    return {
      system: systemParts.length > 0 ? systemParts.join('\n\n') : undefined,
      messages: request.messages.filter((message) => message.role !== 'system'),
    };
  }
}
