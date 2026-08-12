import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { ToolCapability } from '@core/runtime/WorkflowFileClient';
import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
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
 * `chinook-assistant` or this session's `intent-routed-demo` would have
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
    (node) =>
      typeof node === 'object' &&
      node != null &&
      chinookTypeIds.has((node as { type?: unknown }).type as string),
  );
  applyChinookRegistration(documentUsesChinook, registry, executors);
}

/**
 * Unconditionally registers Chinook's tools.
 *
 * For a caller that needs the family stated outright rather than inferred
 * from a document — today, tests that add a Chinook node to a bare workbench
 * with no document behind it.
 *
 * **The startup seed is no longer one of them.** `seedDemo.ts` used to build
 * a Chinook showcase by writing nodes straight to the model before any
 * document existed for `registerNodeTypesForRawDocument` to inspect, and
 * without this call it crashed at startup —
 * `registry.nodeTypes.require('tool.chinook-get-all-tables')` throwing
 * synchronously before React ever mounts, which an error boundary cannot
 * catch because there is no component tree yet to catch it in. One-chinook
 * ticket 10 removed the hand-built seed entirely: the editor now imports the
 * shipped `workflows/chinook-assistant/workflow.json`, so it goes through
 * `registerNodeTypesForRawDocument` like every other load path and the
 * special case is gone rather than merely satisfied.
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

  const minted: string[] = [];
  for (const capability of capabilities) {
    if (isAlreadyHandAuthored(capability, registry)) continue;
    const { definition, executor } = createDiscoveredToolNode(capability);
    registry.nodeTypes.upsert(asWorkflowScoped(definition));
    executors.upsert(executor);
    minted.push(capability.id);
  }
  // Only what was actually minted, so the teardown above cannot unregister a
  // hand-authored card that discovery merely declined to duplicate.
  registeredDiscoveredToolIds = minted;
}

/**
 * Does a purpose-built card already cover this capability?
 *
 * A Python `BaseTool` declares the `node_type` of the card meant to represent
 * it, and the backend has always sent that field. The frontend never read it,
 * so once the Chinook tools moved into the visible package the palette's "This
 * workflow" section showed **six** entries where three are correct: the
 * hand-authored cards, plus a generic one per capability keyed by
 * `capability.id`.
 *
 * That is worse than clutter. The generic card's executor refuses toward Chat
 * rather than running in the canvas preview, and it is not the type the
 * shipped document wires — so of two identically-named palette entries, one
 * gives you a node that behaves differently from the one already on the canvas
 * beside it, and nothing on either card says which.
 *
 * The rule is not new, only half-implemented: `api/registries.py` already
 * records that "same-type collisions resolve workflow-wins, mirroring the
 * frontend's local-shadows-global registry rule". This is the frontend half.
 *
 * **Resolution, not mere declaration.** A tool naming a `node_type` no
 * TypeScript module ships must still reach the palette — otherwise declaring
 * the field would *remove* a capability, which is the opposite of what it is
 * for.
 */
function isAlreadyHandAuthored(capability: ToolCapability, registry: ModelRegistry): boolean {
  return capability.nodeType !== '' && registry.nodeTypes.get(capability.nodeType) != null;
}

/**
 * Safety net that stamps `scope: 'workflow'` onto a definition on its way
 * into the registry.
 *
 * The authoritative stamp now lives in each node module's spec
 * (`scope: 'workflow'` in `ChinookDatabaseNode` and `DiscoveredToolNode`).
 * It has to: `defineNode` binds
 * `create` to its own local definition, so a copy made here can never
 * reach a *placed* node — `node.definition` on an instance is the one the
 * spec produced, and `NodeCard` reads `definition.scope` to badge canvas
 * cards for types that vanish when another workflow is opened. This
 * wrapper stays as belt-and-braces at the registration seam so a future
 * scoped family that forgets its spec stamp is still kept out of the
 * palette's always-available sections — but its copy is presentation-only;
 * the spec is where the stamp must go.
 */
function asWorkflowScoped(definition: INodeDefinition): INodeDefinition {
  return { ...definition, scope: 'workflow' };
}

function applyChinookRegistration(
  shouldBeRegistered: boolean,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  applyFamilyRegistration(CHINOOK_NODES, shouldBeRegistered, registry, executors);
}

/**
 * The generic form of the per-family apply helper above: registers or
 * unregisters one workflow-scoped node family wholesale. A new family uses
 * this directly instead of adding another copy of the same loop.
 */
function applyFamilyRegistration(
  family: ReadonlyArray<{ definition: INodeDefinition; executor: INodeExecutor }>,
  shouldBeRegistered: boolean,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  for (const { definition, executor } of family) {
    const existing = registry.nodeTypes.get(definition.id);
    const alreadyRegistered = existing != null;
    // Re-upsert an entry that is registered but unstamped: a scoped type can
    // reach the registry by another route (a direct `upsert` in a test or a
    // seeding path), and one that stays unstamped would quietly reappear
    // among the always-available palette sections.
    if (shouldBeRegistered && alreadyRegistered && existing.scope !== 'workflow') {
      registry.nodeTypes.upsert(asWorkflowScoped(definition));
    } else if (shouldBeRegistered && !alreadyRegistered) {
      registry.nodeTypes.upsert(asWorkflowScoped(definition));
      executors.upsert(executor);
    } else if (!shouldBeRegistered && alreadyRegistered) {
      registry.nodeTypes.unregister(definition.id);
      executors.unregister(executor.id);
    }
  }
}
