import { Err, Ok, type Result } from '@core/kernel/Result';
import type { Workbench } from '@app/Workbench';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { CURRENT_SLUG_KEY, recordKnownSavedAt } from '@app/workflowFileWatch';
import {
  registerDiscoveredCapabilities,
  registerNodeTypesForRawDocument,
} from '@nodes/workflowScoped';
import { recordKnownCapabilities } from '@app/capabilityRefresh';
import { registerPluginCapabilities, setCapabilityWarnings } from '@app/pluginNodes';
import { pushDrillFrame } from '@app/drillStack';

/** The workflow a drill-in is leaving — recorded only once the load succeeds. */
export interface DrillProvenance {
  readonly fromSlug: string;
  readonly fromName: string;
}

/**
 * Load a saved workflow into the editor, by slug.
 *
 * Extracted from `WorkflowManager` unchanged, because there is now more than
 * one way to ask for it: the Workflows panel, and the **Open** affordance on a
 * Team/Workflow mount card (ticket 56's drill-in follow-up). Loading a
 * workflow is knowledge — the order of capability registration against import,
 * the frozen slug, the file watch's baseline — and duplicating that knowledge
 * at a second call site is exactly the duplication the DRY rule forbids. The
 * *presentation* (toasts, closing a panel, a busy spinner) stays with each
 * caller, since those genuinely differ.
 *
 * Everything it touches is injected, so this is orchestration, not policy: it
 * neither owns the client nor knows what a card is.
 *
 * `provenance` marks the load as a **drill-in**: the caller says which workflow
 * the user is leaving, and that frame joins the drill stack so the banner can
 * name the way back. Only a drill-in passes it — a Back click is a *pop*, and
 * a manual load from the Workflows panel clears the trail at its own call site.
 */
export async function loadWorkflowIntoEditor(
  slug: string,
  client: IWorkflowFileClient,
  workbench: Workbench,
  provenance?: DrillProvenance,
): Promise<Result<string, string>> {
  const outcome = await client.load(slug);
  if (!outcome.ok) return Err(outcome.error);

  try {
    // Before importing, not after: `fromJSON` skips any node whose type is
    // not registered yet, so a workflow-scoped type (Chinook's tools, or a
    // discovered capability already placed in a previously-saved document)
    // must exist in the registry before its nodes can be created at all —
    // registering afterwards would be too late. Ticket 18: a workflow's own
    // discovered `tools/` capabilities become real, connectable node types
    // the same way.
    const capabilities = await client.capabilities(slug);
    const tools = capabilities.ok ? capabilities.value.tools : [];
    registerDiscoveredCapabilities(tools, workbench.registry, workbench.engine.executors);
    // The other source, same moment and for the same reason (register PK-06):
    // a tool an installed distribution ships is bindable by the runtime, so a
    // saved document may already reference it, and `fromJSON` drops a node
    // whose type is not registered *yet*.
    registerPluginCapabilities(
      capabilities.ok ? capabilities.value.pluginTools : [],
      workbench.registry,
      workbench.engine.executors,
    );
    setCapabilityWarnings(capabilities.ok ? capabilities.value.warnings : []);
    // Baseline for the palette's manual Refresh: without it, the first press
    // after a load would report every tool the load itself registered as new.
    recordKnownCapabilities(slug, tools);
    registerNodeTypesForRawDocument(outcome.value, workbench.registry, workbench.engine.executors);
    workbench.controller.document.importJSON(JSON.stringify(outcome.value));
    // Continuing to edit and save now updates *this* workflow, not a new one.
    sessionStorage.setItem(CURRENT_SLUG_KEY, slug);
    // Establishes the file watch's baseline for this slug — otherwise its
    // first poll after a load would have nothing to compare against and could
    // mistake the file as already-changed.
    const list = await client.list();
    recordKnownSavedAt(slug, list.ok ? list.value.find((wf) => wf.slug === slug)?.savedAt : undefined);
    // After the import, never before: a trail entry for a load that failed
    // would offer a way back from somewhere the user never arrived.
    if (provenance && provenance.fromSlug && provenance.fromSlug !== slug) {
      pushDrillFrame({ slug: provenance.fromSlug, name: provenance.fromName });
    }
    return Ok(workbench.model.name);
  } catch (error) {
    return Err(`Failed to import: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
