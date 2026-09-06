import type { ProviderRegistry } from '@core/providers/ProviderRegistry';

/**
 * The browser-held provider keys, in the shape a backend run understands.
 *
 * "Models and credentials" is meant to be the *one* home for keys, but a key
 * pasted there used to reach only the in-browser preview: backend runs
 * resolved models from the server's own `.env`, so Chat still reported "no
 * model configured" right after a developer had configured one. This closes
 * that gap by sending the keys along with the run.
 *
 * Built entirely from the registry — each provider names its own environment
 * variable (`ILLMProvider.runtimeCredentialKey`), so a newly registered vendor
 * is forwarded with no change here. A provider with no key set, or none
 * declared, simply contributes nothing.
 *
 * The backend treats these as a **fallback**: an environment variable already
 * set server-side wins, so a shared deployment can never be repointed by a
 * browser. Returns `undefined` rather than `{}` when there is nothing to send,
 * so the request body simply omits the field.
 */
export function collectRuntimeCredentials(
  registry: ProviderRegistry,
): Record<string, string> | undefined {
  const credentials: Record<string, string> = {};
  for (const provider of registry.list()) {
    const name = provider.runtimeCredentialKey;
    if (!name) continue;
    const key = registry.getApiKey(provider.id)?.trim();
    if (key) credentials[name] = key;
  }
  return Object.keys(credentials).length > 0 ? credentials : undefined;
}
