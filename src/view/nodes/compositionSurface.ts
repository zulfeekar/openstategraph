import {
  compositionPurpose,
  formatComposition,
  summarizeComposition,
} from '@core/runtime/compositionSummary';
import type { ICompositionTerm } from '@core/runtime/compositionVocabulary';

/**
 * What a mount card shows, decided before anything is rendered.
 *
 * This exists because of a regression that had no commit to blame. The card's
 * **Open this mount** verb was written as a child of the census line, so every
 * early return that dropped the census dropped the verb with it — and four of
 * the five states a slug can be in are early returns. A mount whose package was
 * not saved yet, or whose runtime was restarting, rendered a card with no way
 * into it and nothing saying why. Nothing removed the affordance; a condition
 * did, silently, and no test could see it because the decision lived inside a
 * `.tsx` component and the suite runs in `node`.
 *
 * So the decision is here, pure and free of React, and `CompositionBody` is the
 * projection of it — the same split as `portLayout` and `liveInputValue`. The
 * property that matters, and the one pinned in the test beside this file:
 *
 * > **A configured mount always offers its open verb.** Reading the child is
 * > how the card describes the box; it is not how the card lets you in.
 */

/** What the fetch of the child document has come back with, if anything yet. */
export type MountDocumentState =
  | { readonly status: 'loading' }
  | { readonly status: 'ready'; readonly document: unknown }
  | { readonly status: 'missing' }
  | { readonly status: 'unreachable' };

export interface CompositionSurface {
  /**
   * Whether the drill-in verb is offered — **always true here**, and a field
   * rather than a constant precisely so a test can say so out loud. The suite
   * runs in `node` with no DOM, so nothing can assert against a rendered card;
   * what it can assert is that this decision never says no, and that the card
   * has exactly one early return (`surface === null`) so there is nowhere else
   * for the verb to be lost.
   */
  readonly open: boolean;
  /** The census line, or `null` when the child could not be counted. */
  readonly census: string | null;
  /** The package's own one-line purpose; empty when it never wrote one. */
  readonly purpose: string;
  /** How many child nodes this instance overrides — its own data, no fetch. */
  readonly overridden: number;
  /** What to say in the census's place, or `null` when the census is there. */
  readonly note: string | null;
  /** Whether there is a compiled graph worth offering a peek at. */
  readonly peekable: boolean;
}

export interface CompositionSurfaceInput {
  /** The package this mount points at. */
  readonly slug: string;
  readonly state: MountDocumentState;
  /** This mount's raw `overrides` JSON, as authored. */
  readonly overrides?: string;
  /** This mount's authored `outcome` prose, if any — see `CompositionContext`. */
  readonly claimsOutcome?: boolean;
  /** The census words, from `ModelRegistry.censusTerms`. */
  readonly vocabulary?: readonly ICompositionTerm[];
}

/**
 * `null` only for an unconfigured mount.
 *
 * An empty slug is the one honest silence: there is no package to open, no
 * census to take, and a placeholder would read as a failure rather than as an
 * empty field.
 */
export function compositionSurface(input: CompositionSurfaceInput): CompositionSurface | null {
  const slug = input.slug.trim();
  if (!slug) return null;

  const overridden = overriddenCount(input.overrides ?? '');
  const summary =
    input.state.status === 'ready'
      ? summarizeComposition(input.state.document, {
          claimsOutcome: input.claimsOutcome ?? false,
          vocabulary: input.vocabulary ?? [],
        })
      : null;

  return {
    open: true,
    census: summary ? formatComposition(summary) : null,
    purpose: input.state.status === 'ready' ? compositionPurpose(input.state.document) : '',
    overridden,
    note: summary ? null : noteFor(input.state, slug),
    peekable: summary !== null,
  };
}

/**
 * Why there is no census, in the reader's terms.
 *
 * Said rather than omitted, because silence is the same shape as the defect:
 * a card with no census and no reason is indistinguishable from a card whose
 * body failed to render, which is exactly how this went unnoticed.
 */
function noteFor(state: MountDocumentState, slug: string): string {
  switch (state.status) {
    case 'loading':
      return `reading ${slug}…`;
    case 'missing':
      // Free text is deliberate — a mount may name a package you have not
      // built yet — so this is a statement of fact, never a validation error.
      return `unknown workflow: ${slug}`;
    case 'unreachable':
      return `could not reach the runtime to read ${slug}`;
    case 'ready':
      return `${slug} is empty`;
  }
}

/**
 * How many child nodes this mount overrides (docs/decisions/mount-overrides.md).
 *
 * A fact about **this node's own data**, so it survives a failed fetch: a card
 * claiming the package default while an override runs would be a lie about
 * what executes, and it would be a lie precisely when the runtime is down.
 * Malformed JSON is the inspector validator's problem; this stays silent
 * rather than guessing.
 */
function overriddenCount(raw: string): number {
  const blob = readBlob(raw);
  if (!blob) return 0;
  return Object.values(blob).filter(pinsSomething).length;
}

/**
 * An object, or `null` for anything this card will not guess at.
 *
 * A blob may legitimately arrive as a JSON **string** at any nesting level —
 * `commit()` writes one and `apply_mount_overrides` reads one — so a string is
 * parsed rather than dismissed. Malformed JSON is the inspector validator's
 * problem; this stays silent rather than guessing.
 */
function readBlob(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  if (typeof value !== 'string' || !value.trim()) return null;
  try {
    return readBlob(JSON.parse(value));
  } catch {
    // Not JSON yet — the author is mid-keystroke, or the inspector is already
    // showing them the error. Either way the card does not pile on.
    return null;
  }
}

/**
 * Whether one child id's entry actually pins anything.
 *
 * **An empty entry is not a customisation**, and the distinction is the whole
 * point of the badge: `{"agent1": {}}` and `{"m1": {"overrides": {}}}` are what
 * a cleared override leaves behind, and a card counting them would report a pin
 * against a field that follows the package. `MountContext.clearOverride` prunes
 * them on the write side and says so — but the card must not lean on that,
 * because `OVERRIDES_FIELD` is a raw JSON textarea
 * (`organisms-first-class/12`), so either shape can be typed by hand.
 *
 * A nested mount recurses: its own `overrides` is the only key it carries, so
 * asking "is it non-empty" one level down is asking the same question again.
 */
function pinsSomething(entry: unknown): boolean {
  const fields = readBlob(entry);
  if (!fields) return false;
  return Object.entries(fields).some(([key, value]) =>
    key === 'overrides' ? pinsSomething(value) : true,
  );
}
