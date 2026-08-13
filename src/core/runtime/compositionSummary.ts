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
}

/**
 * Node type → the word a reader uses for it, singular and plural.
 *
 * Order here *is* the order on the card: the actors first (who does the
 * work), then what closes the loop, then what they hold. Alphabetical or
 * document order would both scramble that reading.
 */
const VOCABULARY: readonly (readonly [
  match: (type: string) => boolean,
  one: string,
  many: string,
])[] = [
  [(t) => t === 'orchestrate.supervisor', 'supervisor', 'supervisors'],
  [(t) => t === 'orchestrate.worker', 'worker', 'workers'],
  [(t) => t.startsWith('agent.'), 'agent', 'agents'],
  [(t) => t === 'route.classifier', 'router', 'routers'],
  [(t) => t === 'route.grader', 'grader', 'graders'],
  [(t) => t === 'human.approval', 'approval', 'approvals'],
  [(t) => t.startsWith('function.'), 'function', 'functions'],
  [(t) => t.startsWith('tool.'), 'tool', 'tools'],
  [(t) => t === 'workflow.subgraph', 'workflow', 'workflows'],
  [(t) => t.startsWith('input.'), 'input', 'inputs'],
  [(t) => t.startsWith('output.'), 'output', 'outputs'],
];

/**
 * Entry and exit are the mount's *own* ports, drawn on the parent canvas, so
 * counting them again inside the box would be describing the same wire twice.
 * Annotations are not machinery at all.
 */
const NOT_CONTENT = new Set(['input', 'inputs', 'output', 'outputs']);

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

  const nodes = Array.isArray(doc.nodes) ? doc.nodes : [];
  const counts = new Map<string, number>();
  const graderIds: string[] = [];

  for (const node of nodes) {
    const type = typeof node?.type === 'string' ? node.type : '';
    if (!type) continue;
    if (type === 'route.grader' && typeof node.id === 'string') graderIds.push(node.id);
    const entry = VOCABULARY.find(([match]) => match(type));
    if (!entry) continue;
    counts.set(entry[2], (counts.get(entry[2]) ?? 0) + 1);
  }

  const parts: CompositionPart[] = [];
  for (const [, one, many] of VOCABULARY) {
    const count = counts.get(many);
    if (!count) continue;
    if (NOT_CONTENT.has(many)) continue;
    parts.push({ label: count === 1 ? one : many, count });
  }
  if (parts.length === 0) return null;

  // A loop is worth stating wherever it exists — it is the most useful thing
  // to know about a mounted document, and it is earned from that document
  // rather than claimed by the card.
  if (graderIds.some((id) => hasRevise(doc, id))) {
    return { parts, note: 'loops until its grader passes' };
  }

  // **The gap is stated, not omitted** (ticket 03) — but only where something
  // was promised. A mount that claims no outcome claims nothing, and telling
  // it there is no grader would be a nag about a shape it never wanted.
  //
  // A child that does *not* loop used to be expressed as the absence of the
  // note above, and absence of a claim is not a claim of absence: the card
  // showed an `Expected outcome` the user had written, beside nothing saying
  // it is unchecked. Silence is the same shape as the defect.
  if (!context.claimsOutcome) return { parts };
  return {
    parts,
    note: graderIds.length
      ? 'its grader never revises — nothing sends a weak answer back'
      : 'no grader — nothing checks the outcome',
  };
}

/** The census as the one line a card shows. */
export function formatComposition(summary: CompositionSummary): string {
  const counts = summary.parts.map((part) => `${part.count} ${part.label}`).join(' · ');
  return summary.note ? `${counts} — ${summary.note}` : counts;
}

/** A grader only closes a loop if something is wired to its `revise` port. */
function hasRevise(doc: DocumentShape, graderId: string): boolean {
  const edges = Array.isArray(doc.edges) ? doc.edges : [];
  return edges.some(
    (edge) => edge?.source?.nodeId === graderId && edge?.source?.portId === 'revise',
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
