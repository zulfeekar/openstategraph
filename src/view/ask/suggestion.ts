/**
 * The capability-gap suggestion an editor run can carry back.
 *
 * When a run declares `audience: 'developer'`, every agent is told that if it
 * cannot answer for want of a capability it should say so and emit one fenced
 * `suggestion` block. **The fence never reaches this module.** The backend
 * splits it out of the answer on every run, for every audience, and delivers
 * the parsed object on the `done` frame's `developer` channel — see
 * `backend/openstategraph/api/audience.py`. A customer surface therefore
 * cannot render developer guidance even by accident, because there is nothing
 * in a customer's `answer` to render.
 *
 * What remains here is the other half, and it is the half only the browser can
 * do: **is this suggestion applicable to the canvas that is actually open?**
 * The backend knows the fence parsed; it does not know which node types this
 * editor registered or which nodes this document contains. That is a pure
 * function with no controller and no React in sight, because "did the model
 * just ask us to add a node that does not exist?" is exactly the question that
 * must be answerable in a unit test rather than in a browser.
 *
 * The rule it enforces: **a suggestion that cannot be applied is not a
 * suggestion.** An unknown `nodeType`, an `attachTo` naming a node that is not
 * on the canvas, or a payload that is not an object all resolve to `null` and
 * no card is offered. Offering a button that cannot work is worse than
 * offering nothing — it reads as a promise.
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

/** What the open editor can actually offer, for validating a suggestion. */
export interface EditorFacts {
  /** Every node type id registered in this editor. */
  readonly nodeTypes: ReadonlySet<string>;
  /** Every node id currently in the document. */
  readonly nodeIds: ReadonlySet<string>;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * The suggestion this editor may act on, or `null`.
 *
 * `raw` is the object off the run's developer channel — `null` for a customer
 * run, which is the case this returns `null` for first and without ceremony.
 */
export function applicableSuggestion(
  raw: Readonly<Record<string, unknown>> | null | undefined,
  facts: EditorFacts,
): CapabilitySuggestion | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;

  const suggestion: CapabilitySuggestion = {
    nodeType: asString(raw['nodeType']),
    attachTo: asString(raw['attachTo']),
    // The agent's tool bus is the only port a tool can land on today, so it
    // is the default rather than a required field — a model that omits it
    // still produces something applicable.
    port: asString(raw['port']) || 'tools',
    label: asString(raw['label']),
    reason: asString(raw['reason']),
  };

  // Both checks are against the *live* editor, never a list baked in here: a
  // node type the registry does not know cannot be created, and an `attachTo`
  // the document does not contain cannot be wired. Either way no card is
  // offered rather than a button that would fail.
  if (!facts.nodeTypes.has(suggestion.nodeType)) return null;
  if (!facts.nodeIds.has(suggestion.attachTo)) return null;

  return suggestion;
}
