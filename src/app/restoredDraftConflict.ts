/**
 * What a reload does when the file moved under the draft it is restoring.
 *
 * ## The failure this exists for
 *
 * `osg-agent-experience/68`, a data-loss blocker. A tab left open overnight on
 * a package, a CLI session rewriting that package's `workflow.json` in the
 * morning, and then a reload of the tab: the editor restored the tab's own
 * draft and wrote it straight back over the file. Sixty-seven nodes, four
 * edges gone, `data` changed on ten of them — the pre-rewrite content,
 * resurrected. Nothing was lost only because the file was under git.
 *
 * No gesture caused that write. `importJSON` on the restore fires
 * `controller.onChange`, which is what disk autosave listens to, so the reload
 * itself was the edit.
 *
 * ## Why it is a question rather than a rule
 *
 * The two documents are both somebody's work. The draft is this browser's
 * unsaved edits, which is the loss drafts exist to prevent
 * (`osg-agent-experience/23`); the file is what a colleague, an agent or a
 * `git pull` put there, which is the loss this ticket is about. Preferring
 * either one silently is how one of the two gets destroyed, and the editor is
 * not the one who knows which is wanted — the same call `diskConflictNotice`
 * makes for the save path, in the same words.
 *
 * So the decision is a comparison with three answers and no default that
 * writes. `draftIsStale`'s clock comparison is deliberately not used: a
 * browser whose clock is wrong would silently win or silently lose, which is
 * the argument `restoreDraftFor` already records for comparing bytes.
 */

/**
 * Why the question is being asked — `osg-agent-experience/69`.
 *
 * Two occasions, one dialog. `restored-draft` is `68`'s: a reload found the
 * file had moved under the draft it was about to restore. `changed-elsewhere`
 * is this tab sitting open while another tab, the CLI or a coding agent
 * rewrote the file underneath it.
 *
 * A field rather than a second offer type, and a second dialog was explicitly
 * refused: the *choice* is identical — this browser's unsaved edits against
 * the bytes on disk, with nothing written until the user answers — and two
 * dialogs would be two places for that choice to drift, on the one screen
 * standing between two versions of somebody's work. What differs is one
 * sentence of explanation, which is why the cause reaches
 * `restoredDraftChoiceCopy` and nothing else.
 */
export type RestoredDraftCause = 'restored-draft' | 'changed-elsewhere';

/** Which document a mount of this offer is about, once the user answers. */
export interface RestoredDraftOffer {
  readonly slug: string;
  readonly cause: RestoredDraftCause;
  /** The file exactly as the backend served it — what *take the file* loads. */
  readonly file: unknown;
  /** The name the file carries, so the offer can say what it is offering. */
  readonly fileName: string;
}

export type RestoredDraftDecision =
  /** Draft and file are the same document: baseline it and say nothing. */
  | { readonly kind: 'baselined' }
  /** They differ: write nothing, and put the choice in front of the user. */
  | { readonly kind: 'ask' }
  /**
   * The file could not be read. Distinct from `ask` because there is nothing
   * to offer and distinct from `baselined` because a failed read must never
   * become a blind write — a caller that folded them together would either
   * lose the draft or overwrite a file it never saw.
   */
  | { readonly kind: 'stood-down' };

/**
 * The comparison, on the two canonical forms the caller has already reduced.
 *
 * Strings rather than documents because the reduction is not this module's
 * knowledge: `diskAutosave` owns which fields count as an edit (a measured
 * `size` does not) and both sides must go through the same rules or every
 * reload would ask.
 */
export function decideRestoredDraft(
  fileComparable: string | null,
  draftComparable: string,
): RestoredDraftDecision {
  if (fileComparable === null) return { kind: 'stood-down' };
  return fileComparable === draftComparable ? { kind: 'baselined' } : { kind: 'ask' };
}

/**
 * The offer currently awaiting an answer, and the one place that holds it.
 *
 * Module state rather than React state because the question is raised inside
 * `WorkbenchContext`'s autosave effect — before any dialog exists — and
 * answered by a component several levels away. The same arrangement
 * `openAddress` and `drillStack` use, and for the same reason: a page-load
 * fact that outlives the render which discovered it.
 */
let pending: RestoredDraftOffer | null = null;
const listeners = new Set<() => void>();

function announce(): void {
  for (const listener of [...listeners]) listener();
}

export function offerRestoredDraftChoice(offer: RestoredDraftOffer): void {
  pending = offer;
  announce();
}

export function pendingRestoredDraftChoice(): RestoredDraftOffer | null {
  return pending;
}

/** The user answered, or a test is starting over. */
export function clearRestoredDraftChoice(): void {
  pending = null;
  announce();
}

export function subscribeRestoredDraftChoice(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
