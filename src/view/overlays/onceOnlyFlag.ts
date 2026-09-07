/**
 * A question this browser has already answered once, and is not asked again.
 *
 * `OnboardingHint` invented this in place — a namespaced `localStorage` key,
 * both buttons writing it, and a `try/catch` whose failure branch is *silence*
 * rather than a hint. Production-ready ticket 23 needed a second hint of the
 * same shape (the pointer at the examples shelf), and a second hand-rolled copy
 * of the same three decisions is duplication of **knowledge**, not of shape.
 * So the decisions live here once and the components are projections of them.
 *
 * The three decisions, each of which has a reason:
 *
 * - **Dismissing counts as answering.** A bubble that returns after you closed
 *   it is the most annoying kind of onboarding there is, so the flag is written
 *   by the close button exactly as by the act button.
 * - **No storage means already answered.** Private mode, an embedded frame, a
 *   sandboxed iframe: `getItem` throws, and the honest fallback is to show
 *   nothing. The alternative — show it — is a hint that cannot be dismissed for
 *   good and reappears on every load.
 * - **Storage is a parameter.** Two methods are the whole dependency, so a test
 *   hands over an object literal instead of a DOM. Same shape as
 *   `examplesShelf.ts`, which stores a three-state answer for the same reason.
 */

/** A `localStorage`-shaped thing. Narrow on purpose. */
export interface FlagStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const ANSWERED = 'true';

function ambientStorage(): FlagStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Whether this browser has answered already — and `true`, meaning "say
 * nothing", whenever there is no storage to remember an answer in.
 */
export function alreadyAnswered(key: string, storage: FlagStorage | null = ambientStorage()) {
  try {
    return storage === null || storage.getItem(key) === ANSWERED;
  } catch {
    return true;
  }
}

/** Record the answer. Failure is not worth a word: the hint is hidden either way. */
export function markAnswered(key: string, storage: FlagStorage | null = ambientStorage()): void {
  try {
    storage?.setItem(key, ANSWERED);
  } catch {
    /* hidden for this session, simply not carried forward */
  }
}

/** The credentials pointer's key. Unchanged — an existing install stays answered. */
export const ONBOARDED_KEY = 'openstategraph.onboarded';

/** The examples pointer's key (ticket 23). Namespaced like every other. */
export const EXAMPLES_HINT_KEY = 'openstategraph.examplesHint';
