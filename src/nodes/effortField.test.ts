import { describe, expect, it } from 'vitest';

import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { MockProvider } from '@core/providers/MockProvider';
import { AnthropicProvider } from '@core/providers/AnthropicProvider';
import { OllamaProvider } from '@core/providers/OllamaProvider';
import { defineNode } from '@core/model/ModelRegistry';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defaultsFrom, resolveOptions } from '@core/model/contracts/fields';
import type { SelectFieldSchema } from '@core/model/contracts/fields';

import { MODEL_FIELD_KEY, modelField } from './modelField';
import {
  COMMON_EFFORT_LEVELS,
  MODEL_DEFAULT_EFFORT,
  REASONING_EFFORT_FIELD_KEY,
  effortAvailability,
  effortField,
  effortFrom,
  effortOptionsFor,
  withReasoningEffort,
} from './effortField';

// `CredentialStore` is a class, not an interface, so a hand-rolled stand-in
// can never satisfy it. It does not need one: `new CredentialStore(false)` is
// the session mode — memory only, no `localStorage` — which is exactly the
// stub these tests were reaching for, and it is what every other test that
// builds a registry uses.
function registry(): ProviderRegistry {
  const providers = new ProviderRegistry(new CredentialStore(false));
  providers.register(new MockProvider(0));
  providers.register(new AnthropicProvider());
  providers.register(new OllamaProvider());
  return providers;
}

class Model extends AbstractNodeModel {}

describe('effortAvailability', () => {
  it('reports the provider tiers for a model that reasons', () => {
    const found = effortAvailability(registry(), {
      [MODEL_FIELD_KEY]: 'anthropic/claude-haiku-4-5',
    });
    expect(found).toEqual({ kind: 'supported', levels: ['low', 'medium', 'high', 'max'] });
  });

  it('reports unsupported for a model whose provider declares no tiers', () => {
    const found = effortAvailability(registry(), { [MODEL_FIELD_KEY]: 'mock/mock-offline' });
    expect(found.kind).toBe('unsupported');
  });

  it('reports unknown — not unsupported — for a discovered catalogue', () => {
    // Ollama's models arrive from `/api/tags` at runtime. The editor has no
    // way to know whether a freshly pulled tag reasons, and guessing "no"
    // would refuse a setting the runtime would have honoured.
    const found = effortAvailability(registry(), {
      [MODEL_FIELD_KEY]: 'ollama/gpt-oss:120b-cloud',
    });
    expect(found).toEqual({ kind: 'unknown' });
  });

  it('reports unknown for a selection no registered provider can resolve', () => {
    const found = effortAvailability(registry(), { [MODEL_FIELD_KEY]: 'nvidia/nemotron' });
    expect(found).toEqual({ kind: 'unknown' });
  });

  it('falls back to the mock simulator exactly as the model field does', () => {
    // An unconfigured node resolves to `mock/mock-offline` in the browser
    // (`resolveModelSelection`), which is a model known not to reason — so an
    // empty card must not advertise a reasoning control either.
    expect(effortAvailability(registry(), {}).kind).toBe('unsupported');
  });

  it('reads the open document’s model for a node left on "Workflow default"', () => {
    // The card used to lie. Every node in the shipped Chinook document is on
    // "Workflow default", the document's `settings.model` is
    // `ollama:gpt-oss:120b-cloud`, and the picker read "Not supported by Mock
    // · Offline" — a statement about a model the run would never use.
    const providers = registry();
    providers.setWorkflowDefaultModel('ollama:gpt-oss:120b-cloud');
    expect(effortAvailability(providers, {})).toEqual({ kind: 'unknown' });
  });

  it('still prefers the node’s own choice over the document default', () => {
    const providers = registry();
    providers.setWorkflowDefaultModel('ollama:gpt-oss:120b-cloud');
    expect(
      effortAvailability(providers, { [MODEL_FIELD_KEY]: 'anthropic/claude-haiku-4-5' }),
    ).toEqual({ kind: 'supported', levels: ['low', 'medium', 'high', 'max'] });
  });
});

describe('effortOptionsFor', () => {
  it('offers the model default plus every declared tier', () => {
    const options = effortOptionsFor(registry(), {
      [MODEL_FIELD_KEY]: 'anthropic/claude-haiku-4-5',
    });
    expect(options.map((option) => option.value)).toEqual([
      MODEL_DEFAULT_EFFORT,
      'low',
      'medium',
      'high',
      'max',
    ]);
  });

  it('offers no tier at all on a model that cannot reason', () => {
    // The house rule: a control that reaches nothing is worse than no control.
    // One inert option naming the model, and nothing selectable that the run
    // would silently discard.
    const options = effortOptionsFor(registry(), { [MODEL_FIELD_KEY]: 'mock/mock-offline' });
    expect(options).toHaveLength(1);
    expect(options[0]?.value).toBe(MODEL_DEFAULT_EFFORT);
    expect(options[0]?.label).toContain('Mock');
  });

  it('offers only tiers every provider spells the same way when capability is unknown', () => {
    const options = effortOptionsFor(registry(), {
      [MODEL_FIELD_KEY]: 'ollama/gpt-oss:120b-cloud',
    });
    expect(options.slice(1).map((option) => option.value)).toEqual([...COMMON_EFFORT_LEVELS]);
    // `minimal` is real on OpenAI and a pydantic error on Anthropic; the
    // fallback list must not be the riskiest option on offer.
    expect(options.map((option) => option.value)).not.toContain('minimal');
  });

  it('offers the common tiers — not a Mock disclaimer — on a workflow-default node', () => {
    const providers = registry();
    providers.setWorkflowDefaultModel('ollama:gpt-oss:120b-cloud');
    const options = effortOptionsFor(providers, {});
    expect(options.map((option) => option.label)).not.toContain('Not supported by Mock · Offline');
    expect(options.slice(1).map((option) => option.value)).toEqual([...COMMON_EFFORT_LEVELS]);
  });

  it('recomputes when the model changes, through the select schema itself', () => {
    const schema = effortField(registry());
    const reasoning = resolveOptions(schema, { [MODEL_FIELD_KEY]: 'anthropic/claude-opus-5' });
    const notReasoning = resolveOptions(schema, { [MODEL_FIELD_KEY]: 'mock/mock-offline' });
    expect(reasoning.length).toBeGreaterThan(1);
    expect(notReasoning).toHaveLength(1);
  });
});

describe('effortFrom', () => {
  it('omits an unchosen tier rather than sending an empty one', () => {
    expect(effortFrom({})).toBeUndefined();
    expect(effortFrom({ [REASONING_EFFORT_FIELD_KEY]: '   ' })).toBeUndefined();
    expect(effortFrom({ [REASONING_EFFORT_FIELD_KEY]: 'high' })).toBe('high');
  });
});

describe('withReasoningEffort', () => {
  const drivesAModel = (providers: ProviderRegistry) =>
    defineNode(
      {
        id: 'test.drives-model',
        category: 'agent',
        label: 'Drives a model',
        description: '',
        iconId: 'node-agent',
        accent: 'indigo',
        defaultSize: { width: 200, height: 100 },
        fields: [modelField(providers), { kind: 'text', key: 'other', defaultValue: '' }],
      },
      Model,
    );

  const drivesNothing = defineNode(
    {
      id: 'test.no-model',
      category: 'agent',
      label: 'No model',
      description: '',
      iconId: 'node-agent',
      accent: 'indigo',
      defaultSize: { width: 200, height: 100 },
      fields: [{ kind: 'text', key: 'other', defaultValue: '' }],
    },
    Model,
  );

  it('adds the control to any definition that carries the model picker', () => {
    const providers = registry();
    const withEffort = withReasoningEffort(drivesAModel(providers), providers);
    const keys = withEffort.fields.map((field) => field.key);
    expect(keys).toContain(REASONING_EFFORT_FIELD_KEY);
    // Immediately after the model, because the two are one decision.
    expect(keys.indexOf(REASONING_EFFORT_FIELD_KEY)).toBe(keys.indexOf(MODEL_FIELD_KEY) + 1);
  });

  it('reaches a node built from the definition, not just the definition', () => {
    // The defect this test exists for was invisible to every assertion above.
    // `defineNode`'s `create` closes over the definition it built, so a spread
    // copy gave the palette the new field and every *instance* the old list —
    // the picker was in `registry.nodeTypes.get(…).fields` and absent from the
    // inspector of a node created from it. Found in the running editor.
    const providers = registry();
    const definition = withReasoningEffort(drivesAModel(providers), providers);
    const node = definition.create({ id: 'n1', position: { x: 0, y: 0 } });
    expect(node.definition.fields.map((field) => field.key)).toContain(REASONING_EFFORT_FIELD_KEY);
    expect(node.data).toHaveProperty(REASONING_EFFORT_FIELD_KEY, MODEL_DEFAULT_EFFORT);
  });

  it('leaves a node that drives no model untouched', () => {
    const providers = registry();
    expect(withReasoningEffort(drivesNothing, providers)).toBe(drivesNothing);
  });

  it('is idempotent, so re-registering a catalogue cannot double the field', () => {
    const providers = registry();
    const once = withReasoningEffort(drivesAModel(providers), providers);
    const twice = withReasoningEffort(once, providers);
    expect(twice).toBe(once);
  });

  it('seeds its default through the same path as every other field', () => {
    const providers = registry();
    const withEffort = withReasoningEffort(drivesAModel(providers), providers);
    expect(defaultsFrom(withEffort.fields)[REASONING_EFFORT_FIELD_KEY]).toBe(MODEL_DEFAULT_EFFORT);
  });

  it('defaults to the model default rather than a tier', () => {
    // Seeding `medium` would silently change every existing node's behaviour
    // while looking like a display default — some models default to `high`.
    const schema = effortField(registry()) as SelectFieldSchema;
    expect(schema.defaultValue).toBe(MODEL_DEFAULT_EFFORT);
  });
});
