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
