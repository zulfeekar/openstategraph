/**
 * The name a document wears before anybody has named it.
 *
 * A `core/` fact, because it is the seed of `WorkflowModel` and because the
 * backend derives a **frozen** directory name from it at first save. Its
 * *presentation* — how a top bar marks the absence so it does not read as a
 * title — belongs to `view/` and lives in `TopBar.tsx`.
 *
 * `say-it-on-the-surface/09`. The argument for the word itself, and for why it
 * is a name rather than a state word, is in `documentName.test.ts` beside the
 * assertion that holds it.
 */

/** What an unnamed document is called. Never a state word — see the test. */
export const UNNAMED_DOCUMENT = 'Untitled';

/**
 * True when this document has never been given a name.
 *
 * Blank counts: a name cleared to nothing is not a name, and the save path has
 * to treat both the same way or it would mint a slug from an empty string.
 */
export function isUnnamedDocument(name: string): boolean {
  const trimmed = name.trim();
  return trimmed === '' || trimmed === UNNAMED_DOCUMENT;
}
