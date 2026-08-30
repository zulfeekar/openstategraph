import { PreferencesStore } from '@app/preferences';
import { openAncestry } from '@app/openAncestry';
import { provideMountAncestry } from '@core/runtime/mountAncestry';
import { ModelRegistry } from '@core/model/ModelRegistry';
import { WorkflowModel } from '@core/model/WorkflowModel';
import { UNNAMED_DOCUMENT } from '@core/model/documentName';
import { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import {
  ConnectionValidator,
  DEFAULT_CONNECTION_RULES,
} from '@core/validation/ConnectionValidator';
import { DEFAULT_WORKFLOW_RULES, WorkflowValidator } from '@core/validation/WorkflowValidator';
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
  /** Chrome-level user preferences (flow direction). Ticket 45. */
  readonly preferences = new PreferencesStore();
  /**
   * **Unnamed, and saying so** (`say-it-on-the-surface/09`). This was
   * `AI Workflow` — a plausible title, in the slot where a saved document's
   * name goes, on a document with no folder on the backend. The word is not
   * only cosmetic: the backend slugifies it at first save and freezes the
   * directory, so the default decided a folder name nobody chose.
   */
  readonly model = new WorkflowModel(UNNAMED_DOCUMENT);
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

    // What "Workflow default" means, kept current from the open document.
    // One wiring point, here, because this is where the document and the
    // provider set meet — every card, inspector and preview executor then
    // asks the registry rather than each inventing its own answer.
    this.model.on('workflow:settings', ({ settings }) =>
      this.providers.setWorkflowDefaultModel(String(settings['model'] ?? '')),
    );

    this.connectionValidator = new ConnectionValidator(this.model, this.registry);
    this.connectionValidator.rules.registerAll(DEFAULT_CONNECTION_RULES);

    this.workflowValidator = new WorkflowValidator(this.model, this.registry);
    this.workflowValidator.rules.registerAll(DEFAULT_WORKFLOW_RULES);

    this.serializer = new WorkflowSerializer(this.registry);

    // Migration v2 → v3: `team.workflow` collapses into `workflow.subgraph`
    // (production-ready ticket 16). The two compiled identically — one backend
    // builder, no branch, identical ports — and what made Team look like a
    // second organism was a glyph, an `outcome` field that turned out to be
    // documentation, and a census note the *child document* earns.
    //
    // The id is all that changes: the node keeps its id so edges still
    // resolve, and its data — slug, overrides, and the authored `outcome`
    // `workflow.subgraph` gained in the same change — comes across untouched.
    // Mirrors `MIGRATIONS[2]` in `backend/openstategraph/schema.py`; the two
    // sides read the same documents and must agree.
    this.serializer.register({
      from: 2,
      to: 3,
      migrate: (doc: Record<string, unknown>): Record<string, unknown> => {
        const nodes = Array.isArray(doc['nodes']) ? doc['nodes'] : [];
        for (const node of nodes) {
          if (
            typeof node === 'object' &&
            node !== null &&
            (node as Record<string, unknown>)['type'] === 'team.workflow'
          ) {
            (node as Record<string, unknown>)['type'] = 'workflow.subgraph';
          }
        }
        return doc;
      },
    });

    // Migration v1 → v2: convert router branches from newline-separated text
    // to repeatable-group array with stable ids (ticket 20).
    this.serializer.register({
      from: 1,
      to: 2,
      migrate: (doc: Record<string, unknown>): Record<string, unknown> => {
        const nodes = Array.isArray(doc['nodes']) ? doc['nodes'] : [];
        for (const node of nodes) {
          if (
            typeof node === 'object' &&
            node !== null &&
            typeof node['type'] === 'string' &&
            node['type'] === 'route.classifier' &&
            typeof node['data'] === 'object' &&
            node['data'] !== null
          ) {
            const data = node['data'] as Record<string, unknown>;
            const branches = data['branches'];
            // Convert newline-separated text to array of {id, name}
            if (typeof branches === 'string' && branches.trim()) {
              const entries = branches
                .split('\n')
                .filter((line) => line.trim())
                .map((name, idx) => ({
                  id: `b${Date.now()}-${idx}-${name
                    .trim()
                    .slice(0, 8)
                    .replace(/[^a-z0-9_]/gi, '-')}`,
                  name: name.trim(),
                }));
              data['branches'] = entries;
            }
          }
        }
        doc['version'] = 2;
        return doc;
      },
    });

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
  // Teach the mount field which packages are already above this document, so
  // picking one is refused in the editor with the compiler's own sentence
  // (organisms-first-class ticket 42). Installed here rather than in the
  // constructor because the trail is `sessionStorage`, and a `new Workbench()`
  // in a `node` test has no business inheriting a browser's open document.
  //
  // Oldest first: the drill trail, then the document on screen — the same
  // order `_subgraph` builds its ancestry in, so the chain in the refusal
  // reads as the route that produced the cycle.
  //
  // A reader, not a snapshot: the trail changes on every load, drill and save,
  // and a stale copy here would refuse a legitimate mount. `openAncestry` owns
  // what the trail is made of, and its own tests own the edge cases.
  provideMountAncestry(openAncestry);
  return new Workbench();
}
