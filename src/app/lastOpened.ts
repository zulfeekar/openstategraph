/**
 * When this browser last opened each workflow — `install-experience` 28.
 *
 * The arrival list sorts on *"most recently opened or edited"*, and only one
 * of those two is on disk. `savedAt` is a fact about the project that every
 * browser reads alike; **opened** is a fact about this person, and there is
 * nowhere else for it to live. `arrivalChoices` carries the argument for why
 * neither clock outranks the other.
 *
 * ## Written in one place
 *
 * `setOpenSlug` is the single seam that makes a slug this tab's open document
 * — the Workflows panel's load, a save that mints a slug, and a deep link all
 * pass through it, and nothing else does. So the stamp is written there, once,
 * rather than at the three call sites: a fourth caller would arrive and forget,
 * and the list would silently start ordering by a clock with a hole in it.
 *
 * A mount records its **class** slug, which is what `setOpenSlug` is given:
 * `concierge/wf-music` is one instance of `chinook-assistant`, and what the
 * reader opened is the package.
 *
 * ## Failure costs an ordering, never an arrival
 *
 * Every read and write is wrapped. A private window, a sandboxed frame or a
 * browser with site data blocked yields no stamps, the list is ordered by the
 * disk clock alone, and nothing is reported — there is nothing a reader could
 * do about it and the order they get is still a defensible one. Unparseable
 * bytes are treated the same way, and deliberately are **not** quarantined the
 * way `workflowStore` quarantines a draft: this key holds no work, only an
 * opinion about sorting, and the honest repair is to start recording again.
 */

/** The two methods this needs. Narrow on purpose, like `onceOnlyFlag`'s. */
export interface StampStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** One namespaced key holding the whole map. */
export const OPENED_AT_KEY = 'openstategraph.opened-at';

/**
 * How many stamps are kept.
 *
 * `localStorage` is about 5MB for the whole origin, shared with every draft —
 * `workflowStore` budgets against that ceiling explicitly, and a key that
 * grows by one entry per package ever opened is exactly the kind of quiet
 * tenant that eventually costs somebody a *save* rather than a list. Sixty is
 * far beyond any project a person browses by memory, and the entries evicted
 * are the oldest, which are the ones this list would have shown last anyway.
 */
export const OPENED_AT_LIMIT = 60;

function ambient(): StampStore | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * The stamps this browser holds, keyed by slug.
 *
 * `{}` for every failure — absent, unreadable, or the right JSON of the wrong
 * shape. An array is not a map of slugs, and half-reading one would order the
 * arrival list by nonsense.
 */
export function readOpenedStamps(store: StampStore | null = ambient()): Record<string, string> {
  let parsed: unknown;
  try {
    const raw = store?.getItem(OPENED_AT_KEY) ?? null;
    if (raw === null) return {};
    parsed = JSON.parse(raw);
  } catch {
    // A store that throws and bytes that will not parse are one answer here:
    // this key holds an opinion about sorting, never work, so there is nothing
    // to quarantine and nothing a reader could act on.
    return {};
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {};

  const stamps: Record<string, string> = {};
  for (const [slug, at] of Object.entries(parsed as Record<string, unknown>)) {
    if (typeof at === 'string') stamps[slug] = at;
  }
  return stamps;
}

/**
 * Record that `slug` was opened, now.
 *
 * `now` is a parameter so the decision is testable without a clock, following
 * every other dated module here.
 */
export function recordOpened(
  slug: string,
  store: StampStore | null = ambient(),
  now: () => Date = () => new Date(),
): void {
  if (!slug) return;
  const stamps = { ...readOpenedStamps(store), [slug]: now().toISOString() };

  // Newest kept, oldest dropped. An entry whose stamp will not parse sorts
  // last and is the first to go, which is the right fate for a value nothing
  // downstream can use.
  const kept = Object.entries(stamps)
    .sort(([, a], [, b]) => (Date.parse(b) || 0) - (Date.parse(a) || 0))
    .slice(0, OPENED_AT_LIMIT);

  try {
    store?.setItem(OPENED_AT_KEY, JSON.stringify(Object.fromEntries(kept)));
  } catch {
    // Session-only, and not worth a word: the list is still ordered, by the
    // clock that lives on disk.
  }
}
