/**
 * What the panel may honestly say about `result.attempts`.
 *
 * It used to say "N attempts before the grader passed it" whenever `attempts`
 * exceeded one. On `chained-summarizer` — an input, two agents and an output,
 * **no grader anywhere** — that printed *"2 attempts before the grader passed
 * it."* A sentence about a node the document does not contain
 * (`every-workflow-green` 21).
 *
 * The cause is not this line. `RunState.attempts` is a single graph-wide
 * integer and **every model-driven node increments it once per invocation** —
 * `_agent` and `_orchestrator` both do. So two agents in a straight chain
 * reach two, and nothing was ever rejected by anybody. That counter is
 * `workflow-gallery/21`, which is open and owns the fix; this module only
 * stops the surface from claiming something the counter cannot support.
 *
 * So the sentence says what the number actually is — model steps — and names
 * no grader. It is the smaller, true claim, and it stays true after
 * `workflow-gallery/21` lands, at which point a real revision count can
 * replace it rather than correct it.
 */
export function attemptsLine(result: {
  readonly attempts: number;
  readonly decisions: Readonly<Record<string, string>>;
}): string {
  if (!Number.isFinite(result.attempts) || result.attempts <= 1) return '';
  return `${result.attempts} model steps ran for this answer.`;
}
