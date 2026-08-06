import { ModelRegistry } from '@core/model/ModelRegistry';
import { WorkflowModel } from '@core/model/WorkflowModel';
import { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import {
  ConnectionValidator,
  DEFAULT_CONNECTION_RULES,
} from '@core/validation/ConnectionValidator';
import {
  DEFAULT_WORKFLOW_RULES,
  WorkflowValidator,
} from '@core/validation/WorkflowValidator';
import { ExecutionEngine } from '@core/execution/ExecutionEngine';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { MockProvider } from '@core/providers/MockProvider';
import { AnthropicProvider } from '@core/providers/AnthropicProvider';
import { OpenAIProvider } from '@core/providers/OpenAIProvider';
import { OllamaProvider } from '@core/providers/OllamaProvider';
import { WorkflowController } from '@controller/WorkflowController';
import { registerNodeCatalogue } from '@nodes/index';
import { syncWorkflowScopedNodes } from '@nodes/workflowScoped';
import { applyLayoutTokens } from '@design/tokens';

/**
 * The application's object graph.
 *
 * One explicit composition root instead of module-level singletons: every
 * collaborator is constructed here, in dependency order, and handed to
 * whoever needs it. That is what makes the whole engine testable — a test
 * builds a Workbench with three node types and a stub provider, and nothing
 * reaches for a global to find the "real" one.
 *
 * Nothing in this class is React-aware; the view receives it through a
 * context provider.
 */
export class Workbench {
  readonly registry = new ModelRegistry();
  readonly model = new WorkflowModel('AI Workflow');
  readonly credentials = new CredentialStore();
  readonly providers: ProviderRegistry;
  readonly connectionValidator: ConnectionValidator;
  readonly workflowValidator: WorkflowValidator;
  readonly serializer: WorkflowSerializer;
  readonly engine: ExecutionEngine;
  readonly controller: WorkflowController;

  constructor() {
    this.providers = new ProviderRegistry(this.credentials);

    // Mock first, so it is the default selection and the editor is usable
    // with no credentials at all.
    this.providers
      .register(new MockProvider())
      .register(new AnthropicProvider())
      .register(new OpenAIProvider())
      .register(new OllamaProvider());

    this.connectionValidator = new ConnectionValidator(this.model, this.registry);
    this.connectionValidator.rules.registerAll(DEFAULT_CONNECTION_RULES);

    this.workflowValidator = new WorkflowValidator(this.model, this.registry);
    this.workflowValidator.rules.registerAll(DEFAULT_WORKFLOW_RULES);

    this.serializer = new WorkflowSerializer(this.registry);

    this.engine = new ExecutionEngine(this.model, this.providers, this.workflowValidator);

    // The catalogue registers node types *and* their executors, so the
    // engine and the palette can never disagree about what exists.
    registerNodeCatalogue(this.registry, this.engine.executors, this.providers);

    // Workflow-scoped nodes (Chinook's tools) are not part of the global
    // catalogue above — they are registered only while a document that
    // actually references them is open, so an unrelated workflow's palette
    // does not carry every past workflow's tools. Re-synced on every event
    // that can change which node types the document uses.
    const sync = () => syncWorkflowScopedNodes(this.model, this.registry, this.engine.executors);
    this.model.on('workflow:reset', sync);
    this.model.on('node:added', sync);
    this.model.on('node:removed', sync);
    sync();

    this.controller = new WorkflowController({
      model: this.model,
      registry: this.registry,
      connectionValidator: this.connectionValidator,
      workflowValidator: this.workflowValidator,
      serializer: this.serializer,
    });
  }

  /**
   * Asks every provider that can enumerate models to do so.
   *
   * Fire-and-forget on purpose: the seeded model list is already usable, and
   * blocking first paint on a network round-trip — or on an Ollama daemon
   * that may not be running — would be a poor trade.
   */
  warmUp(): void {
    void this.providers.refreshModels();
  }

  dispose(): void {
    this.engine.dispose();
    this.controller.dispose();
    this.model.dispose();
  }
}

export function createWorkbench(): Workbench {
  // Publish the shared layout constants before anything measures itself.
  applyLayoutTokens();
  return new Workbench();
}
