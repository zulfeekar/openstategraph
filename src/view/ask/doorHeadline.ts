/**
 * The two sentences on the build-door card, and which one this run has earned.
 *
 * The door opens by two routes and they know different amounts
 * (`every-workflow-green` 34, then 35):
 *
 * - **the model described the gap.** It declined, and said in its own words
 *   what was missing. That sentence is the best description anyone has, and
 *   the card may say what ticket 34's card always said: *nothing here does
 *   this* — a claim about the library.
 * - **the shape of the run opened it.** The rule, quoted from the predicate
 *   that decides it (`DOOR_SHAPE_RULE`, in `compile/workflow_compiler.py`):
 *   tools were bound and none were called, anywhere in the turn — and nobody
 *   said why. That is a fact about *this run* and nothing more: the shape
 *   cannot tell a refusal from an answer the model simply knew. So the card
 *   claims exactly that much, in the past tense, and asks rather than asserts.
 *
 *   **Quoted, not paraphrased** (`every-workflow-green` 51). This docstring
 *   was the only statement of the rule anywhere, in a different language from
 *   the code implementing it, so when the card appeared on a turn that had
 *   called six tools there was no way to tell from either side whether the
 *   rule was per turn or per node. It is per turn — *anywhere* is the clause
 *   that says so, and a node the router never reached does not open the door
 *   on its own account.
 *
 * The split lives here, in one pure function with a test, rather than inline in
 * `AskPanel` — the card's *value is its wording*, which is the same argument
 * `moduleBrief` makes for sitting beside it. A headline that over-claims is how
 * a card teaches a developer to distrust every card, and prose inside a large
 * component has no way to fail.
 */
export interface DoorHeadline {
  /** The bold clause — what is being claimed. */
  readonly lead: string;
  /** The rest of the sentence: the gap, or the ask that replaces it. */
  readonly detail: string;
}

export function doorHeadline(gap: string): DoorHeadline {
  const described = gap.trim();
  if (described) {
    return { lead: 'Nothing here does this.', detail: described };
  }
  return { lead: 'Nothing here did this.', detail: 'Describe what you need.' };
}
