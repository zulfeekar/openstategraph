import type { Workbench } from './Workbench';
import { subscribeOpenSlug } from './openWorkflow';
import {
  claimHolder,
  deleteWorkflow,
  handOverWorkflow,
  moveWorkflow,
  readWorkflow,
  type KeyValueStore,
  type WriteGuard,
} from './workflowStore';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';

/**
 * A browser-local draft **per workflow**, instead of one per tab.
 *
 * ## The defect
 *
 * Autosave keyed its entry on a synthetic `wf-<timestamp>` id belonging to the
 * *tab*, not to the document. So opening a second workflow — a normal thing to
 * do mid-edit, and something the Workflows panel actively invites — pointed
 * that one key at a different document and the previous draft became
 * unreachable. No prompt, no warning, no undo entry, no diagnostic: the only
 * feedback was a neutral *"Opened: Chinook Assistant"* toast.
 *
 * The Workflows panel's promise made it worse by being precise:
 *
 * > Edits autosave to **this browser only** — they are not on the backend and
 * > will not follow you to another browser, another machine, or survive
 * > clearing site data.
 *
 * Every way of losing work named there is a different browser, a different
 * machine, or clearing site data. Opening a second workflow in the same tab is
 * none of those, and it lost work anyway. A plain reload preserved the draft,
 * which is what made the behaviour so hard to predict.
 *
 * ## The fix, and why it is keying rather than prompting
 *
 * The ticket allowed either. A prompt only covers the paths the editor can
 * intercept — it cannot appear for the address-bar navigation that found this,
 * because the page is already gone. Keying the draft on the slug covers every
 * path at once and asks the user nothing: your unsaved edits to *this*
 * workflow are still there when you come back to *this* workflow.
 *
 * Two collaborating parts, and both are needed:
 *
 * 1. **`draftIdForSlug`** — the autosave key follows the open slug
 *    (`useWorkflowSession` re-keys through `subscribeOpenSlug`), so editing
 *    workflow B can never overwrite workflow A's draft.
 * 2. **`restoreDraftFor`** — opening a workflow prefers this browser's newer
 *    draft over the file, and says so.
 */

/**
 * The storage id a slug's draft lives under.
 *
 * Prefixed rather than bare so it can never collide with a `wf-<timestamp>` id
 * minted before this existed, and so `listWorkflows` still shows both.
 */
export function draftIdForSlug(slug: string): string {
  return `${SLUG_DRAFT_PREFIX}${slug}`;
}

const SLUG_DRAFT_PREFIX = 'slug-';

/**
 * The slug a draft id names, or `null` when the id names no workflow.
 *
 * The inverse of `draftIdForSlug`, and the reason it is exported: the storage
 * sweep has to tell a draft that *has* an identity — and can therefore be
 * compared against the backend's listing — from a `wf-<timestamp>` scratch
 * draft, which never had one and never can be orphaned.
 */
export function slugOfDraftId(id: string): string | null {
  return id.startsWith(SLUG_DRAFT_PREFIX) ? id.slice(SLUG_DRAFT_PREFIX.length) : null;
}

/**
 * Where a tab records which draft key it is writing under.
 *
 * Lives here, with `draftIdForSlug`, rather than privately inside the hook that
 * happens to write it: three modules now need to agree on the answer — the
 * session hook, the Save that renames it, and any test that simulates a
 * reload — and a constant known to one of them was how the rename came to be
 * missed in the first place.
 */
export const DRAFT_SESSION_KEY = 'openstategraph-current-workflow-id';

/** The draft key this tab is writing under, or `null` before one is settled. */
export function currentDraftId(): string | null {
  try {
    return sessionStorage.getItem(DRAFT_SESSION_KEY);
  } catch {
    return null; // sessionStorage throws in restricted contexts
  }
}

/**
 * Move this tab's draft onto `slug`'s key — **ticket 49**, and the moment it
 * is called is the whole of its correctness.
 *
 * ## What went wrong
 *
 * A document with no slug autosaves under a minted `wf-<timestamp>` id. Saving
 * it for the first time mints a slug on the backend, and `setOpenSlug` moves
 * the autosave key to `slug-<slug>` from that instant on — but the draft
 * already written stayed where it was. So immediately after the one gesture
 * that is supposed to make work durable, the key the editor reads on the next
 * page load pointed at nothing, and the bytes it wanted sat under a name
 * nobody would ever ask for again.
 *
 * ## Why not simply do this whenever the open slug changes
 *
 * Because the open slug moves for two different reasons and only one of them
 * is this one. Opening a *second* workflow also moves it — and moving the
 * draft along would take the scratch document the user was editing and file it
 * as the opened workflow's unsaved edits, which the load path would then
 * restore over the file it had just fetched. That is ticket 23's data loss
 * with the arrow reversed, and it would be exactly as silent.
 *
 * So the guard is not a timing heuristic; it is a statement about identity. A
 * key that is already `slug-…` belongs to a document that *has* an identity,
 * and such a draft is never re-filed under a different one. Only a key that
 * names no document — the minted `wf-<timestamp>` — can acquire one, and it
 * can do so exactly once. An occupied destination is refused by
 * `moveWorkflow`, so a slug's own draft can never be overwritten either.
 *
 * Returns whether anything moved, so a caller can tell "renamed" from "there
 * was nothing to rename" — the ordinary case when a save overwrites a package
 * this tab already had open.
 */
export function adoptSlugForDraft(
  previousId: string | null,
  slug: string,
  store: KeyValueStore = browserStore(),
): boolean {
  if (previousId == null || previousId === '') return false;
  if (previousId.startsWith(SLUG_DRAFT_PREFIX)) return false;
  return moveWorkflow(store, previousId, draftIdForSlug(slug));
}

/**
 * Keep this tab's autosave key following whatever it has open — **including
 * when it has nothing open.**
 *
 * ## Why the null case is the whole function
 *
 * Ticket 23 gave the key a rule: it follows the open workflow, so editing B can
 * never overwrite A's draft. The listener that implements it began
 * `if (slug == null) return;`, and that is the announcement `clearOpenSlug`
 * makes — the one that means *this document has no identity any more*. So on
 * `New`, the one gesture whose entire point is starting something that is not
 * the last workflow, the key kept the last workflow's identity. The new
 * document autosaved as that package's unsaved edits and was restored over it
 * on the next visit; the file was then written through the ordinary path
 * (`production-ready` 77, the other half of 71).
 *
 * Every other branch of that listener was right. The null case had simply
 * never been given an answer, and a bare `return` reads like one.
 *
 * ## What it does, and the two things it must not do
 *
 * A subject re-keys to `slug-<subject>` and re-baselines the write guard
 * against the stored draft — the tab is adopting a key whose stored version it
 * has just been shown. No subject mints a fresh `wf-<timestamp>`, the state a
 * never-saved document is supposed to be in and the one `adoptSlugForDraft` is
 * written to accept.
 *
 * **The previous draft is not moved and not deleted.** Both are somebody's
 * unsaved work, and `adoptSlugForDraft` states at length why re-filing a
 * scratch document under another identity is ticket 23's data loss with the
 * arrow reversed. The new document simply stops writing into it.
 *
 * Registered here rather than inline in the hook so the rule is reachable
 * without a DOM: the test drives `setOpenSlug`/`clearOpenSlug` through the
 * real channel and leaves only React out.
 */
export function followOpenSubjectWithDraftKey(
  writer: WriteGuard,
  onId: (id: string) => void,
  store: KeyValueStore = browserStore(),
  mintId: () => string = () => `wf-${Date.now()}`,
): () => void {
  return subscribeOpenSlug((subject) => {
    const id = subject == null ? mintId() : draftIdForSlug(subject);
    // Nothing has been seen under a freshly minted key, and saying otherwise
    // would have the write guard declare a conflict against a draft that does
    // not exist.
    writer.lastSeenAt = subject == null ? null : draftSavedAt(subject, store);
    try {
      sessionStorage.setItem(DRAFT_SESSION_KEY, id);
    } catch {
      // Storage unavailable; the id handed to `onId` is still correct for this
      // session, which is what autosave actually writes under.
    }
    onId(id);
  });
}

/**
 * Drop this browser's draft of a package it has just written to disk itself —
 * **`production-ready` 101**, and the one line between a saved override and a
 * deleted one.
 *
 * ## What a draft means, and when it stops meaning it
 *
 * A draft is *this browser's unsaved edits to a package*. Drilling into a
 * mount breaks that: the mount's overrides live on the **parent**, so a Save
 * mount — and the drill-in's own autosave — write the parent's file while the
 * parent is not the document on screen and has no editor of its own. From that
 * instant the parent's draft is not unsaved work. It is a mirror of a version
 * this browser has itself superseded, and `restoreDraftFor` will faithfully
 * put it back over the file on the way out.
 *
 * That is exactly what it did. Measured with md5: Save mount inside `m2` wrote
 * both overrides to `front-desk/workflow.json`, **← Back** re-read that file
 * correctly, the draft written when the parent was first opened was restored
 * over it, and `writeOpenWorkflowToDisk` — which writes documents *whole* —
 * turned the absence in memory into a deletion on disk.
 *
 * ## Why a delete, and why not a timestamp
 *
 * Not a timestamp, because `restoreDraftFor` says at length why it compares
 * canonical bytes and not clocks, and the clocks here belong to two different
 * machines. *Which package this browser just wrote* needs no clock at all.
 *
 * A delete rather than a rewrite because the draft has nothing left to say:
 * the host document that was just written is the file, and the next edit to
 * the parent mints a fresh draft from it. Nothing recoverable is thrown away
 * that the write itself had not already replaced — the host document is the
 * one this browser loaded from that same file when the drill-in began.
 *
 * **Called from exactly one place**, and that is `production-ready` 102 rather
 * than a detail: until then it was called from *both* host writers by
 * convention, which a third writer would have joined only if its author knew
 * to. The whole host-write protocol now lives in `app/hostPackageWrite`, and
 * this rule is one of its four steps. Do not call it from anywhere else —
 * `aThirdHostWriterCannotForget.test.ts` says so out loud, and the reason is
 * that a supersede *without* the write beside it deletes unsaved work.
 */
export function supersedeDraftAfterHostWrite(
  root: string,
  store: KeyValueStore = browserStore(),
): void {
  deleteWorkflow(store, draftIdForSlug(root));
}

/**
 * Drop this browser's draft of a package that was just deleted on the
 * backend — **`launch-readiness` 95**, corrected by **`launch-readiness` 148**.
 *
 * ## The orphan (95)
 *
 * A draft is keyed `slug-<slug>` (`draftIdForSlug`), and deleting a workflow
 * from the Workflows panel only ever called the backend's `remove(slug)` — it
 * never touched this browser's own copy. The key survived the delete, sitting
 * in `localStorage` under the exact name the *next* workflow with that slug
 * would mint, because slugs are derived from titles and re-using a title
 * (`"Chinook Assistant"`, say) re-mints the same slug. So a re-created
 * workflow of the same name silently inherited a stranger's leftover draft.
 *
 * ## The tab this was reaching into (148)
 *
 * `localStorage` belongs to the **origin**, not to the tab. Every tab of the
 * editor shares one, so an unconditional `deleteWorkflow` here was a delete
 * performed on every tab at once — and one of them may have been holding
 * unsaved work. Reproduced live: type in tab B, delete from tab A's panel, and
 * B's draft key is `absent`, which is why B's next reload landed on a blank
 * canvas. Unsaved work destroyed by a gesture in a different window, with no
 * prompt and no undo.
 *
 * **The reconciliation is not tab-scoping.** A draft is per *workflow* and has
 * been since ticket 23 — see this module's own header — and `96` exists
 * precisely because a draft is *"the only copy of someone's work"* and must
 * outlive the tab that made it. Moving drafts to `sessionStorage` would answer
 * 96 by doing the thing 96 refused to do: lose them on a tab close. So drafts
 * stay origin-scoped, and the *remover* learns the boundary instead.
 *
 * ## What it reads, and why the claim is the right signal
 *
 * The origin already records which draft each live tab is editing:
 * `claimSession` writes a claim on a ten-second heartbeat and it goes stale in
 * thirty. So a live claim on this slug's draft, held by a tab that is not this
 * one, is the origin saying *somebody is typing into this right now*. That is
 * exactly the case 148 is about, and it is the only case where the draft is
 * kept.
 *
 * `thisTabsDraftId` is what separates *my* draft from *theirs*: a claim on a
 * key this tab is itself writing under is this tab's own, and its own draft is
 * still discarded, because the user asked for this delete and `147` has
 * already released the slug. Passed in rather than read from `sessionStorage`
 * inside, so a test can drive two tabs against one store — which is the only
 * kind of test that can fail against this defect.
 *
 * Returns a decision rather than nothing, because *"your other tab still has
 * unsaved edits to that"* is a sentence the user is owed. Called from one
 * place, mirroring `supersedeDraftAfterHostWrite`'s discipline.
 */
export interface DraftDiscardDecision {
  readonly discarded: boolean;
  /** Why it was kept. Absent when it was discarded. */
  readonly reason?: 'another-tab-is-editing';
}

/**
 * The rule, with every ambient fact already read — `say-it-on-the-surface`
 * 07's shape, for the same reason: the case that must **not** fire is a race
 * between two browser tabs, and a decision expressed as data can be tested
 * at any clock.
 */
export function decideDraftDiscard(input: {
  readonly draftId: string;
  readonly thisTabsDraftId: string | null;
  readonly liveClaimHolder: string | null;
}): DraftDiscardDecision {
  if (input.liveClaimHolder == null) return { discarded: true };
  if (input.draftId === input.thisTabsDraftId) return { discarded: true };
  return { discarded: false, reason: 'another-tab-is-editing' };
}

export function discardDraftAfterDelete(
  slug: string,
  store: KeyValueStore = browserStore(),
  thisTabsDraftId: string | null = currentDraftId(),
  nowMs: () => number = () => Date.now(),
): DraftDiscardDecision {
  const draftId = draftIdForSlug(slug);
  const decision = decideDraftDiscard({
    draftId,
    thisTabsDraftId,
    liveClaimHolder: claimHolder(store, draftId, nowMs),
  });
  if (decision.discarded) deleteWorkflow(store, draftId);
  return decision;
}

/**
 * Carry this tab's draft onto the fresh key it was just re-keyed to —
 * **`launch-readiness` 153**, and the mirror of `adoptSlugForDraft`.
 *
 * ## What was missing
 *
 * `147` releases the open slug when a tab is told its workflow was deleted
 * elsewhere, which re-keys autosave to a minted `wf-<timestamp>`. Autosave
 * writes nothing until the next edit, so between the delete and that edit the
 * document exists only in memory — the `slug-<slug>` draft is not this tab's
 * any more and the new key holds nothing. A reload showed a blank canvas while
 * the work sat in `localStorage` under a name nobody would ask for again.
 * Recoverable, never destroyed; what was missing is the route back.
 *
 * ## Why this does not break `adoptSlugForDraft`'s rule
 *
 * That rule reads: *a draft that already has an identity is never re-filed
 * under another one*, because doing it on an ordinary open-slug change would
 * file the scratch document the user is editing as the opened workflow's
 * unsaved edits. This is the mirror case and the rule is intact rather than
 * bent — the identity has **ceased to exist**. The package is gone, a slug is
 * frozen and cannot be re-taken, and the destination is a key that names *no*
 * document at all, which is the one direction that rule leaves open. Nothing is
 * ever carried onto another `slug-…` key: that is asserted here, not assumed.
 *
 * ## Who may carry it
 *
 * Only the tab writing under that key. `148` established that a draft is
 * origin-scoped and only its own tab may drop it; the same boundary decides
 * this, in the other direction. `previousDraftId` is read by the caller
 * **before** the re-key, because afterwards this tab's key is the new one and
 * the question can no longer be asked.
 *
 * The live claim is deliberately *not* consulted, unlike `decideDraftDiscard`.
 * A claim is keyed by draft id, so two tabs on one slug write one claim and it
 * cannot separate them — and the answer is safe either way, because this
 * deletes nothing: a second tab arriving after the first finds nothing to move,
 * keeps the document on its own canvas, and can still Save it as a new package.
 */
export interface DraftCarryDecision {
  readonly carried: boolean;
  /** Why it was not carried. Absent when it was. */
  readonly reason?: 'not-this-tabs-draft' | 'no-fresh-key' | 'nothing-to-carry';
}

/** The rule, pure, with the two keys already read (`decideDraftDiscard`'s shape). */
export function decideDraftCarry(input: {
  readonly draftId: string;
  readonly thisTabsDraftId: string | null;
}): DraftCarryDecision {
  if (input.draftId !== input.thisTabsDraftId) {
    return { carried: false, reason: 'not-this-tabs-draft' };
  }
  return { carried: true };
}

export function carryDraftToFreshKey(
  slug: string,
  previousDraftId: string | null,
  nextDraftId: string | null,
  store: KeyValueStore = browserStore(),
): DraftCarryDecision {
  const draftId = draftIdForSlug(slug);
  const decision = decideDraftCarry({ draftId, thisTabsDraftId: previousDraftId });
  if (!decision.carried) return decision;
  // A key that names a workflow is never a destination — see above, and
  // `adoptSlugForDraft` for the loss that rule exists to prevent.
  if (nextDraftId == null || nextDraftId === '' || slugOfDraftId(nextDraftId) != null) {
    return { carried: false, reason: 'no-fresh-key' };
  }
  if (!handOverWorkflow(store, draftId, nextDraftId)) {
    return { carried: false, reason: 'nothing-to-carry' };
  }
  return { carried: true };
}

/** Whether this browser holds a draft for `subject` (a slug or an address). */
export function hasDraftFor(subject: string | null, store?: KeyValueStore): boolean {
  return (
    subject !== null && subject !== '' && draftSavedAt(subject, store ?? browserStore()) !== null
  );
}

/**
 * When this browser's draft of `slug` was written, or `null` if there is none.
 *
 * This is the **write guard's baseline**, and forgetting it is not cosmetic.
 * `saveWorkflow` refuses to write when the stored payload is newer than the
 * version this tab last saw — a compare-and-set that stops one tab clobbering
 * another's work. With a per-tab key that question never arose, because the
 * key was fresh every time. With a per-slug key it arises on every navigation:
 * the draft in storage was written by the *previous page load*, which had a
 * different `writerId` and a later `savedAt`, so an unbaselined tab declares a
 * conflict against itself and stops autosaving — announcing that another tab
 * saved more recently when no other tab exists.
 *
 * A tab that is about to load a draft has, by any honest reading, *seen* it.
 * Call this whenever the autosave key adopts a slug.
 */
export function draftSavedAt(slug: string, store: KeyValueStore = browserStore()): string | null {
  const draft = readWorkflow(store, draftIdForSlug(slug));
  return draft.status === 'ok' ? draft.savedAt : null;
}

/**
 * What actually reached the canvas when a page load tried to restore a draft.
 *
 * **A report, not a plan, and the distinction is `production-ready` 71.** The
 * startup hook used to carry `session.shouldRestore` — the *intent* — into the
 * decision about whether disk autosave may write the open package. With a slug
 * surviving in `sessionStorage` and the draft gone, that intent is `true`,
 * nothing is imported, the canvas stays blank, and the package was handed to
 * autosave anyway. The next edit wrote an empty document over a real workflow,
 * with no Save pressed and nothing said.
 *
 * So this is a distinct **type**, not a boolean, and `baselineSlugAfterRestore`
 * accepts only this. Passing the plan is a compile error rather than a data
 * loss, which is the only version of this guard that cannot rot — the comment
 * describing the hazard was already correct and already there, and the code
 * disagreed with it for as long as nobody re-read both.
 */
export interface DraftRestoreReport {
  /** True only when a document was parsed, imported, and is on screen. */
  readonly restored: boolean;
  /** What to tell the user, when something was wrong with the stored bytes. */
  readonly notice?: string;
}

/**
 * Put this browser's draft for `plan.id` on screen, and report what happened.
 *
 * Every outcome other than a successful import is `restored: false`, including
 * the two recoverable ones — bytes that will not parse (quarantined by the
 * reader, which supplies the notice) and a document this build cannot import.
 * In both the canvas keeps what it already had, which is the right recovery
 * and is emphatically **not** a restore.
 */
export function restoreSessionDraft(
  plan: { readonly id: string; readonly shouldRestore: boolean },
  workbench: Workbench,
  writer: WriteGuard,
  store: KeyValueStore = browserStore(),
): DraftRestoreReport {
  if (!plan.shouldRestore) return { restored: false };

  const outcome = readWorkflow(store, plan.id);
  // Recovered, not crashed: whatever is already on screen stays, the bad bytes
  // are quarantined by the reader, and the user is told.
  if (outcome.status === 'corrupt') return { restored: false, notice: outcome.reason };
  if (outcome.status !== 'ok') return { restored: false };

  // Remember which version we restored. Without this the first autosave cannot
  // tell its own lineage from another tab's newer write.
  writer.lastSeenAt = outcome.savedAt;
  try {
    // Same ordering requirement as the named-file Load path: a workflow-scoped
    // node type must be registered *before* import, or `fromJSON` silently
    // skips every node of that type.
    registerNodeTypesForRawDocument(
      JSON.parse(outcome.json),
      workbench.registry,
      workbench.engine.executors,
    );
    workbench.controller.document.importJSON(outcome.json);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return {
      restored: false,
      notice:
        `The autosaved workflow could not be restored (${detail}). ` +
        'The editor has started from a blank workflow; nothing was deleted.',
    };
  }
  return { restored: true };
}

export interface DraftRestoreOutcome {
  /** True when the draft differed from the file and was loaded instead. */
  readonly restored: boolean;
}

/**
 * Loads this browser's draft of `slug` over the document currently in the
 * model, when there is one and it differs.
 *
 * **Call it immediately after importing the file, never instead of.** The file
 * import is what registers the workflow's capabilities and establishes the
 * canonical text to compare against; this only decides whether the user's own
 * unsaved version supersedes it.
 *
 * **Comparison is by canonical bytes, not by timestamp.** Both documents are
 * put through the same serializer, so the question asked is "does this draft
 * actually differ from what is on disk" rather than "which clock is ahead" —
 * and a draft written by a browser whose clock is wrong cannot silently win or
 * silently lose. A draft equal to the file is not a restore at all; it is the
 * ordinary case after a save, and it must stay silent.
 */
export function restoreDraftFor(
  slug: string,
  workbench: Workbench,
  store: KeyValueStore = browserStore(),
): DraftRestoreOutcome {
  const draft = readWorkflow(store, draftIdForSlug(slug));
  // `corrupt` is reported by the reader, which quarantines the bytes; the file
  // the editor just loaded stays, which is the right recovery.
  if (draft.status !== 'ok') return { restored: false };

  const fromFile = workbench.controller.document.exportJSON();

  let parsed: unknown;
  try {
    parsed = JSON.parse(draft.json);
  } catch {
    return { restored: false };
  }

  // Same ordering requirement as every other import path: a workflow-scoped
  // type has to be registered before its nodes can be created as themselves.
  registerNodeTypesForRawDocument(parsed, workbench.registry, workbench.engine.executors);
  const outcome = workbench.controller.document.importJSON(draft.json);
  if (!outcome.ok) {
    // An unreadable draft must not cost the user the file they asked for.
    workbench.controller.document.importJSON(fromFile);
    return { restored: false };
  }

  if (workbench.controller.document.exportJSON() === fromFile) return { restored: false };
  return { restored: true };
}

/**
 * `localStorage`, or a store that holds nothing when there is none.
 *
 * The default rather than a required argument because every real caller wants
 * browser storage, and the one context that has none — a test or any non-DOM
 * host — wants "this browser has no drafts", which is exactly true and is not
 * an error to report. A null object says that in one place instead of a
 * `typeof localStorage` check at each call site.
 */
function browserStore(): KeyValueStore {
  if (typeof localStorage !== 'undefined') return localStorage;
  return {
    length: 0,
    key: () => null,
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  };
}
