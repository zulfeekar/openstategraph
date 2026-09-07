import { unreadyFields, type FieldReadiness } from './suggestion';

/**
 * What the accept button on a capability-gap card may honestly promise.
 *
 * **Why this exists** (`production-ready` 74). The button said *Add & re-run*
 * and, for the one suggestion the product actually emits most often, added and
 * did not re-run: `tool.email-send` carries a required `to` with no default, so
 * the run is refused before it starts — correctly, because a run into "No
 * recipient configured" costs a model call to learn something that was already
 * knowable (`the-agent-asks-for-what-it-cannot-get` 01). The refusal was the
 * right behaviour behind the wrong label. A promise kept in the notice
 * afterwards is not the same thing as a promise not made.
 *
 * The fact needed is available **before the press**: a node type's own field
 * schema says which fields are required, and its defaults say which of those
 * arrive empty. So the label is computed from the type, not discovered from the
 * instance.
 *
 * **The recipient is not filled in for the user, and that is deliberate.** The
 * address is in the sentence the card was generated from, and lifting it out
 * would make this one click again — but `tool.email-send`'s whole discipline is
 * that the model writes subject and body and never the destination, which is
 * what its own hint tells a reader. An address parsed out of prose is a
 * destination taken on a model's say-so, and CLAUDE.md's *strict in trusting*
 * half forbids exactly that: tolerance in reading a model's reply is never
 * permission to act on an unresolved value. So the recipient stays manual, and
 * the cost of that decision is paid in the label rather than in silence.
 */
export interface AcceptAction {
  /** The button's words. Never promises a run that will not start. */
  readonly label: string;
  /** A sentence for the card when a run does not follow, else `null`. */
  readonly note: string | null;
  /** Whether pressing it re-runs the question. */
  readonly willRun: boolean;
}

/** Join labels the way a sentence does: "Recipient and Subject". */
function sentenceList(items: readonly string[]): string {
  if (items.length <= 1) return items[0] ?? '';
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

export function acceptAction(
  label: string,
  fields: readonly FieldReadiness[],
  defaults: Readonly<Record<string, unknown>>,
): AcceptAction {
  const unready = unreadyFields(fields, defaults);
  if (unready.length === 0) {
    return { label: 'Add & re-run', note: null, willRun: true };
  }

  const missing = sentenceList([...unready]);
  return {
    willRun: false,
    // Concrete rather than hedged: "Add & set up" would leave a reader
    // guessing which field and where. Naming it is what turns a surprise into
    // an instruction.
    label: `Add & set ${missing}`,
    note: `${label} needs ${missing}, and that is yours to set — this adds the node and opens it, then ask again.`,
  };
}
