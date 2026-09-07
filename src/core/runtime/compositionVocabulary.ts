/**
 * The words a mount card counts in, as a contract rather than a table.
 *
 * `compositionSummary` used to hold a `VOCABULARY` listing
 * `orchestrate.supervisor`, `agent.`, `route.grader` and eight more —
 * node-type ids, in `core/`. CLAUDE.md's open/closed rule says what that is:
 * *"extend by registering, never by editing the engine... a new capability
 * must not require touching `core/`"* (reviews-2026-08-14 ticket 13).
 *
 * So `core/` keeps the **mechanism** — which groups exist, what order they
 * read in, how a type resolves to a word, what happens when nothing
 * registered one — and the **words** live with the node families that own
 * them, in `src/nodes/vocabulary.ts` beside the palette sections and port
 * types that already work this way.
 *
 * A term is plain data: a type or family, a group, two words. Never a
 * predicate function — the old table stored `match: (t: string) => boolean`,
 * and a rule expressed as host-language code is one a plugin manifest cannot
 * carry and nothing can serialise.
 */

import type { IIdentifiable } from '@core/kernel/Registry';

/**
 * The reading order of a census, owned here.
 *
 * From the table this replaces: *"Order here is the order on the card: the
 * actors first (who does the work), then what closes the loop, then what they
 * hold. Alphabetical or document order would both scramble that reading."*
 *
 * A group rather than a number, deliberately. Registration order alone would
 * make the card's reading order a property of module import order — wrong
 * intermittently rather than visibly — and a raw ordering number would let a
 * contributor express an order that means nothing, which is the objection
 * CLAUDE.md raises against exactly that in the middleware slot table.
 */
export const CENSUS_GROUPS = ['actor', 'control', 'held', 'boundary', 'ignored'] as const;

export type CensusGroup = (typeof CENSUS_GROUPS)[number];

/**
 * Groups that are not *contents of the box*, and why each is excluded.
 *
 * - `boundary` — entry and exit are the mount's **own** ports, drawn on the
 *   parent canvas, so counting them again inside the box describes the same
 *   wire twice.
 * - `ignored` — annotations are not machinery at all.
 *
 * Two groups rather than one flag, because the two reasons are different and
 * a future reader deserves to know which applied.
 */
const NOT_CONTENT: ReadonlySet<CensusGroup> = new Set<CensusGroup>(['boundary', 'ignored']);

/** One word a census can count in. */
export interface ICompositionTerm extends IIdentifiable {
  /**
   * An exact node type (`route.grader`) or a whole family (`agent.`, with the
   * trailing dot). An exact term always beats a family term, whichever was
   * registered first.
   */
  readonly id: string;
  readonly group: CensusGroup;
  /** What one of these is called, on a card. */
  readonly one: string;
  /** What several are called. */
  readonly many: string;
  /**
   * The port this kind of node sends work back through, when it can close a
   * revision loop — `revise`, on a grader.
   *
   * Declared here rather than tested for by type in `core/`: the loop note is
   * the most useful thing a mount card says, and `type === 'route.grader'`
   * in the engine meant a new kind of loop-closing node could not earn it
   * without editing `core/`.
   */
  readonly revisePort?: string;
}

/** Whether a term's group is part of what the box contains. */
export function countsAsContent(term: ICompositionTerm): boolean {
  return !NOT_CONTENT.has(term.group);
}

/**
 * The word for a node type. **Always returns one.**
 *
 * A type nothing registered falls back to its family segment —
 * `analytics.chart` counts as "analytics" — and counts as content. The table
 * this replaces skipped it, so a card reading "1 agent" for a child holding
 * one agent and three unrecognised nodes was a lie of omission.
 *
 * That fallback is also what removes the load-order hazard: a census computed
 * before anything registered degrades to family words, which is legible, and
 * not to an empty card, which reads as "this mount contains nothing".
 */
export function termFor(type: string, vocabulary: readonly ICompositionTerm[]): ICompositionTerm {
  const exact = vocabulary.find((term) => term.id === type);
  if (exact) return exact;

  const family = vocabulary.find((term) => term.id.endsWith('.') && type.startsWith(term.id));
  if (family) return family;

  const word = type.split('.')[0] || type;
  return { id: `${word}.`, group: 'held', one: word, many: word };
}
