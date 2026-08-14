/**
 * What is inside a mounted workflow, said in one line.
 *
 * A Workflow mount is deliberately opaque on the canvas — the atoms it
 * contains (a supervisor, its workers, a grader, the tools they hold) live in
 * *another* document, and drilling in is a navigation, not a zoom. That
 * opacity is right for composition and wrong for orientation: a card reading
 * only `chinook-assistant` tells a reader nothing about what the box costs or
 * does.
 *
 * So this derives a **census** of the referenced document — node types counted
 * into the vocabulary a reader already has from the palette — and nothing
 * else. It is pure: a document in, a summary out, no fetching, no React, no
 * knowledge of where the document came from. That is what makes it testable
 * against the real `workflows/<slug>/workflow.json` fixtures on disk.
 *
 * It reads the *saved document*, never the compiled graph: the compiler's
 * output is a LangGraph object, and reading it back would break the
 * one-directional compile seam.
 */

import {
  CENSUS_GROUPS,
  type ICompositionTerm,
  countsAsContent,
  termFor,
} from './compositionVocabulary';

/** One counted line of the census, already pluralised. */
export interface CompositionPart {
  readonly label: string;
  readonly count: number;
}

export interface CompositionSummary {
  readonly parts: readonly CompositionPart[];
  /**
   * What the child's own wiring says about revision: that its grader feeds
   * work back, or — where this mount claims an outcome — that nothing does.
   */
  readonly note?: string;
}

/**
 * What the caller knows about the mount, beyond its document.
 *
 * Replaces `CompositionKind = 'team' | 'subgraph'`. Since schema v3 there is
 * one mount type, so the *card* no longer distinguishes anything — what
 * decides whether a missing loop is worth mentioning is whether this mount
 * claims an outcome, which is a property of what the author wrote on it
 * (production-ready tickets 03 and 16).
 */
export interface CompositionContext {
  /** True when this mount carries authored `outcome` prose. */
  readonly claimsOutcome?: boolean;
  /**
   * The words to count in — see `compositionVocabulary`.
   *
   * Passed in rather than imported, because the words belong to the node
   * families and this module belongs to `core/`
   * (reviews-2026-08-14 ticket 13). Optional, and an omitted vocabulary is
   * not a broken one: every type falls back to its family segment, so a
   * census still reads "1 agent · 1 route · 3 tool" rather than coming back
   * empty. That is what makes this safe to call from a test that has no app
   * running, which is most of them.
   */
  readonly vocabulary?: readonly ICompositionTerm[];
}

interface DocumentShape {
  readonly nodes?: readonly { readonly id?: unknown; readonly type?: unknown }[];
  readonly edges?: readonly {
    readonly source?: { readonly nodeId?: unknown; readonly portId?: unknown };
  }[];
  readonly settings?: unknown;
}

/** Longest purpose a mount card shows. Matches `promptIntent`'s cap. */
const PURPOSE_LIMIT = 160;

/**
 * The one sentence a mounted package says about itself.
 *
 * The census answers *what is in the box* — "1 agent · 1 grader · 3 tools" —
 * which is machinery, not meaning. A reader looking at a **Data Analyst** card
 * wants to know what it achieves, and counting its parts does not say. That
 * was the gap reported from live use: *"the data analyst is a workflow — add a
 * group annotation to briefly explain what is inside"*.
 *
 * **Authored once, in the child package's own `settings.purpose`; shown by
 * every mount of it.** Three alternatives were weighed:
 *
 * - *Per-mount text* — two mounts of one package could describe it two ways,
 *   and at least one would be wrong. It is a fact about the package, so it
 *   belongs to the package. (Per-*mount* difference is what `overrides` is
 *   for, and that already reports itself separately on the card.)
 * - *Derived from the child's graph* — cannot lie, but a count is exactly what
 *   the census already gives; there is no honest way to derive intent from
 *   topology.
 * - *Derived from the child's entry agent's system prompt* — tempting, and
 *   wrong: a package is not always one agent, and the sentence would silently
 *   change when somebody edited an unrelated prompt.
 *
 * Empty when unwritten. A mount whose package never said what it is for shows
 * the census alone rather than an invented summary, because a card that
 * confidently mis-describes what it runs is worse than a quiet one.
 */
export function compositionPurpose(document: unknown): string {
  const doc = asDocument(document);
  const settings = doc?.settings;
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)) return '';
  const purpose = (settings as Record<string, unknown>)['purpose'];
  if (typeof purpose !== 'string') return '';
  const text = purpose.trim().replace(/\s+/g, ' ');
  if (!text) return '';
  return text.length <= PURPOSE_LIMIT ? text : `${text.slice(0, PURPOSE_LIMIT - 1).trimEnd()}…`;
}

/**
 * Count a referenced workflow's document into the atomic vocabulary.
 *
 * Returns `null` for anything that is not a document with nodes — an empty
 * workflow has nothing worth annotating, and a malformed payload must not
 * throw inside a card render.
 */
export function summarizeComposition(
  document: unknown,
  context: CompositionContext = {},
): CompositionSummary | null {
  const doc = asDocument(document);
  if (!doc) return null;

  const vocabulary = context.vocabulary ?? [];
  const nodes = Array.isArray(doc.nodes) ? doc.nodes : [];
  const counted = new Map<string, { term: ICompositionTerm; count: number }>();
  /** Nodes that could close a revision loop, with the port that would do it. */
  const closers: { id: string; term: ICompositionTerm }[] = [];

  for (const node of nodes) {
    const type = typeof node?.type === 'string' ? node.type : '';
    if (!type) continue;
    const term = termFor(type, vocabulary);
    if (term.revisePort && typeof node.id === 'string') closers.push({ id: node.id, term });
    if (!countsAsContent(term)) continue;
    const entry = counted.get(term.id);
    if (entry) entry.count += 1;
    else counted.set(term.id, { term, count: 1 });
  }

  // Group order first — `CENSUS_GROUPS` is the card's reading order — then
  // the order the terms were registered in, which `Map` preserves.
  const parts: CompositionPart[] = [...counted.values()]
    .sort((a, b) => CENSUS_GROUPS.indexOf(a.term.group) - CENSUS_GROUPS.indexOf(b.term.group))
    .map(({ term, count }) => ({ label: count === 1 ? term.one : term.many, count }));
  if (parts.length === 0) return null;

  // A loop is worth stating wherever it exists — it is the most useful thing
  // to know about a mounted document, and it is earned from that document
  // rather than claimed by the card.
  const looping = closers.find(({ id, term }) => hasRevise(doc, id, term.revisePort!));
  if (looping) return { parts, note: `loops until its ${looping.term.one} passes` };

  // **The gap is stated, not omitted** (ticket 03) — but only where something
  // was promised. A mount that claims no outcome claims nothing, and telling
  // it there is no grader would be a nag about a shape it never wanted.
  //
  // A child that does *not* loop used to be expressed as the absence of the
  // note above, and absence of a claim is not a claim of absence: the card
  // showed an `Expected outcome` the user had written, beside nothing saying
  // it is unchecked. Silence is the same shape as the defect.
  if (!context.claimsOutcome) return { parts };
  const present = closers[0];
  if (present) {
    return {
      parts,
      note: `its ${present.term.one} never revises — nothing sends a weak answer back`,
    };
  }
  // Named where the vocabulary has a name to give. With no loop-closing term
  // registered at all there is no honest word for the missing thing, so the
  // sentence says only what is true.
  const closerWord = vocabulary.find((term) => term.revisePort)?.one;
  return {
    parts,
    note: closerWord
      ? `no ${closerWord} — nothing checks the outcome`
      : 'nothing checks the outcome',
  };
}

/** The census as the one line a card shows. */
export function formatComposition(summary: CompositionSummary): string {
  const counts = summary.parts.map((part) => `${part.count} ${part.label}`).join(' · ');
  return summary.note ? `${counts} — ${summary.note}` : counts;
}

/** A loop closes only if something is wired to the node's revise port. */
function hasRevise(doc: DocumentShape, nodeId: string, revisePort: string): boolean {
  const edges = Array.isArray(doc.edges) ? doc.edges : [];
  return edges.some(
    (edge) => edge?.source?.nodeId === nodeId && edge?.source?.portId === revisePort,
  );
}

/**
 * Accepts either a saved envelope (`{ version, name, document }`, what the
 * backend stores) or a bare document, because both spellings reach callers
 * and guessing wrong shows an empty card rather than an error.
 */
function asDocument(value: unknown): DocumentShape | null {
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  if (Array.isArray(record['nodes'])) return record as DocumentShape;
  if (record['document']) return asDocument(record['document']);
  return null;
}
