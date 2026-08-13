import { Err, Ok, type Result } from '@core/kernel/Result';
import type { Workbench } from '@app/Workbench';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { recordKnownSavedAt } from '@app/workflowFileWatch';
import { setOpenSlug } from '@app/openWorkflow';
import { clearOpenAddress, setOpenAddress } from '@app/openAddress';
import type { MountAddress } from '@core/model/MountAddress';
import {
  registerDiscoveredCapabilities,
  registerNodeTypesForRawDocument,
} from '@nodes/workflowScoped';
import { recordKnownCapabilities } from '@app/capabilityRefresh';
import { registerPluginCapabilities, setCapabilityWarnings } from '@app/pluginNodes';
import { pushDrillFrame } from '@app/drillStack';
import { restoreDraftFor } from '@app/workflowDrafts';

/**
 * What was opened, and where its contents came from.
 *
 * `restoredDraft` is not a detail: the file on the backend and this browser's
 * unsaved edits to it are two different documents, and a person who is shown
 * one while believing they are looking at the other has been misled by the
 * editor. Reported to the caller rather than toasted here, for the same reason
 * everything else presentational is — the panel, the deep link and the
 * drill-in each phrase it in their own context.
 */
export interface LoadedWorkflow {
  /** The workflow's name, for the caller's toast. */
  readonly name: string;
  /** True when this browser's newer draft was loaded instead of the file. */
  readonly restoredDraft: boolean;
}

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
/**
 * Load one **instance** of a mounted workflow — ticket 42.
 *
 * The address names the mount (`concierge/wf-music`); the backend answers with
 * that mount's *effective* document and with the class the instance is of. The
 * split matters at every step below: what is imported is the instance, and
 * what capabilities, knowledge and the file watch are asked about is the
 * class, because none of those differ per mount.
 *
 * Deliberately a sibling of `loadWorkflowIntoEditor` rather than a branch
 * inside it. The two share the registration order and differ in four places —
 * the fetch, the draft, the scope, and what gets recorded as open — and a
 * function with four `if (isInstance)` branches would be one function pretending
 * to be two.
 */
export async function loadMountIntoEditor(
  address: MountAddress,
  client: IWorkflowFileClient,
  workbench: Workbench,
): Promise<Result<LoadedWorkflow, string>> {
  const outcome = await client.loadMount(address);
  if (!outcome.ok) return Err(outcome.error);
  const { slug, document } = outcome.value;

  try {
    registerNodeTypesForRawDocument(document, workbench.registry, workbench.engine.executors);
    const capabilities = await client.capabilities(slug);
    const tools = capabilities.ok ? capabilities.value.tools : [];
    registerDiscoveredCapabilities(tools, workbench.registry, workbench.engine.executors);
    registerPluginCapabilities(
      capabilities.ok ? capabilities.value.pluginTools : [],
      workbench.registry,
      workbench.engine.executors,
    );
    setCapabilityWarnings([
      ...(capabilities.ok ? capabilities.value.warnings : []),
      // The merge's own reports ride the same surface: an override naming a
      // child node that no longer exists ran the package default, and the
      // person looking at the instance is the one who can fix it.
      ...outcome.value.warnings,
    ]);
    recordKnownCapabilities(slug, tools);
    workbench.controller.document.importJSON(JSON.stringify(document));
    // **No draft restore.** A draft belongs to a document someone can save,
    // and this one is derived — the package plus this mount's overrides. There
    // is nothing here that a later Save could write back as itself.
    //
    // The autosave *key* still moves, to the address rather than the class
    // slug (`setOpenAddress`), so whatever this tab writes cannot land on the
    // package's own draft and be restored over it later.
    const mountId = address.mountPath[address.mountPath.length - 1] ?? '';
    workbench.controller.document.enterInstance(mountId);
    setOpenAddress(address, slug);
    // Baselined on the **class**: the file that actually backs this instance
    // is the package, so that is the one whose changes matter to it.
    const row = await client.summary(slug);
    recordKnownSavedAt(slug, row.ok ? (row.value?.savedAt ?? undefined) : undefined);
    return Ok({ name: workbench.model.name, restoredDraft: false });
  } catch (error) {
    return Err(`Failed to import: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

export async function loadWorkflowIntoEditor(
  slug: string,
  client: IWorkflowFileClient,
  workbench: Workbench,
  provenance?: DrillProvenance,
): Promise<Result<LoadedWorkflow, string>> {
  const outcome = await client.load(slug);
  if (!outcome.ok) return Err(outcome.error);

  try {
    // Hand-authored cards first, discovery second, and the order is the whole
    // fix for ticket 32. `registerDiscoveredCapabilities` declines to mint a
    // generic card for a capability whose `node_type` is *already registered*
    // (`isAlreadyHandAuthored`) — so running it before the document's own
    // hand-authored families are in the registry asks that question too early,
    // gets "no" for every one of them, and mints a duplicate. That is why the
    // palette showed six Chinook entries for three tools, and why the count was
    // unstable: on a load where the previous document had left the family
    // registered, the same check answered "yes" and the duplicates vanished.
    //
    // Both still run *before* the import. That is no longer a data-loss
    // question — `WorkflowSerializer` preserves an unregistered node now
    // instead of skipping it (ticket 20, `core/serialization/UnknownNode.ts`)
    // — but it decides whether a node arrives as its real, editable card or as
    // an unknown-node placeholder, which is worth getting right.
    registerNodeTypesForRawDocument(outcome.value, workbench.registry, workbench.engine.executors);
    const capabilities = await client.capabilities(slug);
    const tools = capabilities.ok ? capabilities.value.tools : [];
    registerDiscoveredCapabilities(tools, workbench.registry, workbench.engine.executors);
    // The other source, same moment and for the same reason (register PK-06):
    // a tool an installed distribution ships is bindable by the runtime, so a
    // saved document may already reference it.
    registerPluginCapabilities(
      capabilities.ok ? capabilities.value.pluginTools : [],
      workbench.registry,
      workbench.engine.executors,
    );
    setCapabilityWarnings(capabilities.ok ? capabilities.value.warnings : []);
    // Baseline for the palette's manual Refresh: without it, the first press
    // after a load would report every tool the load itself registered as new.
    recordKnownCapabilities(slug, tools);
    workbench.controller.document.importJSON(JSON.stringify(outcome.value));
    // …and then this browser's own unsaved edits to *this* workflow, if it has
    // any that differ (ticket 23). Opening a second workflow used to discard
    // them with no prompt and no way back, because the draft was keyed on the
    // tab rather than on the document.
    const draft = restoreDraftFor(slug, workbench);
    // Continuing to edit and save now updates *this* workflow, not a new one —
    // and the address bar says which one, so the developer who just opened it
    // can copy the link (ticket 20). Set after the import succeeded: a URL
    // naming a workflow that failed to open is a link that lies.
    // Back to a package: every change is expressible again, and the tab is no
    // longer displaying an instance (ticket 42). Both are cleared here rather
    // than at each caller, because this is the one path that opens a document.
    workbench.controller.document.leaveInstance();
    clearOpenAddress();
    setOpenSlug(slug);
    // Establishes the file watch's baseline for this slug — otherwise its
    // first poll after a load would have nothing to compare against and could
    // mistake the file as already-changed. Asked about *this slug*, not found
    // in the editor listing: that listing omits hidden packages, so a drill-in
    // to `concierge` used to baseline `undefined` and then be told, one poll
    // later, that the file it had just loaded was deleted (ticket 21).
    const row = await client.summary(slug);
    recordKnownSavedAt(slug, row.ok ? (row.value?.savedAt ?? undefined) : undefined);
    // After the import, never before: a trail entry for a load that failed
    // would offer a way back from somewhere the user never arrived.
    if (provenance && provenance.fromSlug && provenance.fromSlug !== slug) {
      pushDrillFrame({ slug: provenance.fromSlug, name: provenance.fromName });
    }
    return Ok({ name: workbench.model.name, restoredDraft: draft.restored });
  } catch (error) {
    return Err(`Failed to import: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
