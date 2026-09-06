import { describe, expect, it } from 'vitest';
import { CredentialStore, ProviderRegistry, redactApiKey } from './ProviderRegistry';
import { AnthropicProvider } from './AnthropicProvider';
import { OllamaProvider } from './OllamaProvider';

/**
 * A stored key is never shown, and never handed to the view (ticket 04).
 *
 * The old dialog put the raw key into `<TextInput value={…}>`, so the secret
 * was in the DOM, in React's state, and one devtools panel away — and it was
 * re-fillable, which meant a mistyped paste silently replaced a working key.
 * `describeApiKey` is the fix, and it is a *registry* method rather than a
 * formatting helper in the view on purpose: the view can no longer obtain the
 * raw value even if someone later writes the code to display it.
 */
describe('redactApiKey', () => {
  it('shows a hint of the head and the last four, never the middle', () => {
    expect(redactApiKey('sk-ant-api03-abcdefghijklmnop9WxZ')).toBe('sk-…9WxZ');
  });

  it('reveals nothing at all from a short key', () => {
    // Revealing 7 of 8 characters is not redaction.
    expect(redactApiKey('sk-12345')).toBe('••••');
    expect(redactApiKey('abc')).toBe('••••');
  });

  it('is empty for no key', () => {
    expect(redactApiKey(null)).toBe('');
    expect(redactApiKey('')).toBe('');
    expect(redactApiKey('   ')).toBe('');
  });

  it('never contains the original key', () => {
    const key = 'sk-ant-api03-supersecretvalue1234';
    const redacted = redactApiKey(key);
    expect(redacted).not.toContain('supersecret');
    expect(key).not.toBe(redacted);
  });
});

describe('the dialog can only ever obtain a redacted key', () => {
  function registry(): ProviderRegistry {
    return new ProviderRegistry(new CredentialStore(false))
      .register(new AnthropicProvider())
      .register(new OllamaProvider());
  }

  it('describes a stored key without disclosing it', () => {
    const providers = registry();
    providers.setApiKey('anthropic', 'sk-ant-api03-abcdefghijklmnop9WxZ');

    expect(providers.describeApiKey('anthropic')).toBe('sk-…9WxZ');
  });

  it('returns null when there is no key, so the view can disable its input', () => {
    expect(registry().describeApiKey('anthropic')).toBeNull();
  });

  it('returns null for a provider that does not exist', () => {
    expect(registry().describeApiKey('nope')).toBeNull();
  });

  it('goes back to null once the key is forgotten', () => {
    const providers = registry();
    providers.setApiKey('anthropic', 'sk-ant-api03-abcdefghijklmnop9WxZ');
    providers.setApiKey('anthropic', null);

    expect(providers.describeApiKey('anthropic')).toBeNull();
    expect(providers.get('anthropic')?.isConfigured()).toBe(false);
  });

  it('still forwards the real key to a backend run', () => {
    // Redaction is a *display* boundary, not a storage one — the run path
    // must keep working or the dialog would be honest and useless.
    const providers = registry();
    providers.setApiKey('anthropic', 'sk-ant-real');
    expect(providers.getApiKey('anthropic')).toBe('sk-ant-real');
  });
});

describe('the view cannot reach a raw key', () => {
  it('CredentialsDialog never calls getApiKey', async () => {
    // A source assertion, not a rendering one: this repo has no React test
    // harness, and the property worth protecting is structural anyway. The
    // dialog rendered `value={getApiKey(...)}` before ticket 04, putting the
    // secret in the DOM and in React state. If that call ever comes back,
    // this fails in the same pull request rather than in a screenshot review.
    const source = await import('fs/promises').then((fs) =>
      fs.readFile(new URL('../../view/overlays/CredentialsDialog.tsx', import.meta.url), 'utf8'),
    );
    expect(source).not.toContain('getApiKey');
    expect(source).toContain('describeApiKey');
    // …and no vendor literal, which is ticket 02's half of the same file.
    expect(source).not.toContain('instanceof OllamaProvider');
  });

  it('the disabled input points at .env, and names the file that lists it', async () => {
    const source = await import('fs/promises').then((fs) =>
      fs.readFile(new URL('../../view/overlays/CredentialsDialog.tsx', import.meta.url), 'utf8'),
    );
    expect(source).toContain('key in .env');
    expect(source).toContain('.env.example');
    expect(source).toContain('disabled');
  });
});
