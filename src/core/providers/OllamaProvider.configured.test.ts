import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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

/**
 * A browser cannot call Ollama cloud, and the code has to know that.
 *
 * Found in the console while verifying production-ready ticket 02:
 *
 *     Access to fetch at 'https://ollama.com/api/tags' from origin
 *     'http://localhost:5273' has been blocked by CORS policy
 *
 * Structural, not a misconfiguration — `ollama.com` sends no
 * `Access-Control-*` headers and 405s the preflight, so no setting on either
 * side makes it work. A regression from moving `DEFAULT_HOST` to the cloud:
 * the previous localhost default was reachable from a browser once the daemon
 * was started with `OLLAMA_ORIGINS="*"`.
 *
 * The backend path is unaffected — a server has no origin — which is exactly
 * what the failure message has to say.
 */
describe('the canvas preview knows it cannot reach the cloud', () => {
  const fetchCalls: string[] = [];

  beforeEach(() => {
    fetchCalls.length = 0;
    vi.stubGlobal('fetch', (url: string) => {
      fetchCalls.push(String(url));
      return Promise.reject(new TypeError('Failed to fetch'));
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not call the cloud at all when listing models', async () => {
    // A request that can only ever fail is not a fallback, it is a console
    // error on every page load.
    await new OllamaProvider().listModels();
    expect(fetchCalls).toEqual([]);
  });

  it('still enumerates a daemon you named', async () => {
    const provider = new OllamaProvider();
    provider.setBaseUrl('http://localhost:11434');
    await provider.listModels();
    expect(fetchCalls).toEqual(['http://localhost:11434/api/tags']);
  });

  it('offers cloud models, not local ones, when defaulting to the cloud', async () => {
    // The seed was llama3.2/qwen2.5/mistral/gemma2 — four *local* names for a
    // provider whose standing rule is that Ollama means cloud.
    const models = await new OllamaProvider().listModels();
    expect(models.length).toBeGreaterThan(0);
    for (const model of models) {
      expect(model.id).toContain('cloud');
    }
  });

  it('says why a cloud completion cannot work, and where it can', async () => {
    const result = await new OllamaProvider().complete({
      model: 'gpt-oss:120b-cloud',
      messages: [{ role: 'user', content: 'hi' }],
    } as never);

    expect(result.ok).toBe(false);
    const message = String((result as { error: string }).error);
    // Not "check your connection": nothing about the connection is wrong.
    expect(message).toMatch(/browser/i);
    expect(message).toMatch(/backend|Run/);
    expect(message).not.toMatch(/OLLAMA_ORIGINS/);
  });

  it('still tells a daemon user about OLLAMA_ORIGINS', async () => {
    const provider = new OllamaProvider();
    provider.setBaseUrl('http://localhost:11434');

    const result = await provider.complete({
      model: 'llama3.2',
      messages: [{ role: 'user', content: 'hi' }],
    } as never);

    expect(result.ok).toBe(false);
    expect(String((result as { error: string }).error)).toContain('OLLAMA_ORIGINS');
  });
});
