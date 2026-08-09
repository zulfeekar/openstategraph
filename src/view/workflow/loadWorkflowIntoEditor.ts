import { Err, Ok, type Result } from '@core/kernel/Result';
import type { Workbench } from '@app/Workbench';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { CURRENT_SLUG_KEY, recordKnownSavedAt } from '@app/workflowFileWatch';
import {
  registerDiscoveredCapabilities,
  registerNodeTypesForRawDocument,
} from '@nodes/workflowScoped';

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
 */
export async function loadWorkflowIntoEditor(
  slug: string,
  client: IWorkflowFileClient,
  workbench: Workbench,
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
    registerDiscoveredCapabilities(
      capabilities.ok ? capabilities.value.tools : [],
      workbench.registry,
      workbench.engine.executors,
    );
    registerNodeTypesForRawDocument(outcome.value, workbench.registry, workbench.engine.executors);
    workbench.controller.document.importJSON(JSON.stringify(outcome.value));
    // Continuing to edit and save now updates *this* workflow, not a new one.
    sessionStorage.setItem(CURRENT_SLUG_KEY, slug);
    // Establishes the file watch's baseline for this slug — otherwise its
    // first poll after a load would have nothing to compare against and could
    // mistake the file as already-changed.
    const list = await client.list();
    recordKnownSavedAt(slug, list.ok ? list.value.find((wf) => wf.slug === slug)?.savedAt : undefined);
    return Ok(workbench.model.name);
  } catch (error) {
    return Err(`Failed to import: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
