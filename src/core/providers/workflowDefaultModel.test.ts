import { describe, expect, it, vi } from 'vitest';

import { CredentialStore, ProviderRegistry } from './ProviderRegistry';
import { MOCK_SELECTION, workflowModelAsSelection } from './modelSelection';
import { MockProvider } from './MockProvider';
import { AnthropicProvider } from './AnthropicProvider';
import { OllamaProvider } from './OllamaProvider';

/**
 * What an *empty* model selection means.
 *
 * A node left on "Workflow default" stores `''`, and until the registry knew
 * the open document's model there was nowhere for `''` to resolve except the
 * offline simulator. Everything downstream that asks the registry a question
 * about "the model this node runs" — the reasoning picker most visibly —
 * therefore answered about Mock while the run used the document's model.
 *
 * The registry is already the thing that turns a selection into a model, so
 * it is the thing that should know what the empty selection stands for.
 */
function registry(): ProviderRegistry {
  return new ProviderRegistry(new CredentialStore(false))
    .register(new MockProvider(0))
    .register(new AnthropicProvider())
    .register(new OllamaProvider());
}

describe('the workflow default model', () => {
  it('is the offline simulator until a document says otherwise', () => {
    expect(registry().model(MOCK_SELECTION)?.id).toBe('mock-offline');
    expect(registry().resolve('')?.modelId).toBe('mock-offline');
  });

  it('resolves an empty selection to the open document’s model', () => {
    const providers = registry();
    providers.setWorkflowDefaultModel('ollama:gpt-oss:120b-cloud');
    expect(providers.resolve('')).toMatchObject({ modelId: 'gpt-oss:120b-cloud' });
    expect(providers.resolve('')?.provider.id).toBe('ollama');
  });

  it('accepts the settings spelling, which is not the selection spelling', () => {
    // `workflow.settings.model` is what `init_chat_model` wants
    // (`ollama:gpt-oss:120b-cloud`); a node field is `providerId/modelId`.
    expect(workflowModelAsSelection('ollama:gpt-oss:120b-cloud')).toBe('ollama/gpt-oss:120b-cloud');
    const providers = registry();
    providers.setWorkflowDefaultModel('anthropic/claude-haiku-4-5');
    expect(providers.resolve('')?.modelId).toBe('claude-haiku-4-5');
  });

  it('falls back to the simulator when a document names no model', () => {
    const providers = registry();
    providers.setWorkflowDefaultModel('ollama:gpt-oss:120b-cloud');
    providers.setWorkflowDefaultModel('');
    expect(providers.resolve('')?.modelId).toBe('mock-offline');
  });

  it('announces the change, so an open picker stops showing the old answer', () => {
    const providers = registry();
    const seen = vi.fn();
    providers.onChange(seen);
    providers.setWorkflowDefaultModel('ollama:gpt-oss:120b-cloud');
    expect(seen).toHaveBeenCalled();
  });

  it('leaves an explicit selection alone', () => {
    const providers = registry();
    providers.setWorkflowDefaultModel('ollama:gpt-oss:120b-cloud');
    expect(providers.resolve('anthropic/claude-haiku-4-5')?.provider.id).toBe('anthropic');
  });
});
