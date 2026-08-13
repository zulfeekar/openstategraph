import { describe, expect, it } from 'vitest';
import { OllamaProvider } from './OllamaProvider';

/**
 * Two ways to be configured, and they coexist — providers-and-credentials
 * ticket 02, mirroring the backend's
 * `env_vars=("OLLAMA_API_KEY", "OLLAMA_HOST")`.
 *
 * This provider used to declare `requiresApiKey = false`, so the inherited
 * `isConfigured` returned `true` unconditionally. That was not keyless, it was
 * **ambient**: the cloud was reached through a local daemon holding its own
 * credentials. The visible cost was a credentials dialog with nowhere to type
 * `OLLAMA_API_KEY`, while the onboarding hint told people to add it there.
 */
describe('OllamaProvider is configured by a key or by a host', () => {
  it('is not configured with neither', () => {
    expect(new OllamaProvider().isConfigured()).toBe(false);
  });

  it('is configured by an API key alone — the cloud', () => {
    const provider = new OllamaProvider();
    provider.setApiKey('sk-ollama');
    expect(provider.isConfigured()).toBe(true);
  });

  it('is configured by a host alone — a daemon you run needs no key of ours', () => {
    const provider = new OllamaProvider();
    provider.setBaseUrl('http://localhost:11434');
    expect(provider.isConfigured()).toBe(true);
  });

  it('a blank key or host does not count as either', () => {
    const provider = new OllamaProvider();
    provider.setApiKey('   ');
    provider.setBaseUrl('  ');
    expect(provider.isConfigured()).toBe(false);
  });

  it('declares a key requirement, so the dialog renders the key field', () => {
    // The dialog gates the API-key field on `requiresApiKey`. While this was
    // false there was no way to see an Ollama key in the UI at all.
    expect(new OllamaProvider().requiresApiKey).toBe(true);
    expect(new OllamaProvider().configurableEndpoint).toBe(true);
  });

  it('is no longer labelled as local', () => {
    // It read "Ollama · Local" while the standing rule is that Ollama means
    // cloud, and while the default host was in fact localhost.
    expect(new OllamaProvider().label).toBe('Ollama');
  });
});

describe('the default endpoint is the cloud, not localhost', () => {
  const hostOf = (provider: OllamaProvider): string =>
    (provider as unknown as { host: string }).host;

  it('defaults to ollama.com', () => {
    expect(hostOf(new OllamaProvider())).toBe('https://ollama.com');
  });

  it('a named host wins, so running your own daemon still works', () => {
    const provider = new OllamaProvider();
    provider.setBaseUrl('http://localhost:11434');
    expect(hostOf(provider)).toBe('http://localhost:11434');
  });

  it('sends the key as a bearer token, and sends no header without one', () => {
    // With the cloud as the default host, a request with no Authorization
    // header is a 401 — the key stopped being optional the moment the
    // default stopped being a local daemon.
    const headersOf = (provider: OllamaProvider): Record<string, string> =>
      (provider as unknown as { headers: Record<string, string> }).headers;

    expect(headersOf(new OllamaProvider())).toEqual({});

    const keyed = new OllamaProvider();
    keyed.setApiKey('sk-ollama');
    expect(headersOf(keyed)).toEqual({ authorization: 'Bearer sk-ollama' });
  });
});
