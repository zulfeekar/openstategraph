import { describe, expect, it } from 'vitest';
import {
  ARRIVAL_DISMISSED_KEY,
  arrivalWasDismissed,
  rememberArrivalDismissed,
  shouldOfferArrival,
  type DismissalStore,
} from './arrivalOffer';

/**
 * `install-experience` 28 — when the editor offers the project's workflows,
 * and the four ways it must not.
 *
 * The whole risk of this ticket is 23 coming back. 23's defect was a document
 * arriving on the canvas that nobody chose; an *offer* is the opposite of that
 * — nothing is opened until a person clicks — but only while the offer stays
 * an offer. So the gate is pure, every clause names a way the offer would be
 * wrong, and the decision is testable with no DOM.
 */

const arriving = {
  urlNamedWorkflow: false,
  restoredDraft: false,
  placedStarter: false,
  canvasHoldsDocument: false,
  dismissed: false,
} as const;

function memory(initial: Record<string, string> = {}): DismissalStore {
  const seen = new Map(Object.entries(initial));
  return {
    getItem: (key) => seen.get(key) ?? null,
    setItem: (key, value) => void seen.set(key, value),
  };
}

const throwing: DismissalStore = {
  getItem() {
    throw new Error('storage is disabled in this context');
  },
  setItem() {
    throw new Error('storage is disabled in this context');
  },
};

describe('shouldOfferArrival', () => {
  it('offers on a bare arrival', () => {
    expect(shouldOfferArrival(arriving)).toBe(true);
  });

  it('stays quiet when the address bar named a workflow', () => {
    // The ticket's fifth clause, and the one a colleague's link depends on:
    // `?w=<slug>` opens that workflow and shows no dialog.
    expect(shouldOfferArrival({ ...arriving, urlNamedWorkflow: true })).toBe(false);
  });

  it('stays quiet when this tab restored its own draft', () => {
    // A reload is not an arrival. The document is already back on the canvas
    // and a modal over it would be asking a question that has been answered.
    expect(shouldOfferArrival({ ...arriving, restoredDraft: true })).toBe(false);
  });

  it('stays quiet on the one visit ticket 24 owns', () => {
    // A browser holding no draft and no marker is handed Input → Agent →
    // Output with a Note explaining it. That visit already has an answer to
    // "what is this canvas", and two answers at once is the duplication this
    // repository keeps paying for.
    expect(shouldOfferArrival({ ...arriving, placedStarter: true })).toBe(false);
  });

  it('stays quiet when a document is already on the canvas', () => {
    // `stable-beta-public/27`. Every other clause names a *route* by which a
    // document arrives; this one names the outcome all of them share, and it
    // is the one nothing was checking. `?demo=1` seeds thirteen nodes in
    // `main.tsx` before React exists — no `?w=`, no draft restored, no
    // starter — so all four clauses said "bare arrival" over a full canvas
    // and the modal's backdrop sat on top of the work, swallowing every click
    // and keystroke aimed at it. Nine e2e tests failed on that backdrop.
    expect(shouldOfferArrival({ ...arriving, canvasHoldsDocument: true })).toBe(false);
  });

  it('stays quiet once this tab has dismissed it', () => {
    expect(shouldOfferArrival({ ...arriving, dismissed: true })).toBe(false);
  });
});

describe('the dismissal', () => {
  it('is remembered', () => {
    const store = memory();
    rememberArrivalDismissed(store);
    expect(arrivalWasDismissed(store)).toBe(true);
    expect(store.getItem(ARRIVAL_DISMISSED_KEY)).not.toBeNull();
  });

  it('has not happened in a store that holds nothing', () => {
    expect(arrivalWasDismissed(memory())).toBe(false);
  });

  it('counts as having happened when there is nowhere to remember it', () => {
    // `onceOnlyFlag`'s rule, for the same reason: a modal that cannot be
    // dismissed for good returns on every load with no way to be rid of it,
    // which is worse than one nobody is shown. The start panel on the blank
    // canvas still offers everything the dialog would have.
    expect(arrivalWasDismissed(throwing)).toBe(true);
    expect(() => rememberArrivalDismissed(throwing)).not.toThrow();
  });
});
