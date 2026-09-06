/**
 * What makes a Guardrail `detector` invalid — the card's half of it.
 *
 * The mirror of `detector_problem` in `backend/openstategraph/abc/guardrail.py`,
 * and pinned to it by `backend/tests/test_a_detector_is_checked_before_it_runs.py`
 * so the two cannot drift into disagreeing about the word "invalid".
 *
 * Guardrails ticket 05. A `detector` is the one regular expression a developer
 * writes on a card, and nothing looked at it until a run reached the node —
 * where a missing `)` was an exception rather than a sentence. Three checks now
 * stand between typing one and running it: this one, when the field is edited;
 * a compile diagnostic (`Finding.INVALID_GUARDRAIL_RULE`); and `resolved()`
 * itself, which still refuses, because a guardrail that fails open is worse
 * than one that fails loudly.
 *
 * **Compiling a pattern is not running it.** `new RegExp(source)` parses; it
 * matches nothing. So this check executes none of what the developer wrote —
 * which matters, because nothing here bounds how long a *match* takes. That
 * class is refused rather than half-mitigated, and the argument is recorded
 * once, at `detector_problem` in the Python module.
 */

/**
 * The longest pattern the card accepts, in characters. Mirrors
 * `DETECTOR_MAX_LENGTH` in `abc/guardrail.py`.
 *
 * A bound on the absurd, not a defence: `(a+)+$` is six characters.
 */
export const DETECTOR_MAX_LENGTH = 400;

/**
 * Constructs that are Python's regular-expression dialect and not JavaScript's.
 *
 * Where one of these appears, the browser is not entitled to an opinion — the
 * pattern runs under Python's `re`, and refusing `(?P<year>\d{4})` on the card
 * because `new RegExp` cannot parse it would be this file inventing a rule the
 * runtime does not have. `abc/guardrail.py`'s `GuardrailRule` already states
 * the residual cost of dialects differing at the edges; this is the card
 * declining to make it worse.
 */
const PYTHON_ONLY = /\(\?P[<=]|\(\?#|\(\?\(|\\A|\\Z|\(\?[aiLmsux]+[):]/;

/**
 * The reason this pattern cannot be used, or `null` if it can.
 *
 * The shape `IFieldSchema.validate` takes: a sentence blocks the value, `null`
 * accepts it. Empty is accepted — a blank `detector` is how every built-in
 * entity is spelled, because the library brings the pattern. Whether a
 * *custom* entity may be blank is the row's question, not the field's.
 */
export const validateDetector = (value: string): string | null => {
  if (!value) return null;
  if (value.length > DETECTOR_MAX_LENGTH) {
    return `A pattern may be at most ${DETECTOR_MAX_LENGTH} characters; this is ${value.length}.`;
  }
  if (PYTHON_ONLY.test(value)) return null;
  try {
    new RegExp(value);
  } catch (error) {
    return `Not a valid pattern: ${error instanceof Error ? error.message : String(error)}`;
  }
  return null;
};
