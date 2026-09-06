import type { RestoredDraftCause } from '@app/restoredDraftConflict';

/**
 * What the editor says when a reload finds the file has moved under its draft
 * — `osg-agent-experience/68`.
 *
 * Held apart from the dialog for the reason `arrivalCopy` is: a string inside
 * JSX has no way to fail, and these five sentences are the only thing standing
 * between two versions of somebody's work and the loss of one of them.
 *
 * The vocabulary is `diskConflictNotice`'s, deliberately. That sentence
 * already had to name these same two doors for the *save* path, and two
 * spellings of one choice — "keep mine" here and "overwrite" there — would be
 * two features as far as a reader is concerned.
 */

export const RESTORED_DRAFT_TITLE = 'This workflow changed on disk';

/**
 * The subtitle states the fact and the consequence, in that order, and names
 * neither door: the buttons name themselves, and a subtitle that recommends
 * one is the guess this whole ticket exists to stop the editor making.
 *
 * "Nothing has been written" is the load-bearing clause. The failure being
 * reported here used to happen silently *and* had already happened by the time
 * anybody could have been told; a reader's first question is whether the file
 * is already gone.
 */
export const RESTORED_DRAFT_SUBTITLE =
  'You have unsaved edits in this browser, and the saved file has changed since ' +
  'you made them. Nothing has been written — choose which version to keep.';

/**
 * The same choice, arriving while the tab sits open — `osg-agent-experience/69`.
 *
 * One sentence differs from the one above and it is the only thing that may:
 * *when* the file moved. `68`'s question is asked by a reload, so its subtitle
 * says "since you made them" and a reader supplies the overnight gap
 * themselves. This one is asked with the canvas already on screen, where "the
 * saved file has changed" with no "just now" reads as a fact about the past
 * and invites the reader to look for what they did wrong. It also names the
 * writers, because the first question anybody asks of a dialog that appeared
 * unbidden is who caused it — and the honest answer, which the file watch
 * behind this cannot narrow, is that it was one of four.
 *
 * The second half is verbatim from the sibling, deliberately: "Nothing has
 * been written — choose which version to keep" is the clause the whole feature
 * rests on, and a second wording of it is a second promise.
 */
export const CHANGED_ELSEWHERE_SUBTITLE =
  'Someone else just saved this workflow — another tab, the command line, or a ' +
  'coding agent — and you have unsaved edits here. ' +
  'Nothing has been written — choose which version to keep.';

/** The subtitle for one occasion, so the dialog holds no `if` about copy. */
export function restoredDraftSubtitle(cause: RestoredDraftCause): string {
  return cause === 'changed-elsewhere' ? CHANGED_ELSEWHERE_SUBTITLE : RESTORED_DRAFT_SUBTITLE;
}

export const RESTORED_DRAFT_KEEP = 'Keep my edits';

export const RESTORED_DRAFT_TAKE = 'Take the file';

/** What each door does, printed beside it rather than learned by pressing it. */
export function restoredDraftKeepHint(name: string): string {
  return `The canvas keeps your unsaved edits, and saving overwrites "${name}" on disk.`;
}

export function restoredDraftTakeHint(name: string): string {
  return `"${name}" is loaded from disk and your unsaved edits are discarded.`;
}

/**
 * The toast after *take the file*.
 *
 * Said out loud because the canvas changing under the user is exactly the
 * event `restoredDraftNotice` exists to stop being silent — this is the same
 * rule pointed the other way.
 */
export function restoredDraftTookTheFile(name: string): string {
  return `Loaded "${name}" from disk. Your unsaved edits to it are gone.`;
}

/** The toast after *keep my edits*. */
export function restoredDraftKeptTheDraft(name: string): string {
  return `Keeping your unsaved edits. The next change writes them over "${name}" on disk.`;
}

/**
 * The toast a **clean** tab gets when it took the new revision by itself —
 * `osg-agent-experience/69`.
 *
 * Silent about the *choice*, not about the *event*. There was nothing to
 * decide, so no dialog was raised; but the document on screen changed without
 * a gesture, and that is the one thing this editor may never do quietly —
 * `restoredDraftNotice`'s rule, and the whole subject of `68`. A toast is the
 * right weight for it precisely because nothing was lost: it says what
 * happened and gets out of the way.
 */
export function workflowRefreshedFromDisk(name: string): string {
  return `"${name}" was saved elsewhere, so this canvas was updated to match. You had no unsaved edits.`;
}
