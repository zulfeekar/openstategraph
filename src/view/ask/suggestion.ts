/**
 * The capability-gap suggestion an editor run can carry back.
 *
 * When the Ask panel runs with `advisor: true`, every agent is told that if it
 * cannot answer for want of a capability it should say so and emit exactly one
 * fenced block:
 *
 * ```suggestion
 * {"nodeType": "tool.web-search", "attachTo": "agent-1",
 *  "port": "tools", "label": "Web Search", "reason": "…"}
 * ```
 *
 * This module is the whole of the trust boundary between a model's free text
 * and a real mutation of the user's canvas. It is a pure function with no
 * controller and no React in sight, because "did the model just ask us to add
 * a node that does not exist?" is exactly the question that must be answerable
 * in a unit test rather than in a browser.
 *
 * The rule it enforces: **a suggestion that cannot be applied is not a
 * suggestion.** An unknown `nodeType`, an `attachTo` naming a node that is not
 * on the canvas, or malformed JSON all resolve to "no suggestion", and the
 * fence stays in the rendered text as plain prose. Offering a button that
 * cannot work is worse than offering nothing — it reads as a promise.
 */

/** What the editor would do, once validated against the open document. */
export interface CapabilitySuggestion {
  /** A registered node type id, e.g. `tool.web-search`. */
  readonly nodeType: string;
  /** The id of the node on the canvas to wire the new node into. */
  readonly attachTo: string;
  /** The target port on `attachTo` — the agent's tool bus. */
  readonly port: string;
  /** Short human label for the card: "Web Search". */
  readonly label: string;
  /** One sentence explaining the gap. */
  readonly reason: string;
}

export interface ParsedAnswer {
  /** The answer with the suggestion fence removed, ready to render. */
  readonly text: string;
  /** Null when there was no fence, or none that could be honoured. */
  readonly suggestion: CapabilitySuggestion | null;
}

/** What the open editor can actually offer, for validating a suggestion. */
export interface EditorFacts {
  /** Every node type id registered in this editor. */
  readonly nodeTypes: ReadonlySet<string>;
  /** Every node id currently in the document. */
  readonly nodeIds: ReadonlySet<string>;
}

/**
 * Matches a ```suggestion fence and captures its body.
 *
 * Non-greedy so the *first* fence wins when a model emits several — it was
 * told to emit one, and picking the first is the only choice that is stable
 * as the answer streams in.
 */
const FENCE = /```suggestion\s*\n([\s\S]*?)```/;

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * Splits an answer into renderable prose and, if present and applicable, the
 * one suggestion the editor may act on.
 *
 * Only a fence the editor will honour is stripped from `text` — in that case
 * the card says the same thing better. An unusable fence stays in the prose
 * deliberately, so a developer can see what the model actually asked for
 * instead of watching the editor silently swallow it.
 */
export function parseSuggestion(answer: string, facts: EditorFacts): ParsedAnswer {
  const match = FENCE.exec(answer);
  if (!match) return { text: answer, suggestion: null };

  let parsed: unknown;
  try {
    parsed = JSON.parse(match[1] ?? '');
  } catch {
    return { text: answer, suggestion: null };
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { text: answer, suggestion: null };
  }

  const record = parsed as Record<string, unknown>;
  const suggestion: CapabilitySuggestion = {
    nodeType: asString(record['nodeType']),
    attachTo: asString(record['attachTo']),
    // The agent's tool bus is the only port a tool can land on today, so it
    // is the default rather than a required field — a model that omits it
    // still produces something applicable.
    port: asString(record['port']) || 'tools',
    label: asString(record['label']),
    reason: asString(record['reason']),
  };

  // Both checks are against the *live* editor, never a list baked in here: a
  // node type the registry does not know cannot be created, and an `attachTo`
  // the document does not contain cannot be wired. Either way the fence is
  // left in the prose rather than turned into a button that would fail.
  if (!facts.nodeTypes.has(suggestion.nodeType)) return { text: answer, suggestion: null };
  if (!facts.nodeIds.has(suggestion.attachTo)) return { text: answer, suggestion: null };

  return {
    text: answer.replace(FENCE, '').replace(/\n{3,}/g, '\n\n').trim(),
    suggestion,
  };
}
