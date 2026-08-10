import { Registry } from '@core/kernel/Registry';
import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import type { FieldOption } from '@core/model/contracts/fields';
import { AbstractLLMProvider, type ILLMProvider, type ModelDescriptor } from './ILLMProvider';

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
  readonly providers = new Registry<ILLMProvider>('llmProviders');
  private readonly bus = new EventBus<ProviderEvents>();

  constructor(private readonly credentials: CredentialStore) {}

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

  /** Every model across every provider, in registration order. */
  allModels(): readonly ModelDescriptor[] {
    return this.providers.list().flatMap((provider) => provider.models);
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
    const separator = selection.indexOf('/');
    if (separator > 0) {
      const providerId = selection.slice(0, separator);
      const modelId = selection.slice(separator + 1);
      const provider = this.providers.get(providerId);
      if (provider && modelId) return { provider, modelId };
    }
    // Tolerate a bare model id from an older document.
    const owner = this.providers
      .list()
      .find((provider) => provider.models.some((model) => model.id === selection));
    return owner ? { provider: owner, modelId: selection } : undefined;
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
   * Options for the agent node's model field, grouped by provider and
   * annotated so an unconfigured model is visibly unavailable rather than
   * failing only once the workflow is run.
   */
  modelOptions(): readonly FieldOption[] {
    return this.providers.list().flatMap((provider) =>
      provider.models.map((model) => ({
        value: ProviderRegistry.selectionFor(provider.id, model.id),
        label: provider.isConfigured() ? model.label : `${model.label} · needs key`,
        group: provider.label,
      })),
    );
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
