import { Err, Ok, type Result } from '@core/kernel/Result';
import type { Workbench } from '@app/Workbench';
import type { IWorkflowFileClient } from '@core/runtime/WorkflowFileClient';
import { recordKnownSavedAt } from '@app/workflowFileWatch';
import { getOpenSlug, setOpenSlug } from '@app/openWorkflow';
import { clearOpenAddress, getOpenAddress, setOpenAddress } from '@app/openAddress';
import type { MountAddress } from '@core/model/MountAddress';
import { MountContext } from '@core/model/MountContext';
import {
  registerDiscoveredCapabilities,
  registerNodeTypesForRawDocument,
} from '@nodes/workflowScoped';
import { recordKnownCapabilities } from '@app/capabilityRefresh';
import { registerPluginCapabilities, setCapabilityWarnings } from '@app/pluginNodes';
import { pushDrillFrame } from '@app/drillStack';
import { restoreDraftFor } from '@app/workflowDrafts';
import { rememberDiskDocument } from '@app/diskAutosave';

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

    // The address and the mount context are recorded **before** the import,
    // and that ordering is load-bearing rather than tidy.
    //
    // `importJSON` fires `workflow:reset`, which is what makes a newly-opened
    // document catch up to the run (`AskPanel`, ticket 34/43). That projection
    // resolves frames through the *open address* — so with the address still
    // naming the document being left behind, every write landed on a node this
    // one does not contain, and the canvas stayed blank. Setting it first
    // means the one signal carries a consistent pair.
    //
    // The rule it appears to break — never name a document that failed to open
    // — is honoured by the `catch` below, which puts both back.
    const mountId = address.mountPath[address.mountPath.length - 1] ?? '';
    const [root, inheritedDoc] = await Promise.all([
      client.load(address.root),
      // What this mount would run with no overrides of its own — the value the
      // inspector's "overridden" badge offers to put back. Fetched with the
      // rest rather than on demand: it is one small request, and asking for it
      // at click time would make a revert fail on a flaky connection after the
      // user had already committed to it.
      client.loadMount(address, { inherited: true }),
    ]);
    workbench.controller.document.enterInstance(
      mountId,
      root.ok
        ? new MountContext(
            address,
            root.value as Record<string, unknown>,
            inheritedDoc.ok ? (inheritedDoc.value.document as Record<string, unknown>) : undefined,
          )
        : undefined,
    );
    setOpenAddress(address, slug);
    workbench.controller.document.importJSON(JSON.stringify(document));
    // **No draft restore.** A draft belongs to a document someone can save,
    // and this one is derived — the package plus this mount's overrides. There
    // is nothing here that a later Save could write back as itself.
    //
    // The autosave *key* still moves, to the address rather than the class
    // slug (`setOpenAddress`), so whatever this tab writes cannot land on the
    // package's own draft and be restored over it later.
    // **Two baselines, because two documents matter and they matter for
    // different reasons.**
    //
    // The **class** is the file that actually backs what is on screen, so its
    // changes are the ones that make this view stale.
    //
    // The **root** is the file an instance save actually *writes*: an override
    // is stored on the parent, so `WorkflowManager.handleSave` compare-and-sets
    // against `getKnownSavedAt(address.root)`. Without a baseline recorded here
    // that guard short-circuits on `baseline && …` and disables itself — so on
    // a fresh deep link to `?w=root/mount`, the first override save wrote the
    // whole retained parent document back and silently reverted any parent
    // edit made since the tab opened. The guard existed for exactly that; it
    // just never had a baseline on this path.
    const baselined = new Set<string>();
    for (const target of [slug, address.root]) {
      if (baselined.has(target)) continue;
      baselined.add(target);
      const row = await client.summary(target);
      recordKnownSavedAt(target, row.ok ? (row.value?.savedAt ?? undefined) : undefined);
    }
    return Ok({ name: workbench.model.name, restoredDraft: false });
  } catch (error) {
    // Put the address back: it was set before the import so the projection
    // would see a consistent pair, and a document that did not open must not
    // keep claiming the address bar.
    workbench.controller.document.leaveInstance();
    clearOpenAddress();
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
    // **Which document this is, recorded before the import** — the same
    // load-bearing ordering `loadMountIntoEditor` documents above, and ticket
    // 25's other half.
    //
    // `importJSON` fires `workflow:reset`, and two listeners answer it by
    // asking what is open: the canvas catch-up projection (`AskPanel`, tickets
    // 34/43/25) and the draft autosave key. With the slug still naming the
    // document being left behind, the first replayed the *previous*
    // workflow's run onto this canvas — an owner opened Morning Brief and its
    // entry card asked the Workflow Architect's question — and the second
    // wrote this document into the previous one's draft.
    //
    // Back to a package: every change is expressible again, and the tab is no
    // longer displaying an instance (ticket 42). Both are cleared here rather
    // than at each caller, because this is the one path that opens a document.
    //
    // The rule it appears to break — never name a workflow that failed to open
    // — is honoured by the `catch` below, which puts back whatever was open.
    const leaving = { slug: getOpenSlug(), address: getOpenAddress() };
    workbench.controller.document.leaveInstance();
    clearOpenAddress();
    setOpenSlug(slug);
    workbench.controller.document.importJSON(JSON.stringify(outcome.value));
    // What disk holds, for disk autosave — recorded here, and *before* the
    // draft restore below. Importing fires `controller.onChange`, which is
    // what autosave listens to, so without this baseline merely opening a
    // workflow rewrote its file with an identical document and a new
    // `savedAt`. A restored draft, by contrast, genuinely differs from the
    // file and should reach it.
    rememberDiskDocument(slug, workbench.model.name, outcome.value);
    // …and then this browser's own unsaved edits to *this* workflow, if it has
    // any that differ (ticket 23). Opening a second workflow used to discard
    // them with no prompt and no way back, because the draft was keyed on the
    // tab rather than on the document.
    const draft = restoreDraftFor(slug, workbench);
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
    // Put back what was open: the identity was recorded before the import so
    // the one `workflow:reset` signal carried a consistent pair, and a
    // document that did not open must not keep claiming the address bar.
    if (leaving.address) setOpenAddress(leaving.address, leaving.slug ?? leaving.address.root);
    else if (leaving.slug) setOpenSlug(leaving.slug);
    else clearOpenAddress();
    return Err(`Failed to import: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}
