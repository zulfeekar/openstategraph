import type { Result } from '@core/kernel/Result';
import { recordKnownDigest, recordKnownVersion } from '@app/workflowFileWatch';
import { announceWorkflowSaved } from '@app/workflowSaveBroadcast';
import { writeHostPackage } from '@app/hostPackageWrite';
import { getOpenSlug, setOpenSlug } from '@app/openWorkflow';
import { getOpenAddress } from '@app/openAddress';
import { isInstance } from '@core/model/MountAddress';
import {
  saveFailureMessage,
  type SaveFailure,
  type SaveReceipt,
  type WorkflowSummary,
} from '@core/runtime/WorkflowFileClient';
import { clearConflictStandDown, rememberDiskDocument } from '@app/diskAutosave';
import { adoptSlugForDraft, currentDraftId } from '@app/workflowDrafts';
import { duplicateNameConfirmation } from './consequences';

/**
 * Saving a workflow — the knowledge, with no surface attached.
 *
 * Extracted from `WorkflowManager.handleSave` for exactly the reason
 * `createNewWorkflow` was extracted from `handleCreate`: there is now more than
 * one way to ask for it. `say-it-on-the-surface` 01 found that the only save
 * affordance in the product lived inside a panel behind a toggle, with no
 * top-bar control and no `Mod+S`, while the thing filling the gap — autosave —
 * is **browser-local** and reaches no backend. A person who drew a flow and
 * never opened the panel had nothing on disk and no way to know it.
 *
 * The guard `createNewWorkflow` states applies here unchanged: a second entry
 * point is a **promotion** of the manager, never a second implementation of
 * it. So the button moved out and this moved here; the panel and the toolbar
 * both call this one function and differ only in how they say what happened.
 *
 * ## Three acts wear one word, and the caller must not have to know which
 *
 * `handleSave` already carried two (`ticket 20`); this adds none and hides
 * none:
 *
 * 1. **An instance is open** — what is on screen is the package plus this
 *    mount's overrides, so saving it back to the package would burn those
 *    overrides into the shared definition and hit every other mount. What is
 *    written is the **parent**. This branch is the reason a bare `Save` button
 *    is dangerous and the reason `SaveOutcome` names what it did: a toolbar
 *    that says "Saved" while writing a different document than the one on
 *    screen is a worse defect than no button at all.
 * 2. **A slug is held** — an overwrite of that package.
 * 3. **No slug** — a *creation*, and the slug comes back from the backend,
 *    never from `slugify(name)` here, which cannot see that another workflow
 *    already lives at `my-workflow`.
 */

/** Everything this needs from the runtime, and nothing else. */
export interface IWorkflowSaving {
  list(): Promise<Result<readonly WorkflowSummary[], string>>;
  summary(slug: string): Promise<Result<WorkflowSummary | null, string>>;
  /**
   * `baseDigest` is deliberately **not** in this signature
   * (`osg-agent-experience/45`). Pressing Save is the user saying *keep
   * mine*: an explicit, deliberate overwrite of whatever is on disk, which is
   * exactly the door a conflict leaves open. The version check exists for the
   * writer nobody asked for — autosave — and a Save button that could be
   * refused would leave a developer holding edits with nowhere to put them.
   */
  save(slug: string, name: string, document: unknown): Promise<Result<SaveReceipt, SaveFailure>>;
  create(name: string, document: unknown): Promise<Result<string, string>>;
}

/**
 * The document on screen, and the serializer that turns it into bytes.
 *
 * Narrower than `Workbench` on purpose (Interface Segregation): saving needs a
 * name, a way to serialise, a way to canonicalise for the autosave baseline,
 * and the mount context. Depending on the whole workbench would make this
 * untestable without one.
 */
export interface SavableWorkbench {
  readonly model: {
    readonly name: string;
    /**
     * Adopt the name the first save was given.
     *
     * Needed because the bytes are serialised from the model: without it the
     * package's `workflow.json` would carry `Untitled` while its listing row
     * and its folder carried the name the user typed — one workflow with two
     * names, which is the ambiguity `07` spent a ticket removing.
     *
     * Deliberately **not** routed through `RenameWorkflowCommand`. A command
     * is undoable, and the slug this name mints is frozen the instant the
     * backend answers; an undo that walked the name back to `Untitled` while
     * `workflows/customer-triage/` stayed put would manufacture exactly that
     * disagreement. The rename is a consequence of the save, not a canvas
     * gesture, so it does not belong in the canvas's history.
     */
    setName(name: string): void;
  };
  readonly serializer: {
    toJSONString(model: SavableWorkbench['model']): string;
    canonicalise(document: unknown): unknown;
    /** Which types' sizes a write is not worth — see `diskAutosave.comparable`. */
    sizeIsMeasured(typeId: string): boolean;
  };
  readonly controller: {
    readonly document: { mountContext(): MountContext | null | undefined };
  };
}

interface MountContext {
  readonly rootDocument: Record<string, unknown>;
}

/**
 * What happened, named — never a bare boolean.
 *
 * Every caller has to be able to say the *right* sentence, and the three acts
 * above produce three different true sentences. `created` carries the minted
 * slug because it is the one thing the user could not have predicted: a second
 * "My Workflow" lands at `my-workflow-k7m3qp`, and silently is how you later
 * wonder which of two rows is yours.
 */
export type SaveOutcome =
  | { readonly kind: 'created'; readonly slug: string; readonly name: string }
  | { readonly kind: 'saved'; readonly slug: string; readonly name: string }
  | { readonly kind: 'overrides'; readonly root: string }
  | { readonly kind: 'cancelled'; readonly name: string }
  | { readonly kind: 'refused'; readonly message: string };

export interface SaveDeps {
  readonly client: IWorkflowSaving;
  readonly workbench: SavableWorkbench;
  /**
   * How this surface asks a yes/no question. Injected rather than calling
   * `confirm` here so the act is testable without a DOM — and so a surface
   * that has a better dialog than the browser's can supply one.
   */
  readonly confirm: (message: string) => boolean;
  /**
   * How this surface asks for the name a new package will carry — returning
   * `null` when the person dismissed the question.
   *
   * Required, with no default, on purpose. A default would let a fourth
   * surface reach `create` without asking, which is the exact defect
   * `say-it-on-the-surface/09` was filed for: the slug is minted here and
   * frozen for the life of the directory, so every path that can mint one has
   * to say out loud how it asks. Injected like `confirm` beside it, for the
   * same two reasons — testable without a DOM, and replaceable by a surface
   * with a better dialog than the browser's.
   */
  readonly promptName: (suggestion: string) => string | null;
}

/**
 * The sentence above the box, and the one thing a user is never otherwise
 * told.
 *
 * `03` removed this vocabulary problem from the mount field: a slug is a
 * machine name nobody explained. The other half is that it is *minted from
 * what you type here and then frozen*, because a slug that moves renames a
 * directory — so this is the last moment the answer is free. Two sentences,
 * because a dialog nobody reads is a dialog that did not happen; the length is
 * pinned in `aFirstSaveAsksForAName.test.ts` rather than left to taste.
 */
export function namePromptMessage(): string {
  return 'Name this workflow. The name becomes its folder on the backend and cannot be changed later.';
}

export async function saveWorkflow({
  client,
  workbench,
  confirm,
  promptName,
}: SaveDeps): Promise<SaveOutcome> {
  const address = getOpenAddress();
  if (address && isInstance(address)) {
    const mounts = workbench.controller.document.mountContext();
    if (!mounts) {
      return {
        kind: 'refused',
        message: 'This mount has no parent loaded, so there is nowhere to save its overrides.',
      };
    }
    // **Through the seam, not beside it** (`production-ready` 102). The
    // compare-and-set on the parent's `saved_at` — the file watch follows the
    // *class* while an instance is open, so nothing else notices the parent
    // moving — the write, the draft supersede 101 was filed for, and the
    // baseline adoption are one protocol, and this branch used to carry its
    // own copy of it. A third writer of a host package now gets all four by
    // construction instead of by review.
    const outcome = await writeHostPackage(client, {
      address,
      rootDocument: mounts.rootDocument,
    });
    if (outcome.kind === 'refused') return { kind: 'refused', message: outcome.reason };
    if (outcome.kind === 'failed')
      return { kind: 'refused', message: `Could not save: ${outcome.error}` };
    return { kind: 'overrides', root: outcome.root };
  }

  const open = getOpenSlug();
  // **The name the package will carry**, which on a create is not necessarily
  // the one the document is wearing (`say-it-on-the-surface/09`).
  let name = workbench.model.name;
  if (!open) {
    // Ask *before* the clash check below, because the answer is what the
    // clash is against. Asking afterwards would have warned about the default
    // and then missed a genuine collision with the word actually typed.
    const answer = promptName(name);
    // Dismissal and blank are one branch. `slugify('')` falls back to
    // `workflow`, so an empty answer does not fail — it quietly mints
    // `workflows/workflow/`, which is a worse outcome than not saving.
    if (answer === null || answer.trim() === '') {
      return { kind: 'cancelled', name };
    }
    name = answer.trim();
    // Before the serialise below, so the document, the listing row and the
    // folder all carry one name.
    workbench.model.setName(name);

    // A create, not an overwrite, is the one path that can mint a second
    // package of a name that already has one — and it used to do so in
    // silence, which is how a review ended with three "AI Workflow"s
    // (the-editor-makes-a-real-package 07). Still allowed, just announced.
    const listing = await client.list();
    const wanted = name.trim().toLocaleLowerCase();
    const clashes = (listing.ok ? listing.value : [])
      .filter((row) => row.name.trim().toLocaleLowerCase() === wanted)
      .map((row) => row.slug);
    if (clashes.length > 0 && !confirm(duplicateNameConfirmation(name, clashes))) {
      return { kind: 'cancelled', name };
    }
  }

  const document = JSON.parse(workbench.serializer.toJSONString(workbench.model)) as unknown;
  let slug = open;
  let failure: string | null = null;
  // The version this Save produced, adopted below so autosave — which may have
  // stood down over a conflict this Save has just settled — quotes the file's
  // real digest on the next edit rather than the one it loaded with.
  let adopted: string | undefined;
  if (open) {
    const outcome = await client.save(open, name, document);
    if (!outcome.ok) failure = saveFailureMessage(outcome.error);
    else adopted = outcome.value.digest;
  } else {
    const outcome = await client.create(name, document);
    if (outcome.ok) slug = outcome.value;
    else failure = outcome.error;
  }
  if (failure !== null || slug === null) {
    return {
      kind: 'refused',
      message: `Could not save: ${failure ?? 'the runtime did not name the new workflow'}`,
    };
  }

  // **Ticket 49, and it must come before `setOpenSlug`.** This is the one
  // moment a document acquires an identity, so it is the one moment its draft
  // can follow — a graph drawn before any save autosaves under a minted
  // `wf-<timestamp>` key, and `setOpenSlug` below moves the autosave key to
  // `slug-<slug>` from that instant on. Without the rename in between, the key
  // the next page load reads points at nothing while the user's bytes sit
  // under a name nobody will ever ask for again: press Save, press ⌘R, and the
  // canvas comes back empty.
  adoptSlugForDraft(currentDraftId(), slug);
  // Storage *and* the address bar — a workflow that has just become real on
  // the backend is linkable from this moment on.
  setOpenSlug(slug);
  // Autosave refuses to write a package it has no baseline for, so an explicit
  // save has to leave one behind — otherwise a workflow saved for the first
  // time here would never autosave again, which is precisely the moment a
  // developer starts expecting it to.
  rememberDiskDocument(slug, name, document, workbench.serializer);
  // *Keep mine*, answered (`osg-agent-experience/45`): this Save has just
  // overwritten the file deliberately, so opening the workflow again is an
  // ordinary open and must restore this browser's draft as it always does.
  clearConflictStandDown(slug);
  // This tab's own write — recorded as known-good so the file watch never
  // mistakes this save for an external change. Read back by slug, not looked up
  // in a refreshed listing: a hidden package is not in that listing, so saving
  // one used to record no baseline at all (ticket 21).
  const row = await client.summary(slug);
  recordKnownVersion(slug, row.ok ? row.value : null);
  // The receipt wins over the row when there is one: it is the digest of the
  // bytes this save wrote, while the row is a second read that another writer
  // could already have overtaken (`osg-agent-experience/45`).
  recordKnownDigest(slug, adopted);
  // The other tabs of this browser, given the head start the SSE stream cannot
  // (`osg-agent-experience/69`). `adopted ?? row` for the same reason the two
  // lines above are in that order: the receipt is the digest of the bytes this
  // save wrote, and the row is a second read somebody could already have
  // overtaken. A create has no receipt, and announcing it is still right — a
  // sibling tab that has this brand-new slug open is exactly the case a
  // duplicate-and-open produces.
  announceWorkflowSaved(slug, adopted ?? (row.ok ? row.value?.digest : undefined));

  return open ? { kind: 'saved', slug, name } : { kind: 'created', slug, name };
}

/**
 * The sentence a surface says, derived from the outcome rather than written
 * twice.
 *
 * The panel and the toolbar must not be able to describe one act two ways —
 * the same reason `HIDDEN_PACKAGE_NOTE` is one constant. In particular the
 * instance branch says *whose* document was written, because that is the one
 * case where the answer is not the document on screen.
 */
export function saveMessage(outcome: SaveOutcome): string | null {
  switch (outcome.kind) {
    case 'created':
      return `Created: ${outcome.name} (${outcome.slug})`;
    case 'saved':
      return `Saved: ${outcome.name}`;
    case 'overrides':
      return `Saved this mount's overrides to ${outcome.root}`;
    case 'refused':
      return outcome.message;
    case 'cancelled':
      // **Not silent** (`say-it-on-the-surface` 02). A dismissed `confirm`
      // used to return nothing at all, so pressing Save and answering "no"
      // left a user with a document that had not saved and no statement that
      // anything had happened — indistinguishable from a broken button, and
      // one of the four ways this product could refuse to add a workflow
      // without naming a rule. Worse in the case nobody chooses: a browser
      // that suppresses dialogs answers "no" on the user's behalf.
      return `Not saved — that would have created a second workflow named "${outcome.name}".`;
  }
}

/** True when the save reached the backend. Used to decide whether to refresh. */
export function saveSucceeded(outcome: SaveOutcome): boolean {
  return outcome.kind === 'created' || outcome.kind === 'saved' || outcome.kind === 'overrides';
}
