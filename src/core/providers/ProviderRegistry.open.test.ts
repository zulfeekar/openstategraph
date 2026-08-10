import { describe, expect, it, vi } from 'vitest';
import { Ok, type Result } from '@core/kernel/Result';
import { CredentialStore, ProviderRegistry } from './ProviderRegistry';
import {
  AbstractLLMProvider,
  ZERO_USAGE,
  type CompletionRequest,
  type CompletionResult,
  type ModelDescriptor,
} from './ILLMProvider';
import { AnthropicProvider } from './AnthropicProvider';
import { OpenAIProvider } from './OpenAIProvider';
import { OllamaProvider } from './OllamaProvider';
import { collectRuntimeCredentials } from '@core/runtime/providerCredentials';

/**
 * The provider set is open on this side too (ticket 02).
 *
 * The registry was already open in shape — `register()` is a public method
 * and `Workbench` is only its composition root — but two things stopped a
 * fourth vendor from being a *first-class* one: registering after startup
 * fired no change event, so the model picker and credentials dialog never
 * learned about it; and the dialog asked `provider instanceof OllamaProvider`
 * to decide whether to offer an endpoint field, which is a vendor literal no
 * plugin can join.
 *
 * `FakeProvider` here is the fourth vendor. It is defined in the test file on
 * purpose: if it needs nothing from `src/core/providers` beyond the exported
 * interface, then neither does a real plugin.
 */
class FakeProvider extends AbstractLLMProvider {
  readonly id = 'acme';
  readonly label = 'Acme';
  readonly requiresApiKey = true;
  override readonly runtimeCredentialKey = 'ACME_API_KEY';
  override readonly credentialsHint = 'Get a key at acme.example';
  override readonly configurableEndpoint = true;
  readonly models: readonly ModelDescriptor[] = [
    {
      id: 'acme-large',
      label: 'Acme Large',
      providerId: 'acme',
      contextWindow: 128_000,
      maxOutputTokens: 8_192,
      supportsTools: true,
    },
  ];

  async complete(_request: CompletionRequest): Promise<Result<CompletionResult, string>> {
    return Ok({ text: 'ok', toolCalls: [], usage: ZERO_USAGE, stopReason: 'end_turn' });
  }
}

function registry(): ProviderRegistry {
  return new ProviderRegistry(new CredentialStore(false))
    .register(new AnthropicProvider())
    .register(new OpenAIProvider())
    .register(new OllamaProvider());
}

describe('a fourth provider needs no fork', () => {
  it('is registered at runtime, long after construction', () => {
    const providers = registry();
    expect(providers.get('acme')).toBeUndefined();

    providers.register(new FakeProvider());

    expect(providers.get('acme')?.label).toBe('Acme');
    expect(providers.list().map((p) => p.id)).toContain('acme');
  });

  it('reaches the model picker with no change to the picker', () => {
    const providers = registry();
    providers.register(new FakeProvider());

    const options = providers.modelOptions();
    const acme = options.find((option) => option.value === 'acme/acme-large');
    expect(acme).toBeDefined();
    // Unconfigured providers are annotated, not hidden — the same treatment
    // the built-ins get, from the same code path.
    expect(acme?.label).toBe('Acme Large · needs key');
    expect(acme?.group).toBe('Acme');
  });

  it('resolves a selection to itself', () => {
    const providers = registry();
    providers.register(new FakeProvider());

    const resolved = providers.resolve('acme/acme-large');
    expect(resolved?.provider.id).toBe('acme');
    expect(resolved?.modelId).toBe('acme-large');
  });

  it('has its key forwarded to a backend run under its own env var', () => {
    const providers = registry();
    providers.register(new FakeProvider());
    providers.setApiKey('acme', 'acme-secret');

    expect(collectRuntimeCredentials(providers)).toEqual({ ACME_API_KEY: 'acme-secret' });
  });

  it('notifies subscribers when it registers, so the UI learns about it', () => {
    const providers = registry();
    const handler = vi.fn();
    providers.onChange(handler);

    providers.register(new FakeProvider());

    expect(handler).toHaveBeenCalled();
  });
});

describe('no consumer needs a vendor literal', () => {
  it('the endpoint field is a declared capability, not an instanceof', () => {
    const providers = registry();
    providers.register(new FakeProvider());

    // Ollama declares it, so the dialog stops asking `instanceof
    // OllamaProvider`; a plugin declares it the same way and gets the field.
    expect(providers.get('ollama')?.configurableEndpoint).toBe(true);
    expect(providers.get('acme')?.configurableEndpoint).toBe(true);
    expect(providers.get('anthropic')?.configurableEndpoint ?? false).toBe(false);
  });

  it('accepts a base url for any provider that declares one', () => {
    const providers = registry();
    const acme = new FakeProvider();
    providers.register(acme);

    providers.setBaseUrl('acme', 'https://acme.internal');

    expect(providers.get('acme')).toBe(acme);
  });
});

describe('three providers coexist', () => {
  it('each keeps its own key and its own models', () => {
    const providers = registry();
    providers.setApiKey('anthropic', 'sk-ant-1');
    providers.setApiKey('openai', 'sk-oai-2');
    providers.setApiKey('ollama', 'oll-3');

    expect(providers.get('anthropic')?.isConfigured()).toBe(true);
    expect(providers.get('openai')?.isConfigured()).toBe(true);

    expect(collectRuntimeCredentials(providers)).toEqual({
      ANTHROPIC_API_KEY: 'sk-ant-1',
      OPENAI_API_KEY: 'sk-oai-2',
      OLLAMA_API_KEY: 'oll-3',
    });
  });

  it('a per-node selection names the provider, so two nodes reach two vendors', () => {
    const providers = registry();

    const first = providers.resolve('anthropic/claude-haiku-4-5');
    const second = providers.resolve('openai/gpt-4.1-mini');

    expect(first?.provider.id).toBe('anthropic');
    expect(second?.provider.id).toBe('openai');
    // The selection string is what a node's `model` field stores, and it is
    // what the backend splits on `/` to build `provider:model`.
    expect(ProviderRegistry.selectionFor('acme', 'acme-large')).toBe('acme/acme-large');
  });
});
