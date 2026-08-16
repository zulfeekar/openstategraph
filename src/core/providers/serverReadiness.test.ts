import { describe, expect, it, vi } from 'vitest';
import type { ProviderStatus } from '@core/runtime/RuntimeClient';
import {
  ServerReadiness,
  probeServerReadiness,
  serverReadiness,
} from '@core/providers/serverReadiness';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { AbstractLLMProvider, type ModelDescriptor } from '@core/providers/ILLMProvider';
import { effortOptionsFor } from '../../nodes/effortField';
import { MODEL_FIELD_KEY } from '../../nodes/modelField';

function status(name: string, configured: boolean): ProviderStatus {
  return { name, label: name, configured, configuredBy: null, envVars: [], keyHint: null };
}

class StubProvider extends AbstractLLMProvider {
  readonly requiresApiKey = true;
  readonly models: readonly ModelDescriptor[];

  constructor(
    readonly id: string,
    readonly label: string,
    modelId: string,
    modelLabel: string,
    levels: readonly string[] = ['low', 'high'],
  ) {
    super();
    this.models = [
      {
        id: modelId,
        providerId: id,
        label: modelLabel,
        contextWindow: 1000,
        maxOutputTokens: 100,
        supportsTools: false,
        reasoningEffortLevels: levels,
      },
    ];
  }

  async complete(): Promise<never> {
    throw new Error('not used');
  }
}

describe('ServerReadiness', () => {
  it('says nothing about a provider before the server has answered', () => {
    expect(new ServerReadiness().modelConfigured()).toBeNull();
  });

  it('trusts a key this browser holds without asking anyone', () => {
    expect(new ServerReadiness().readinessOf('anthropic', true)).toBe('ready');
  });

  it('calls a provider ready when the server named it configured', () => {
    const readiness = new ServerReadiness();
    readiness.recordProviders([status('anthropic', true), status('gemini', false)]);

    expect(readiness.readinessOf('anthropic', false)).toBe('ready');
  });

  it('still says "needs key" for a provider the server listed as unconfigured', () => {
    const readiness = new ServerReadiness();
    readiness.recordProviders([status('anthropic', true), status('gemini', false)]);

    expect(readiness.readinessOf('gemini', false)).toBe('needs key');
  });

  it('withdraws the accusation — but does not invent a key — when only health has answered', () => {
    // `/api/providers` is behind auth and may never answer. `model_configured`
    // proves *a* provider is ready without naming which, which is enough to
    // stop accusing and not enough to claim the opposite.
    const readiness = new ServerReadiness();
    readiness.recordHealth(true);

    expect(readiness.readinessOf('anthropic', false)).toBe('unknown');
  });

  it('falls back to the browser when the server has nothing configured', () => {
    const readiness = new ServerReadiness();
    readiness.recordHealth(false);

    expect(readiness.readinessOf('anthropic', false)).toBe('needs key');
  });

  it('notifies once per real change and not on a repeat of the same answer', () => {
    const readiness = new ServerReadiness();
    const listener = vi.fn();
    readiness.onChange(listener);

    readiness.recordProviders([status('anthropic', true)]);
    readiness.recordProviders([status('anthropic', true)]);

    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe('probeServerReadiness', () => {
  it('publishes both answers and reports the runtime reachable', async () => {
    const store = new ServerReadiness();

    const reachable = await probeServerReadiness(
      {
        health: async () => ({ ok: true, value: { modelConfigured: true } }),
        providers: async () => ({ ok: true, value: [status('ollama', true)] }),
      },
      store,
    );

    expect(reachable).toBe(true);
    expect(store.readinessOf('ollama', false)).toBe('ready');
  });

  it('reports unreachable and records nothing when health fails', async () => {
    const store = new ServerReadiness();

    const reachable = await probeServerReadiness(
      {
        health: async () => ({ ok: false }),
        providers: async () => {
          throw new Error('must not be asked');
        },
      },
      store,
    );

    expect(reachable).toBe(false);
    expect(store.modelConfigured()).toBeNull();
  });

  it('keeps health when the provider list is refused by auth', async () => {
    const store = new ServerReadiness();

    await probeServerReadiness(
      {
        health: async () => ({ ok: true, value: { modelConfigured: true } }),
        providers: async () => ({ ok: false }),
      },
      store,
    );

    expect(store.modelConfigured()).toBe(true);
    expect(store.readinessOf('anthropic', false)).toBe('unknown');
  });
});

/**
 * Providers-and-credentials 06: three surfaces judged model readiness from
 * browser-local keys only, and contradicted `/api/health`, `/api/providers`
 * and the credentials dialog on a server where every provider was configured.
 * They read one resolver now, so they are pinned against one health response.
 */
describe('the three surfaces on a configured install', () => {
  const registry = () => {
    const providers = new ProviderRegistry(new CredentialStore(false));
    providers.register(new StubProvider('anthropic', 'Anthropic', 'opus', 'Claude Opus 5'));
    providers.register(new StubProvider('gemini', 'Gemini', 'flash', 'Gemini Flash'));
    // The offline simulator an empty selection falls back to — the model whose
    // name the Reasoning row was putting on every card.
    providers.register(new StubProvider('mock', 'Mock', 'mock-offline', 'Mock · Offline', []));
    return providers;
  };

  it('tells every picker to re-render when the server answers', () => {
    // Found in a browser, not in a test: the hint vanished on the poll that
    // reported a configured server while the picker kept the "· needs key"
    // it had rendered a second earlier, because nothing re-rendered it.
    serverReadiness.reset();
    const listener = vi.fn();
    registry().onChange(listener);

    serverReadiness.recordHealth(true);

    expect(listener).toHaveBeenCalled();
    serverReadiness.reset();
  });

  it('drops "· needs key" from a model the server has a key for', () => {
    serverReadiness.reset();
    serverReadiness.recordProviders([status('anthropic', true), status('gemini', false)]);

    const labels = registry()
      .modelOptions()
      .map((option) => option.label);

    expect(labels).toContain('Claude Opus 5');
    expect(labels).toContain('Gemini Flash · needs key');
    serverReadiness.reset();
  });

  it('says nothing about a key while only health has answered', () => {
    serverReadiness.reset();
    serverReadiness.recordHealth(true);

    const labels = registry()
      .modelOptions()
      .map((option) => option.label);

    expect(labels.some((label) => label.includes('needs key'))).toBe(false);
    serverReadiness.reset();
  });

  it('keeps "· needs key" when the server has nothing either', () => {
    serverReadiness.reset();
    serverReadiness.recordHealth(false);

    const labels = registry()
      .modelOptions()
      .map((option) => option.label);

    expect(labels).toContain('Claude Opus 5 · needs key');
    serverReadiness.reset();
  });

  it('stops telling a "Workflow default" node it runs the offline simulator', () => {
    // The document names no model, so the *server* picks one and this editor
    // cannot say which. Answering about Mock put "Not supported by Mock ·
    // Offline" on the Reasoning row of every card on a configured install.
    serverReadiness.reset();
    serverReadiness.recordHealth(true);

    const labels = effortOptionsFor(registry(), { [MODEL_FIELD_KEY]: '' }).map((o) => o.label);

    expect(labels.some((label) => label.startsWith('Not supported by'))).toBe(false);
    expect(labels).toContain("Model's default");
    serverReadiness.reset();
  });

  it('still names the simulator when nothing is configured anywhere', () => {
    serverReadiness.reset();
    serverReadiness.recordHealth(false);

    const labels = effortOptionsFor(registry(), { [MODEL_FIELD_KEY]: '' }).map((o) => o.label);

    expect(labels).toEqual(['Not supported by Mock · Offline']);
    serverReadiness.reset();
  });
});
