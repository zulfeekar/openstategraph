/**
 * Whether this page load offers the project's workflows —
 * `install-experience` 28.
 *
 * ## The rule 23 left half-finished
 *
 * 23 (`be3af73`) made a bare URL a blank canvas, because it had been adopting
 * somebody else's newest draft. That was right and it stays right. What it
 * left is the other half the ticket names: *blank* was only the safe answer,
 * not a useful one, and a project holding three workflows still said nothing
 * about them.
 *
 * An **offer** is not an adoption. Nothing reaches the canvas until a person
 * clicks a row, so 23's rule is untouched — and the gate below exists to keep
 * it that way, because every clause is a case where offering would be either
 * wrong or noise.
 *
 * ## The four clauses
 *
 * - **`urlNamedWorkflow`** — `?w=<slug>` names the document. A link a
 *   colleague sends must land where it says, with no modal in front of it.
 * - **`restoredDraft`** — this tab reloaded and got its own document back. A
 *   reload is not an arrival, and a list of alternatives on top of the work
 *   already on screen is a question that has been answered.
 * - **`placedStarter`** — the one visit ticket 24 owns. A browser holding no
 *   draft and no marker is handed Input → Agent → Output with a Note saying
 *   what it is. That visit already has an answer to *what is this canvas*, and
 *   two answers at once is the duplication this repository keeps paying for.
 *   The cost is stated rather than hidden: on a first-ever visit to a project
 *   that **does** hold workflows, the list is not offered and the reader gets
 *   the lesson instead. It costs exactly that one load — the browser then
 *   holds a draft, the starter is never offered again, and the next tab
 *   arrives here — and the Workflows control is on screen throughout.
 * - **`dismissed`** — see below.
 *
 * ## Dismissal is per tab, and that is the deliberate half
 *
 * `onceOnlyFlag` remembers an answer for the whole browser, forever, which is
 * right for a hint and wrong for this: an arrival question should be asked
 * again on a genuinely new arrival, and a new tab is one. So the flag is
 * written to `sessionStorage` — dismiss it and this tab never asks again,
 * however many times it is reloaded; open a new tab tomorrow and it offers.
 *
 * The **fail-safe direction is the same as `onceOnlyFlag`'s** and for the same
 * reason: no storage means already dismissed. A modal that cannot record a
 * dismissal returns on every load with no way to be rid of it, which is worse
 * than one nobody is shown — and the blank canvas behind it carries the same
 * list in its start panel either way.
 */

/** The two methods this needs. Narrow on purpose. */
export interface DismissalStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** Namespaced like every other flag this product stores. */
export const ARRIVAL_DISMISSED_KEY = 'openstategraph.arrival-dismissed';

const DISMISSED = 'true';

function ambient(): DismissalStore | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/** Pure, and every input is a fact the caller already had. */
export function shouldOfferArrival(input: {
  /** Whether `?w=` named a workflow in the address this load arrived on. */
  readonly urlNamedWorkflow: boolean;
  /** Whether this tab restored its own autosaved document. */
  readonly restoredDraft: boolean;
  /** Whether this load handed over ticket 24's first-run starter. */
  readonly placedStarter: boolean;
  /** Whether this tab has already dismissed the offer. */
  readonly dismissed: boolean;
}): boolean {
  return (
    !input.urlNamedWorkflow && !input.restoredDraft && !input.placedStarter && !input.dismissed
  );
}

/** Whether this tab has dismissed the offer — and `true` when it cannot tell. */
export function arrivalWasDismissed(store: DismissalStore | null = ambient()): boolean {
  try {
    return store === null || store.getItem(ARRIVAL_DISMISSED_KEY) === DISMISSED;
  } catch {
    return true;
  }
}

/** Record the dismissal. Failure is not worth a word: the offer is gone either way. */
export function rememberArrivalDismissed(store: DismissalStore | null = ambient()): void {
  try {
    store?.setItem(ARRIVAL_DISMISSED_KEY, DISMISSED);
  } catch {
    /* dismissed for this render, simply not carried across a reload */
  }
}
