import { describe, expect, it } from 'vitest';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { resolveOptions } from '@core/model/contracts/fields';
import {
  MOCK_SELECTION,
  MODEL_FIELD_KEY,
  WORKFLOW_DEFAULT_MODEL,
  modelField,
  resolveModelSelection,
  workflowModelAsSelection,
} from '@nodes/modelField';

// `resolveOptions` is the one place that decides whether a field's options are
// a list or a function of the node's data. This helper had a hand-rolled copy
// of that branch, which stopped matching when the resolver gained its `data`
// parameter.
const options = (registry: ProviderRegistry) => resolveOptions(modelField(registry));

describe('modelField', () => {
  it('defaults to the workflow model, not to a fake one', () => {
    // The old default was `mock/mock-offline`, so every unconfigured card read
    // **Mock · Offline** while the backend's `_resolve_model` treated `mock`
    // as "no override" and ran the workflow's real model. The card named a
    // fake model for a node that would use a real one.
    expect(modelField(new ProviderRegistry(new CredentialStore(false))).defaultValue).toBe(
      WORKFLOW_DEFAULT_MODEL,
    );
    expect(WORKFLOW_DEFAULT_MODEL).toBe('');
  });

  it('offers the workflow default first, so the honest choice is the reachable one', () => {
    const first = options(new ProviderRegistry(new CredentialStore(false)))[0];
    expect(first?.value).toBe(WORKFLOW_DEFAULT_MODEL);
    expect(first?.label).toMatch(/workflow/i);
  });

  it('still offers every model the registry knows', () => {
    const registry = new ProviderRegistry(new CredentialStore(false));
    const listed = options(registry).map((option) => option.value);
    for (const option of registry.modelOptions()) {
      expect(listed).toContain(option.value);
    }
  });

  it('re-reads the registry on every call, so a key pasted mid-session shows up', () => {
    const registry = new ProviderRegistry(new CredentialStore(false));
    const field = modelField(registry);
    expect(typeof field.options).toBe('function');
  });

  it('is the same key the backend reads', () => {
    expect(MODEL_FIELD_KEY).toBe('model');
    expect(modelField(new ProviderRegistry(new CredentialStore(false))).key).toBe(MODEL_FIELD_KEY);
  });
});

describe('workflowModelAsSelection', () => {
  it('converts the runtime format every shipped workflow actually uses', () => {
    // Verified against workflows/*/workflow.json — all four carry exactly this.
    expect(workflowModelAsSelection('ollama:gpt-oss:120b-cloud')).toBe('ollama/gpt-oss:120b-cloud');
  });

  it('splits on the FIRST colon — a model id may contain its own', () => {
    // Splitting on the last would invent a provider called `ollama:gpt-oss`.
    expect(workflowModelAsSelection('ollama:a:b:c')).toBe('ollama/a:b:c');
  });

  it('leaves a value that is already a selection alone', () => {
    expect(workflowModelAsSelection('anthropic/claude-opus-5')).toBe('anthropic/claude-opus-5');
  });

  it('leaves a bare model id alone rather than inventing a provider', () => {
    expect(workflowModelAsSelection('gpt-4o')).toBe('gpt-4o');
    expect(workflowModelAsSelection(':leading')).toBe(':leading');
  });
});

describe('resolveModelSelection', () => {
  it('prefers the node’s own choice', () => {
    expect(resolveModelSelection('anthropic/claude-opus-5', { model: 'ollama:x' })).toBe(
      'anthropic/claude-opus-5',
    );
  });

  it('falls back to the workflow’s model, in a format the registry can read', () => {
    expect(resolveModelSelection('', { model: 'ollama:gpt-oss:120b-cloud' })).toBe(
      'ollama/gpt-oss:120b-cloud',
    );
    expect(resolveModelSelection('   ', { model: 'ollama:gpt-oss:120b-cloud' })).toBe(
      'ollama/gpt-oss:120b-cloud',
    );
  });

  it('falls back to the offline simulator only when the document names nothing', () => {
    // The browser preview holds no API key and reaches no backend, so mock is
    // the honest last resort here — and only here.
    expect(resolveModelSelection('', {})).toBe(MOCK_SELECTION);
    expect(resolveModelSelection('', { model: '  ' })).toBe(MOCK_SELECTION);
    expect(resolveModelSelection('', { model: 42 })).toBe(MOCK_SELECTION);
  });
});
