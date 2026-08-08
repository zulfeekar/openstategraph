import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { ToolCapability } from '@core/runtime/WorkflowFileClient';
import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
import { TABULAR_NODES } from './tools/TabularDataNode';
import { WORKSHOP_NODES } from './tools/CodeWorkshopNode';
import { createDiscoveredToolNode } from './tools/DiscoveredToolNode';

/**
 * Registers a node type only while a workflow that actually uses it is open.
 *
 * **The gap this closes**, recorded directly in `.scratch/fullstack-langgraph/map.md`:
 * the Chinook tools were registered unconditionally in the global catalogue
 * (`registerNodeCatalogue`), so every workflow's palette carried them —
 * "put one workflow's tools in the shared catalogue and every future
 * palette carries every past workflow's tools... useless exactly when the
 * product starts working." The settled fix is a workflow-scoped registry
 * overlay on the shared `Registry<T>`, using the `upsert()` it already
 * has, with workflow-local shadowing global.
 *
 * **What this is not**: the full generic mechanism ticket 18 designs
 * (a backend capability manifest per workflow, pushed over SSE, driving
 * dynamically-schemad node types for *any* discovered tool). That is real,
 * separately-scoped work — a dynamic-field-rendering node type from an
 * arbitrary Pydantic schema — and remains an honest gap. This is the
 * narrower, immediate fix: the one family of workflow-specific nodes that
 * actually exists today (Chinook) stops leaking into every other
 * workflow's palette, keyed off what the *current document* references
 * rather than a hand-maintained slug allowlist — so it keeps working
 * correctly however a document was loaded (initial seed, autosave restore,
 * an explicit Load), with one hook instead of one per load path.
 */
export function syncWorkflowScopedNodes(
  model: WorkflowModel,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  const chinookTypeIds = new Set(CHINOOK_NODES.map((n) => n.definition.id));
  const documentUsesChinook = model.nodes().some((node) => chinookTypeIds.has(node.type));
  applyChinookRegistration(documentUsesChinook, registry, executors);

  const tabularTypeIds = new Set(TABULAR_NODES.map((n) => n.definition.id));
  const documentUsesTabular = model.nodes().some((node) => tabularTypeIds.has(node.type));
  applyTabularRegistration(documentUsesTabular, registry, executors);

  const workshopTypeIds = new Set(WORKSHOP_NODES.map((n) => n.definition.id));
  const documentUsesWorkshop = model.nodes().some((node) => workshopTypeIds.has(node.type));
  applyFamilyRegistration(WORKSHOP_NODES, documentUsesWorkshop, registry, executors);
}

/**
 * Registers whatever workflow-scoped types a **document about to be
 * imported** references, before it is imported.
 *
 * Load-order bug this exists to prevent, found while building
 * `syncWorkflowScopedNodes` itself, not live: `WorkflowSerializer.fromJSON`
 * resolves each serialized node's type via `registry.nodeTypes.get(...)`
 * and **silently skips** any node whose type is not registered yet
 * (`Skipped unknown node type "…"`, filed as a warning, not a failure). If
 * Chinook's tools are only ever registered *after* their nodes are already
 * in the model, they can never get there in the first place — importing
 * `chinook-nl-to-sql` or this session's `intent-routed-demo` would have
 * silently dropped all three tool nodes and every edge touching them,
 * every single time either was loaded. Call this immediately before
 * `controller.document.importJSON(json)`, from every load path (an
 * explicit "Load", the crash-continuity autosave restore, or any future
 * one) — `syncWorkflowScopedNodes` above then keeps things correct as the
 * session continues (dragging the last Chinook node off the canvas
 * unregisters the family again).
 */
export function registerNodeTypesForRawDocument(
  document: unknown,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  const nodes = (document as { nodes?: unknown })?.nodes;
  if (!Array.isArray(nodes)) return;

  const chinookTypeIds = new Set(CHINOOK_NODES.map((n) => n.definition.id));
  const documentUsesChinook = nodes.some(
    (node) => typeof node === 'object' && node != null && chinookTypeIds.has((node as { type?: unknown }).type as string),
  );
  applyChinookRegistration(documentUsesChinook, registry, executors);

  const tabularTypeIds = new Set(TABULAR_NODES.map((n) => n.definition.id));
  const documentUsesTabular = nodes.some(
    (node) => typeof node === 'object' && node != null && tabularTypeIds.has((node as { type?: unknown }).type as string),
  );
  applyTabularRegistration(documentUsesTabular, registry, executors);

  const workshopTypeIds = new Set(WORKSHOP_NODES.map((n) => n.definition.id));
  const documentUsesWorkshop = nodes.some(
    (node) => typeof node === 'object' && node != null && workshopTypeIds.has((node as { type?: unknown }).type as string),
  );
  applyFamilyRegistration(WORKSHOP_NODES, documentUsesWorkshop, registry, executors);
}

/**
 * Unconditionally registers Chinook's tools.
 *
 * For the one legitimate case that needs it stated outright rather than
 * inferred from a document: the seeded startup demo (`seedDemo.ts`) *is*
 * a Chinook showcase, built by writing nodes straight to the model before
 * any document exists for `registerNodeTypesForRawDocument` to inspect.
 * Found live: without this, `seedDemoWorkflow` crashed at startup —
 * `registry.nodeTypes.require('tool.chinook-get-all-tables')` throwing
 * synchronously before React ever mounts, which an error boundary cannot
 * catch because there is no component tree yet to catch it in.
 */
export function registerChinookNodes(
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  applyChinookRegistration(true, registry, executors);
}

/** Ids this tab currently has registered from the last workflow's discovery call. */
let registeredDiscoveredToolIds: readonly string[] = [];

/**
 * Ticket 18's node-type-discovery half: registers one workflow-scoped node
 * type per `ToolCapability` the backend discovered in that workflow's
 * `tools/` folder (`WorkflowFileClient.capabilities`), so a hand-written
 * `BaseTool` subclass becomes a real, connectable palette entry with no TS
 * file to hand-author — see `DiscoveredToolNode.ts`.
 *
 * Unlike Chinook's usage-based sync (`syncWorkflowScopedNodes`), this
 * registers every discovered capability unconditionally the moment a
 * workflow is opened — the whole point is to make an undiscovered-until-now
 * capability *available* to place, not to react to something already
 * placed. Call on every successful load, passing the freshly-fetched list;
 * an empty list (an unsaved workflow, a fetch failure, or a workflow with
 * no `tools/` folder) correctly clears whatever the previous workflow had
 * registered rather than leaving it stranded in the palette.
 */
export function registerDiscoveredCapabilities(
  capabilities: readonly ToolCapability[],
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  for (const id of registeredDiscoveredToolIds) {
    if (registry.nodeTypes.get(id) != null) {
      registry.nodeTypes.unregister(id);
      executors.unregister(id);
    }
  }

  for (const capability of capabilities) {
    const { definition, executor } = createDiscoveredToolNode(capability);
    registry.nodeTypes.upsert(definition);
    executors.upsert(executor);
  }
  registeredDiscoveredToolIds = capabilities.map((c) => c.id);
}

function applyChinookRegistration(
  shouldBeRegistered: boolean,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  for (const { definition, executor } of CHINOOK_NODES) {
    const alreadyRegistered = registry.nodeTypes.get(definition.id) != null;
    if (shouldBeRegistered && !alreadyRegistered) {
      registry.nodeTypes.upsert(definition);
      executors.upsert(executor);
    } else if (!shouldBeRegistered && alreadyRegistered) {
      registry.nodeTypes.unregister(definition.id);
      executors.unregister(executor.id);
    }
  }
}

/**
 * The generic form of the per-family apply helpers above: registers or
 * unregisters one workflow-scoped node family wholesale. New families
 * (Code Workshop is the first) use this directly instead of adding another
 * copy of the same loop.
 */
function applyFamilyRegistration(
  family: ReadonlyArray<{ definition: INodeDefinition; executor: INodeExecutor }>,
  shouldBeRegistered: boolean,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  for (const { definition, executor } of family) {
    const alreadyRegistered = registry.nodeTypes.get(definition.id) != null;
    if (shouldBeRegistered && !alreadyRegistered) {
      registry.nodeTypes.upsert(definition);
      executors.upsert(executor);
    } else if (!shouldBeRegistered && alreadyRegistered) {
      registry.nodeTypes.unregister(definition.id);
      executors.unregister(executor.id);
    }
  }
}

function applyTabularRegistration(
  shouldBeRegistered: boolean,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  for (const { definition, executor } of TABULAR_NODES) {
    const alreadyRegistered = registry.nodeTypes.get(definition.id) != null;
    if (shouldBeRegistered && !alreadyRegistered) {
      registry.nodeTypes.upsert(definition);
      executors.upsert(executor);
    } else if (!shouldBeRegistered && alreadyRegistered) {
      registry.nodeTypes.unregister(definition.id);
      executors.unregister(executor.id);
    }
  }
}
