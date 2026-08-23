import type { ProviderStatus, ProviderStatusList } from '@core/runtime/RuntimeClient';

/**
 * Whether a model can actually run — the **one** answer three canvas surfaces
 * used to guess at separately.
 *
 * The defect it exists for (providers-and-credentials 06): on a server with
 * `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `OLLAMA_API_KEY` set, the editor
 * said "workflows run against mock data until you do" in its first sentence,
 * suffixed every model in the picker with `· needs key`, and told the Agent
 * card its reasoning was `Not supported by Mock · Offline` — while the
 * credentials dialog two clicks away said `ready` for all three. All four
 * surfaces were right about their own source and only the dialog's source was
 * the server, because the other three read the **browser's** key store, which
 * is now preview-only and cannot even be typed into.
 *
 * So this holds what the *server* said and every readiness label reads it.
 * Same seam as `mcpServerCatalogue` and `workflowCatalogue`, for the same
 * reason: a node field's `options` is a synchronous function called during a
 * render, while `/api/health` and `/api/providers` arrive over HTTP.
 *
 * **Three answers, not two, and the third is the point.** "The server has not
 * told us" is not "the server has no key". A label that accuses a provider of
 * missing a key on no evidence is exactly the bug; `unknown` says nothing, and
 * saying nothing is the honest option when the browser cannot know.
 */
export type ModelReadiness = 'ready' | 'needs key' | 'unknown';

type Listener = () => void;

export class ServerReadiness {
  /** `/api/health`'s `model_configured`, or `null` before it answers. */
  private configuredSomewhere: boolean | null = null;

  /** Provider ids `/api/providers` called configured, or `null` before it answers. */
  private configuredProviders: ReadonlySet<string> | null = null;

  /**
   * `/api/providers`'s `run_readiness` — `ProviderCatalogue.elected_default().reason`
   * in the server's own words, or `null` before it answers.
   *
   * providers-and-credentials/14: this is the one place the editor holds that
   * sentence, so a component that wants to say what a run will do reads it
   * here rather than composing its own claim. Two components used to do
   * exactly that — "workflows run against mock data" — on a server whose own
   * `serve` banner already said every run would fail.
   */
  private runReadinessNote: string | null = null;

  private readonly listeners = new Set<Listener>();

  /** Whether the server can resolve a model at all, or `null` if unasked. */
  modelConfigured(): boolean | null {
    return this.configuredSomewhere;
  }

  /**
   * What the editor may say about one provider.
   *
   * `browserHasKey` is passed in rather than read, so this stays ignorant of
   * `ProviderRegistry` and `CredentialStore` — the registry is what knows its
   * own providers, and this is what knows the server.
   *
   * The `unknown` branch is the whole fix. `/api/providers` is behind auth and
   * is only fetched when something asks; until it answers, `model_configured`
   * proves *a* provider is ready without naming which. That is enough to
   * withdraw the accusation and not enough to make the opposite claim.
   */
  readinessOf(providerId: string, browserHasKey: boolean): ModelReadiness {
    if (browserHasKey) return 'ready';
    if (this.configuredProviders) {
      return this.configuredProviders.has(providerId) ? 'ready' : 'needs key';
    }
    if (this.configuredSomewhere === true) return 'unknown';
    return 'needs key';
  }

  /** Records `/api/health`. Notifies only on a real change. */
  recordHealth(modelConfigured: boolean): void {
    if (this.configuredSomewhere === modelConfigured) return;
    this.configuredSomewhere = modelConfigured;
    this.announce();
  }

  /** What the server said a run will do right now, or `null` before it answers. */
  runReadiness(): string | null {
    return this.runReadinessNote;
  }

  /**
   * Records `/api/providers`.
   *
   * Also settles `model_configured`, because the list is the stronger answer:
   * a provider row saying `configured: true` is the same fact health reports,
   * with the name attached. Without this the two could disagree for one poll.
   *
   * `runReadiness` is optional so every existing call site — most of them in
   * tests that do not care about the sentence — keeps compiling; a caller
   * that omits it simply leaves the note unpublished, same as before this
   * field existed.
   */
  recordProviders(statuses: readonly ProviderStatus[], runReadiness?: string): void {
    const next = new Set(statuses.filter((status) => status.configured).map((s) => s.name));
    const same =
      this.configuredProviders !== null &&
      this.configuredProviders.size === next.size &&
      [...next].every((name) => this.configuredProviders?.has(name)) &&
      this.runReadinessNote === (runReadiness ?? this.runReadinessNote);
    const anyConfigured = next.size > 0;
    if (same && this.configuredSomewhere === anyConfigured) return;
    this.configuredProviders = next;
    this.configuredSomewhere = anyConfigured;
    if (runReadiness !== undefined) this.runReadinessNote = runReadiness;
    this.announce();
  }

  onChange(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Forgets what it was told. For tests, so one file's server is not another's. */
  reset(): void {
    this.configuredSomewhere = null;
    this.configuredProviders = null;
    this.runReadinessNote = null;
  }

  private announce(): void {
    for (const listener of this.listeners) listener();
  }
}

/**
 * The one readiness answer the editor reads.
 *
 * A module singleton for the reason `mcpServerCatalogue` is one: node
 * definitions are data assembled at import time, so `ProviderRegistry` cannot
 * be handed this through a React tree. `probeServerReadiness` is the only
 * writer in the app, so "the server answered" and "the labels know" cannot
 * drift.
 */
export const serverReadiness = new ServerReadiness();

/** The two calls that answer "can this install run a model?", in one place. */
export interface ReadinessSource {
  health(): Promise<{ ok: boolean; value?: { readonly modelConfigured: boolean } }>;
  providers(): Promise<{ ok: boolean; value?: ProviderStatusList }>;
}

/**
 * Asks the server and publishes the answer. Returns whether it is reachable,
 * which is what the health dot renders.
 *
 * Both calls, not just health: `model_configured` alone can only withdraw the
 * `· needs key` accusation, and the provider list is what lets a genuinely
 * unconfigured vendor still be labelled. `/api/providers` is behind auth and
 * may refuse; that leaves the `unknown` branch, which is a correct outcome
 * rather than a failure to handle.
 */
export async function probeServerReadiness(
  client: ReadinessSource,
  store: ServerReadiness = serverReadiness,
): Promise<boolean> {
  const health = await client.health();
  if (!health.ok) return false;
  if (health.value) store.recordHealth(health.value.modelConfigured);
  const listed = await client.providers();
  if (listed.ok && listed.value)
    store.recordProviders(listed.value.rows, listed.value.runReadiness);
  return true;
}
