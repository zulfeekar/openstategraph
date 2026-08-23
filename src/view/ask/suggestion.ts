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
  /**
   * Node type ids already wired into `<attachTo>:<port>`, keyed by that pair.
   *
   * Supplied so this module can refuse a duplicate without knowing what a
   * controller is. See `suggestionOutcome`.
   */
  readonly wired?: ReadonlyMap<string, ReadonlySet<string>>;
}

/** The key `EditorFacts.wired` is keyed by. One place, so it cannot drift. */
export function busKey(nodeId: string, portId: string): string {
  return `${nodeId}:${portId}`;
}

/**
 * What the panel should do with an applicable suggestion.
 *
 * **Why this exists** (`the-agent-asks-for-what-it-cannot-get` 01). Accepting
 * a suggestion was not idempotent: the owner accepted the same one three times
 * and got three `Email Send` nodes on one bus, three identical failures, and no
 * progress. The fact needed to refuse was already in hand — `applySuggestion`
 * counted the edges on that bus and spent the number on *positioning*, so the
 * duplicate came out neatly arranged instead of refused.
 *
 * Offsetting is right for two **different** tools and is why that code exists.
 * The same type on the same bus is a different question and nobody was asking
 * it.
 */
export type SuggestionOutcome =
  | { readonly kind: 'apply'; readonly suggestion: CapabilitySuggestion }
  | { readonly kind: 'duplicate'; readonly suggestion: CapabilitySuggestion; readonly message: string }
  // `the-agent-asks-for-what-it-cannot-get` 04, half 1. An unregistered
  // `nodeType` is not the same silence as a malformed `attachTo` — the agent
  // named a real gap, and `null` collapsed it into the case where it named
  // nothing at all. `reason` carries only what the agent itself said (or ''
  // when it said nothing), never the invented type name — the card must not
  // read as if the platform's catalogue has authority handed to the model.
  | { readonly kind: 'gap'; readonly reason: string }
  | { readonly kind: 'none' };

export function suggestionOutcome(
  raw: Readonly<Record<string, unknown>> | null | undefined,
  facts: EditorFacts,
): SuggestionOutcome {
  const gapReason = capabilityGapReason(raw, facts);
  if (gapReason !== null) return { kind: 'gap', reason: gapReason };

  const suggestion = applicableSuggestion(raw, facts);
  if (suggestion === null) return { kind: 'none' };

  const already = facts.wired?.get(busKey(suggestion.attachTo, suggestion.port));
  if (already?.has(suggestion.nodeType)) {
    return {
      kind: 'duplicate',
      suggestion,
      // Names the thing and the place, because "already added" leaves a reader
      // hunting a canvas for which one. And it says what to do instead: a tool
      // that is present and failing needs configuring, not adding again.
      message: `${suggestion.label} is already wired to this step. If it is not working, open it and check its settings — adding a second one would not help.`,
    };
  }
  return { kind: 'apply', suggestion };
}

/**
 * Required fields on a freshly added node that have no value yet.
 *
 * The other half of the same transcript: the suggested `Email Send` was added
 * with an empty `to`, wired, and the flow re-run at once — into "No recipient
 * configured". That failure was **knowable before the run** and cost a model
 * call to discover.
 *
 * Returns labels rather than keys, because the sentence built from this is read
 * by a person looking at a card.
 */
export function unreadyFields(
  fields: readonly FieldReadiness[],
  data: Readonly<Record<string, unknown>>,
): readonly string[] {
  return fields
    .filter((field) => field.required === true)
    .filter((field) => {
      const value = data[field.key];
      return value === undefined || value === null || String(value).trim() === '';
    })
    .map((field) => field.label ?? field.key);
}

/** The slice of a field schema readiness cares about. */
export interface FieldReadiness {
  readonly key: string;
  readonly label?: string | undefined;
  readonly required?: boolean | undefined;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/**
 * The agent's own `reason`, when the suggestion names a `nodeType` this
 * editor has never registered — or `null` when there is nothing to report.
 *
 * This is the fact `applicableSuggestion` cannot surface without weakening
 * its own rule: a suggestion that cannot be applied is still not a
 * suggestion, and `applicableSuggestion` keeps returning `null` for it. But
 * "the type does not exist" and "the wiring does not exist" are different
 * situations for a developer reading the panel — one is a dead run with a
 * real cause, the other is a malformed proposal — and only the caller
 * (`suggestionOutcome`) needs the distinction, so it lives here rather than
 * on the function whose contract the ticket protects.
 *
 * Checked ahead of `attachTo`, deliberately: an invented type is the
 * interesting fact regardless of whether the wiring target also exists, and
 * a raw suggestion with no `nodeType` at all is not "an agent asking for a
 * capability" — it is silence, and stays silence.
 */
function capabilityGapReason(
  raw: Readonly<Record<string, unknown>> | null | undefined,
  facts: EditorFacts,
): string | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const nodeType = asString(raw['nodeType']);
  if (!nodeType || facts.nodeTypes.has(nodeType)) return null;
  return asString(raw['reason']);
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
