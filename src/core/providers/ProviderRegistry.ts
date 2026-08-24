import { Registry } from '@core/kernel/Registry';
import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import type { FieldOption } from '@core/model/contracts/fields';
import {
  AbstractLLMProvider,
  type ILLMProvider,
  type ModelDescriptor,
  type ReasoningEffortLevels,
} from './ILLMProvider';
import { MOCK_SELECTION, workflowModelAsSelection } from './modelSelection';
import { serverReadiness } from './serverReadiness';

const STORAGE_PREFIX = 'openstategraph.credentials.';

interface ProviderEvents extends Record<string, unknown> {
  changed: { providerId: string };
}

/**
 * A stored key, in a form that is safe to render.
 *
 * Enough to answer "is the right key in there?" — the head tells you which
 * vendor and which key format, the last four tell you which of your keys it
 * is — and nothing that helps anyone use it.
 *
 * A key of eight characters or fewer is shown as bullets only: revealing
 * seven of eight characters is not redaction, and a real key is never that
 * short, so the case only arises for a typo or a placeholder.
 */
export function redactApiKey(key: string | null | undefined): string {
  const trimmed = key?.trim() ?? '';
  if (!trimmed) return '';
  if (trimmed.length <= 8) return '••••';
  return `${trimmed.slice(0, 3)}…${trimmed.slice(-4)}`;
}

/**
 * Credential storage.
 *
 * Deliberately narrow and deliberately explicit about its limits: keys are
 * held in `localStorage`, which is readable by any script on this origin.
 * That is an acceptable trade for a local-first editor whose alternative is
 * "retype your key every reload", and it disappears in phase 2 when the
 * LangGraph backend holds credentials server-side.
 *
 * `session` mode keeps the key in memory only, for users who would rather
 * not persist it at all.
 */
export class CredentialStore {
  private readonly memory = new Map<string, string>();

  constructor(private readonly persist: boolean = true) {}

  get(providerId: string): string | null {
    const inMemory = this.memory.get(providerId);
    if (inMemory) return inMemory;
    if (!this.persist) return null;
    try {
      return window.localStorage.getItem(STORAGE_PREFIX + providerId);
    } catch {
      // Private browsing / disabled storage — memory-only is the fallback.
      return null;
    }
  }

  set(providerId: string, key: string | null): void {
    if (!key) {
      this.memory.delete(providerId);
      this.clearPersisted(providerId);
      return;
    }
    this.memory.set(providerId, key);
    if (!this.persist) return;
    try {
      window.localStorage.setItem(STORAGE_PREFIX + providerId, key);
    } catch {
      // Keep the in-memory copy; the session still works.
    }
  }

  clear(): void {
    for (const providerId of this.memory.keys()) this.clearPersisted(providerId);
    this.memory.clear();
  }

  private clearPersisted(providerId: string): void {
    try {
      window.localStorage.removeItem(STORAGE_PREFIX + providerId);
    } catch {
      /* nothing to clear */
    }
  }
}

/**
 * The set of available providers plus their credentials.
 *
 * Adding a vendor is `registry.register(new MyProvider())` — the agent
 * node's model picker, the credentials dialog and the executor all read
 * from here, so none of them needs a per-vendor branch.
 */
export class ProviderRegistry {
  /**
   * The inner registry. **Private**: every consumer goes through this class's
   * own `register`/`get`/`list`, and exposing it leaked a second, credential-
   * unaware way to reach the same providers (install-experience 21).
   */
  private readonly providers = new Registry<ILLMProvider>('llmProviders');
  private readonly bus = new EventBus<ProviderEvents>();

  /**
   * What an **empty** selection stands for — the open document's model.
   *
   * A node left on "Workflow default" stores `''`, which is exactly what the
   * backend's `_resolve_model` treats as "no override". The editor had no
   * equivalent: `''` was translated to the offline simulator at each call
   * site, so anything asking the registry about such a node was answered
   * about Mock. The reasoning picker made that visible — "Not supported by
   * Mock · Offline" on every card of a document running
   * `ollama:gpt-oss:120b-cloud` — but the picker was only the messenger.
   *
   * The simulator remains the answer when no document names a model, because
   * that is what the canvas preview would actually run.
   */
  private workflowDefault = MOCK_SELECTION;

  constructor(private readonly credentials: CredentialStore) {
    // `onChange` promises "what this registry reports has changed", and since
    // `modelOptions` and `reasoningEffortLevelsFor` read `serverReadiness`,
    // the server answering is such a change. Without this the labels are
    // whatever they were at first paint: verified in a browser, where the
    // hint vanished on the poll that reported a configured server and every
    // model in the picker kept its "· needs key" from a second earlier.
    serverReadiness.onChange(() => this.bus.emit('changed', { providerId: '*' }));
  }

  /**
   * Tells the registry which model the open document runs.
   *
   * Takes the **settings** spelling (`ollama:gpt-oss:120b-cloud`) and
   * normalises it, so the one caller — the composition root, listening to
   * `workflow:settings` — hands over `settings.model` unchanged rather than
   * remembering that the two formats differ. Blank restores the simulator.
   */
  setWorkflowDefaultModel(settingsModel: string): void {
    const trimmed = settingsModel.trim();
    this.workflowDefault = trimmed ? workflowModelAsSelection(trimmed) : MOCK_SELECTION;
    this.bus.emit('changed', { providerId: '*' });
  }

  /**
   * Adds a vendor. This is the **only** path in — there is no built-in list
   * here, and `Workbench` is a composition root rather than a privileged one.
   *
   * Callable at any time, not just during startup: the change event is what
   * makes that true in practice, because the model picker and the credentials
   * dialog both re-render from `onChange`. Without it a provider registered
   * after the first paint existed in the registry and nowhere a user could
   * see it.
   */
  register(provider: ILLMProvider): this {
    this.providers.register(provider);
    // Re-apply any stored key so a reload comes back configured.
    if (provider instanceof AbstractLLMProvider) {
      provider.setApiKey(this.credentials.get(provider.id));
    }
    this.bus.emit('changed', { providerId: provider.id });
    return this;
  }

  get(providerId: string): ILLMProvider | undefined {
    return this.providers.get(providerId);
  }

  list(): readonly ILLMProvider[] {
    return this.providers.list();
  }

  /**
   * Parses a model selection.
   *
   * Selections are stored as `providerId/modelId` rather than a bare model
   * id: it disambiguates the same model served by two providers, and it
   * keeps a free-text custom model id resolvable — a bare id would have
   * nowhere to look up which vendor to call.
   */
  resolve(selection: string): { provider: ILLMProvider; modelId: string } | undefined {
    // An empty selection is not an unknown one: it is "whatever this
    // document runs", and only the registry can say what that is.
    const wanted = selection.trim() ? selection : this.workflowDefault;
    const separator = wanted.indexOf('/');
    if (separator > 0) {
      const providerId = wanted.slice(0, separator);
      const modelId = wanted.slice(separator + 1);
      const provider = this.providers.get(providerId);
      if (provider && modelId) return { provider, modelId };
    }
    // Tolerate a bare model id from an older document.
    const owner = this.providers
      .list()
      .find((provider) => provider.models.some((model) => model.id === wanted));
    return owner ? { provider: owner, modelId: wanted } : undefined;
  }

  /** Canonical selection string for a provider/model pair. */
  static selectionFor(providerId: string, modelId: string): string {
    return `${providerId}/${modelId}`;
  }

  model(selection: string): ModelDescriptor | undefined {
    const resolved = this.resolve(selection);
    if (!resolved) return undefined;
    return resolved.provider.models.find((model) => model.id === resolved.modelId);
  }

  /**
   * Reasoning tiers a selection accepts — model first, then its provider.
   *
   * Most specific source wins, and `undefined` propagates rather than being
   * flattened to "none": a model that says nothing about itself inherits its
   * adapter's answer, and an adapter that says nothing leaves the question
   * genuinely open for the runtime to settle. An *unresolvable* selection —
   * a custom model id typed into a provider that allows one, a document
   * naming a vendor that is no longer registered — is also `undefined`, for
   * the same reason: not knowing is not the same as knowing there is none.
   */
  reasoningEffortLevelsFor(selection: string): ReasoningEffortLevels {
    // A node on "Workflow default" in a document that names no model: the
    // **server** resolves the model, and this editor cannot name it. Falling
    // through to the simulator here is what put "Not supported by Mock ·
    // Offline" on every card of an install running `ollama:gpt-oss:120b-cloud`
    // (providers-and-credentials 06). `undefined` is the answer this method
    // already reserves for "not known", and the picker already renders it as
    // the common tiers rather than a refusal.
    if (
      !selection.trim() &&
      this.workflowDefault === MOCK_SELECTION &&
      serverReadiness.modelConfigured() === true
    ) {
      return undefined;
    }
    const resolved = this.resolve(selection);
    if (!resolved) return undefined;
    const model = resolved.provider.models.find((entry) => entry.id === resolved.modelId);
    return model?.reasoningEffortLevels ?? resolved.provider.reasoningEffortLevels;
  }

  /**
   * Options for the agent node's model field, grouped by provider and
   * annotated so an unconfigured model is visibly unavailable rather than
   * failing only once the workflow is run.
   */
  modelOptions(): readonly FieldOption[] {
    return this.providers.list().flatMap((provider) => {
      // A missing **package** and a missing **credential** are different
      // walls (launch-readiness/28): a key can still be typed into the
      // credentials dialog from the browser, but no browser action fixes an
      // `ImportError` on the server. So a package gap is shown disabled and
      // named — "do not filter them out silently", the ticket's own words —
      // while a bare missing key stays selectable, exactly as before.
      const packageGap = serverReadiness.packageGapOf(provider.id);
      return provider.models.map((model) => {
        if (packageGap) {
          const extra = serverReadiness.packageExtraOf(provider.id) ?? provider.id;
          return {
            value: ProviderRegistry.selectionFor(provider.id, model.id),
            label: `${model.label} · needs openstategraph[${extra}]`,
            group: provider.label,
            disabled: true,
          };
        }
        return {
          value: ProviderRegistry.selectionFor(provider.id, model.id),
          // `provider.isConfigured()` is the **browser's** key store, which is
          // preview-only and can no longer even be typed into. Asking it alone
          // suffixed every model with "· needs key" on a server with three
          // working keys (providers-and-credentials 06). `serverReadiness` is
          // the one resolver the hint and the reasoning row read too, so the
          // three cannot disagree again — and it answers `unknown`, which
          // labels nothing, rather than guessing.
          label:
            serverReadiness.readinessOf(provider.id, provider.isConfigured()) === 'needs key'
              ? `${model.label} · needs key`
              : model.label,
          group: provider.label,
        };
      });
    });
  }

  setApiKey(providerId: string, key: string | null): void {
    const provider = this.providers.get(providerId);
    if (!(provider instanceof AbstractLLMProvider)) return;
    provider.setApiKey(key);
    this.credentials.set(providerId, key);
    this.bus.emit('changed', { providerId });
  }

  /**
   * The real key, for the run path only.
   *
   * `collectRuntimeCredentials` needs it to forward to a backend run. The
   * **view must not call this** — it calls `describeApiKey`, which cannot
   * disclose anything.
   */
  getApiKey(providerId: string): string | null {
    return this.credentials.get(providerId);
  }

  /**
   * A stored key as the credentials dialog is allowed to see it, or `null`.
   *
   * A registry method rather than a formatter in the view, deliberately: with
   * this here, the dialog has no path to the raw value at all. Formatting in
   * the view would have left `getApiKey` one autocomplete away from putting
   * the secret back on screen.
   */
  describeApiKey(providerId: string): string | null {
    const redacted = redactApiKey(this.credentials.get(providerId));
    return redacted || null;
  }

  setBaseUrl(providerId: string, url: string | null): void {
    const provider = this.providers.get(providerId);
    if (!(provider instanceof AbstractLLMProvider)) return;
    provider.setBaseUrl(url);
    this.bus.emit('changed', { providerId });
  }

  /**
   * Refreshes the catalogue of every provider that can enumerate its own
   * models. Failures are swallowed per provider — one unreachable endpoint
   * must not blank the picker.
   */
  async refreshModels(): Promise<void> {
    await Promise.all(
      this.providers.list().map(async (provider) => {
        try {
          await provider.listModels?.();
        } catch {
          /* keep the seed list */
        }
      }),
    );
    this.bus.emit('changed', { providerId: '*' });
  }

  onChange(handler: () => void): Unsubscribe {
    return this.bus.on('changed', handler);
  }
}
