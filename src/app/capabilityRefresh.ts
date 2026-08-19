import { WorkflowFileClient, type ToolCapability } from '@core/runtime/WorkflowFileClient';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import { registerDiscoveredCapabilities } from '@nodes/workflowScoped';
import { registerPluginCapabilities, setCapabilityWarnings } from '@app/pluginNodes';
import { setAmbientTools } from '@app/ambientTools';

/**
 * Ticket 18's hot-discovery gap, closed **on demand rather than on a timer**.
 *
 * A new file in a workflow's `tools/` folder does not touch `workflow.json`
 * at all, so nothing the document watcher looks at changes and the palette
 * stays stale until a full re-Load. The obvious fix — fold a capabilities
 * fetch into the 5s document poll — was tried and removed: it spends a
 * request every five seconds, for every open tab, forever, to catch an event
 * that happens a handful of times in an authoring session and whose exact
 * moment the author already knows (they just saved the file). So discovery
 * is refreshed at the two moments it can actually have changed: when a
 * workflow is loaded (`loadWorkflowIntoEditor`), and when the author asks —
 * the palette's "Refresh" affordance, which calls straight into here.
 *
 * The open workflow's slug is a parameter, not a `sessionStorage` read
 * hidden inside — this module then needs no browser globals and stays
 * testable in the `node` environment the suite runs in. The decision itself
 * (`decideCapabilityRefresh`) stays pure and separate from the fetch, so the "did anything actually appear?" question is
 * testable without a network stub — the same split `decideFileWatchAction`
 * uses.
 */

/** The tool capability ids this tab currently has registered, per slug. */
const knownCapabilityIds = new Map<string, readonly string[]>();

export type CapabilityRefreshAction =
  | { readonly kind: 'baseline'; readonly ids: readonly string[] }
  | { readonly kind: 'unchanged' }
  | {
      readonly kind: 'changed';
      readonly ids: readonly string[];
      readonly added: readonly string[];
    };

/**
 * The pure half: given what the backend reports now and what this tab last
 * knew, did the workflow's discovered-tool set change, and what is new.
 *
 * Order-independent (`Set`, not array equality) because the backend's own
 * discovery order carries no promise of stability.
 */
export function decideCapabilityRefresh(
  fresh: readonly ToolCapability[],
  known: readonly string[] | undefined,
): CapabilityRefreshAction {
  const ids = fresh.map((c) => c.id);
  if (known === undefined) return { kind: 'baseline', ids };

  const knownSet = new Set(known);
  const freshSet = new Set(ids);
  const same = knownSet.size === freshSet.size && [...knownSet].every((id) => freshSet.has(id));
  if (same) return { kind: 'unchanged' };

  const added = ids.filter((id) => !knownSet.has(id));
  return { kind: 'changed', ids, added };
}

export type CapabilityRefreshOutcome =
  /** No saved workflow is open, so there is no `tools/` folder to look in. */
  | { readonly kind: 'no-workflow' }
  /** The registry now matches disk, and nothing about it is new. */
  | { readonly kind: 'unchanged'; readonly total: number }
  /** The registry now matches disk, and these ids were not there before. */
  | { readonly kind: 'changed'; readonly total: number; readonly added: readonly string[] };

/**
 * Re-fetches the open workflow's discovered capabilities and re-registers
 * them as workflow-scoped node types.
 *
 * A failed fetch is deliberately *not* an error case: ticket 18's discovery
 * endpoint already treats a workflow with no `tools/` folder as an empty
 * list rather than a failure, and an empty list correctly unregisters
 * whatever was there — a tool file that was deleted should leave the
 * palette, which is exactly as much a refresh as one that appeared.
 */
export async function refreshWorkflowCapabilities(
  slug: string | null,
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
  client: Pick<WorkflowFileClient, 'capabilities'> = new WorkflowFileClient(),
): Promise<CapabilityRefreshOutcome> {
  if (!slug) return { kind: 'no-workflow' };

  const outcome = await client.capabilities(slug);
  const tools = outcome.ok ? outcome.value.tools : [];
  const action = decideCapabilityRefresh(tools, knownCapabilityIds.get(slug));

  // Both of these run whatever the workflow-local decision was. An installed
  // plugin's tools and the capability warnings are not keyed to this
  // workflow's `tools/` folder at all (register PK-06): a `pip install`
  // between two Refresh presses changes neither `tools` nor its ids, and
  // skipping the re-registration on "unchanged" is how a newly installed
  // plugin would stay invisible until a full reload.
  registerPluginCapabilities(outcome.ok ? outcome.value.pluginTools : [], registry, executors);
  setCapabilityWarnings(outcome.ok ? outcome.value.warnings : []);
  // Same rule, same reason: what every agent binds without wiring is a property
  // of the *server*, not of this workflow's `tools/` folder, so it is refreshed
  // whatever the workflow-local decision was (`every-workflow-green` 05a). A
  // failed fetch reports "binds none" rather than keeping a stale answer — an
  // agent card claiming capabilities the editor can no longer confirm is the
  // defect this whole ticket is about, one layer along.
  setAmbientTools(outcome.ok ? outcome.value.ambientTools : []);

  if (action.kind === 'unchanged') return { kind: 'unchanged', total: tools.length };

  knownCapabilityIds.set(slug, action.ids);
  registerDiscoveredCapabilities(tools, registry, executors);
  return action.kind === 'changed'
    ? { kind: 'changed', total: tools.length, added: action.added }
    : { kind: 'unchanged', total: tools.length };
}

/**
 * Baselines what a load already registered, so the first manual Refresh
 * after opening a workflow reports honestly ("nothing new") instead of
 * announcing every tool the load had just put there.
 */
export function recordKnownCapabilities(
  slug: string,
  capabilities: readonly ToolCapability[],
): void {
  knownCapabilityIds.set(
    slug,
    capabilities.map((c) => c.id),
  );
}

/** Exposed for tests — a module-level cache would otherwise leak between them. */
export function forgetKnownCapabilities(): void {
  knownCapabilityIds.clear();
}
