import { describe, expect, it } from 'vitest';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { AnthropicProvider } from '@core/providers/AnthropicProvider';
import { OpenAIProvider } from '@core/providers/OpenAIProvider';
import { MockProvider } from '@core/providers/MockProvider';
import { collectRuntimeCredentials } from './providerCredentials';

function registry(): ProviderRegistry {
  // Memory-only store: no localStorage, so this runs under node like the rest.
  return new ProviderRegistry(new CredentialStore(false))
    .register(new AnthropicProvider())
    .register(new OpenAIProvider())
    .register(new MockProvider());
}

describe('collectRuntimeCredentials', () => {
  it('is undefined when no key is stored, so the request omits the field', () => {
    expect(collectRuntimeCredentials(registry())).toBeUndefined();
  });

  it('keys the stored values by the backend environment-variable name', () => {
    const providers = registry();
    providers.setApiKey('anthropic', 'sk-ant-test');
    expect(collectRuntimeCredentials(providers)).toEqual({ ANTHROPIC_API_KEY: 'sk-ant-test' });
  });

  it('includes every configured provider that declares a variable', () => {
    const providers = registry();
    providers.setApiKey('anthropic', 'sk-ant-test');
    providers.setApiKey('openai', 'sk-oai-test');
    expect(collectRuntimeCredentials(providers)).toEqual({
      ANTHROPIC_API_KEY: 'sk-ant-test',
      OPENAI_API_KEY: 'sk-oai-test',
    });
  });

  it('skips a provider with no variable declared — the mock has nothing to forward', () => {
    const providers = registry();
    providers.setApiKey('mock', 'irrelevant');
    expect(collectRuntimeCredentials(providers)).toBeUndefined();
  });

  it('forgets a cleared key', () => {
    const providers = registry();
    providers.setApiKey('anthropic', 'sk-ant-test');
    providers.setApiKey('anthropic', null);
    expect(collectRuntimeCredentials(providers)).toBeUndefined();
  });
});
