/**
 * What is inside a mounted workflow, said in one line.
 *
 * A Team or Workflow node is deliberately opaque on the canvas — the atoms it
 * contains (a supervisor, its workers, a grader, the tools they hold) live in
 * *another* document, and drilling in is a navigation, not a zoom. That
 * opacity is right for composition and wrong for orientation: a card reading
 * only `chinook-metrics-team` tells a reader nothing about what the box costs or
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
   * Set only for a Team whose grader feeds revision back into the graph —
   * the structural fact that makes a team a *loop* rather than a pipeline.
   */
  readonly note?: string;
}

/** Which mount is asking. A Team claims a loop; a Workflow claims nothing. */
export type CompositionKind = 'team' | 'subgraph';

/**
 * Node type → the word a reader uses for it, singular and plural.
 *
 * Order here *is* the order on the card: the actors first (who does the
 * work), then what closes the loop, then what they hold. Alphabetical or
 * document order would both scramble that reading.
 */
const VOCABULARY: readonly (readonly [match: (type: string) => boolean, one: string, many: string])[] =
  [
    [(t) => t === 'orchestrate.supervisor', 'supervisor', 'supervisors'],
    [(t) => t === 'orchestrate.worker', 'worker', 'workers'],
    [(t) => t.startsWith('agent.'), 'agent', 'agents'],
    [(t) => t === 'route.classifier', 'router', 'routers'],
    [(t) => t === 'route.grader', 'grader', 'graders'],
    [(t) => t === 'human.approval', 'approval', 'approvals'],
    [(t) => t.startsWith('function.'), 'function', 'functions'],
    [(t) => t.startsWith('tool.'), 'tool', 'tools'],
    [(t) => t === 'team.workflow', 'team', 'teams'],
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
  kind: CompositionKind,
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

  const loops = kind === 'team' && graderIds.some((id) => hasRevise(doc, id));
  return loops ? { parts, note: 'loops until its grader passes' } : { parts };
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
