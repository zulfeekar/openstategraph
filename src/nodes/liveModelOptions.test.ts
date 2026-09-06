import { afterEach, describe, expect, it, vi } from 'vitest';

import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { OpenAIProvider } from '@core/providers/OpenAIProvider';
import { serverReadiness } from '@core/providers/serverReadiness';
import type { ProviderStatus } from '@core/runtime/RuntimeClient';
import { resolveOptions } from '@core/model/contracts/fields';
import { allNodeDefinitions } from '@nodes/portSpecs';

import { MODEL_FIELD_KEY, modelField } from './modelField';
import { REASONING_EFFORT_FIELD_KEY, effortField } from './effortField';

/**
 * The pickers that read the provider registry follow it.
 *
 * The defect (providers-and-credentials, observed live on a card at
 * `localhost:5273`): `ProviderRegistry` emitted `changed` when the health probe
 * reported a configured server, the onboarding hint — which subscribes
 * directly — updated in that same moment, and the agent card's model `<select>`
 * beside it still read *Claude Opus 5 · needs key*. Nothing re-rendered the
 * card. First paint was correct only because the probe happened to resolve
 * before the workflow loaded, so the staleness was invisible until
 * configuration changed with the editor open — setting or forgetting a key in
 * the credentials dialog had the same effect on any card already on screen.
 *
 * `options` is resolved lazily on every render, so the list was always
 * *computable*; what was missing was anything to tell React the answer had
 * moved. `ComboboxFieldSchema` already had the answer — a field names its own
 * store through `subscribe` (mcp-connect ticket 07) — and a `select` whose
 * options come from a live registry needs exactly the same thing. So the fix is
 * the existing seam applied to the other option-bearing kind, not a card-level
 * subscription: only the fields whose store moved re-render, and the inspector
 * and the note body get it from the same declaration.
 */

function registry(): ProviderRegistry {
  return new ProviderRegistry(new CredentialStore(false)).register(new OpenAIProvider());
}

function status(name: string, configured: boolean): ProviderStatus {
  return {
    name,
    label: name,
    configured,
    configuredBy: null,
    envVars: [],
    installed: true,
    installHint: '',
    extra: '',
    keyHint: null,
    defaultModel: '',
  };
}

const labels = (options: readonly { readonly label: string }[]) =>
  options.map((option) => option.label);

// A module singleton, so one file's server must not become another's.
afterEach(() => serverReadiness.reset());

describe('the model picker follows the provider registry', () => {
  it('names the store its options come from', () => {
    expect(
      modelField(registry()).subscribe,
      'a select whose options read runtime state must say where that state lives, ' +
        'or nothing can re-render it',
    ).toBeTypeOf('function');
  });

  it.each([
    ['a key set in the credentials dialog', (p: ProviderRegistry) => p.setApiKey('openai', 'sk-x')],
    ['a key forgotten', (p: ProviderRegistry) => p.setApiKey('openai', null)],
    ['the workflow default model changing', (p: ProviderRegistry) => p.setWorkflowDefaultModel('')],
    [
      'the server reporting readiness',
      () => serverReadiness.recordProviders([status('openai', true)]),
    ],
  ])('notifies on %s', (_case, change) => {
    const providers = registry();
    const notify = vi.fn();
    const stop = modelField(providers).subscribe?.(notify);

    change(providers);

    expect(notify).toHaveBeenCalled();
    stop?.();
  });

  it('stops notifying once the control unsubscribes', () => {
    const providers = registry();
    const notify = vi.fn();
    modelField(providers).subscribe?.(notify)?.();

    providers.setApiKey('openai', 'sk-x');

    expect(notify).not.toHaveBeenCalled();
  });

  it('drops the "needs key" suffix the notification was announcing', () => {
    // The behaviour behind the notification: subscribing is only useful if the
    // next resolve actually says something different. This is the exact
    // transition seen on the card — every model suffixed `· needs key` while
    // the server held three working keys.
    const field = modelField(registry());
    expect(labels(resolveOptions(field)).some((label) => label.includes('needs key'))).toBe(true);

    serverReadiness.recordProviders([status('openai', true)]);

    expect(labels(resolveOptions(field)).some((label) => label.includes('needs key'))).toBe(false);
  });
});

describe('the reasoning picker follows it too', () => {
  it('names the same store', () => {
    // Its tiers come from `reasoningEffortLevelsFor`, which reads the registry
    // and `serverReadiness` exactly as `modelOptions` does — a refreshed Ollama
    // catalogue can turn `unknown` into `supported` under a card that is
    // already on screen.
    expect(effortField(registry()).subscribe).toBeTypeOf('function');
  });
});

describe('every model-driven node type in the catalogue', () => {
  const modelFields = allNodeDefinitions().flatMap((definition) =>
    (definition.fields ?? [])
      .filter((field) => field.key === MODEL_FIELD_KEY || field.key === REASONING_EFFORT_FIELD_KEY)
      .map((field) => ({ type: definition.id, field })),
  );

  it('finds such fields at all, so this test can fail', () => {
    expect(modelFields.length).toBeGreaterThan(0);
  });

  it.each(modelFields)('$type declares where $field.key gets its options', ({ field }) => {
    expect(
      'subscribe' in field && field.subscribe,
      'this field resolves its options from the provider registry but names no store, ' +
        'so its control will keep whatever list it had at first paint',
    ).toBeTruthy();
  });
});
