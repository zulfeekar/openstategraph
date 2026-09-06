/**
 * The one workflow setting the editor can write, and the words it uses.
 *
 * `workflow-gallery` 26 made `settings.recursionLimit` reach the graph config
 * from every door — the editor's run, `/chat`, `CompiledWorkflow.ask` and the
 * MCP `run` tool. It left the number reachable only by hand-editing
 * `workflow.json` and reopening the document; 58 is that missing half.
 *
 * **Why a plain module rather than a node field schema.** CLAUDE.md declares
 * node configuration once as a field schema, and this is not a node's
 * configuration — it is a property of the *document*, held in
 * `model.settings` and serialised beside `name`. The existing document-level
 * precedent is the workflow's name: a `Field` in the workflow inspector,
 * committed through a command. This follows it rather than inventing a
 * parallel schema for a surface of one.
 *
 * **Why the copy lives here.** `vitest` runs with `environment: 'node'`, so a
 * React render cannot be asserted. Strings in a plain module can be, which is
 * what `stepBudget.test.ts` and `userFacingLexicon.test.ts` do — and the copy
 * is the part of this ticket most likely to regress, because the number's
 * meaning is counter-intuitive.
 */

/**
 * The key `backend/openstategraph/step_budget.py` reads first.
 *
 * A rename on this side is a silent no-op on that one: the document would
 * still round-trip, and every run would still take 50.
 */
export const STEP_BUDGET_KEY = 'recursionLimit';

/** The window `RunRequest` validates and `workflow_step_budget` clamps to. */
export const STEP_BUDGET_MIN = 10;
export const STEP_BUDGET_MAX = 1000;

/** What a run takes when the document names no number. */
export const STEP_BUDGET_DEFAULT = 50;

export const STEP_BUDGET_LABEL = 'Step budget';

/** An empty box is the default, so the placeholder is the default. */
export const STEP_BUDGET_PLACEHOLDER = String(STEP_BUDGET_DEFAULT);

/**
 * Two sentences of arithmetic and one of advice.
 *
 * The arithmetic, because the number is counted in supersteps and a reader's
 * first guess is laps — one lap of `examples/fanout-in-a-loop` spends four.
 * The advice, because a field that only offers a bigger number teaches the
 * move CLAUDE.md argues against: a loop that will not settle wants a grader
 * that stops it, not more room to spin.
 *
 * And a fourth sentence, added by `organisms-first-class` 61: what this one
 * number does on the *other* path. Run this package directly and it is the
 * run's budget. Mount it inside another workflow and the mounting run's
 * number is a ceiling — this one may take less of it, never more — because a
 * caller who named a step budget said what their whole run may cost, and a
 * mounted package that could raise it would make that ceiling meaningless.
 * The box is disabled inside a mounted instance, so the only place a reader
 * meets this number is the child package's own canvas; if the sentence is not
 * here it is nowhere.
 *
 * And a fifth, added by `organisms-first-class` 63: the number sizes **this
 * workflow**, not the composition it may sit at the top of. Every mount is a
 * separate run with a superstep counter of its own, measured: a loop package
 * mounted three levels down spends exactly what it spends one level down, and
 * three of them side by side spend three times. That is bounded — the mount
 * tree is compiled eagerly and a cycle is refused at build time, so the worst
 * case exists and `CompiledWorkflow.composition_step_budget()` reports it —
 * but it is not what a box labelled "Step budget" invites a reader to assume,
 * and the assumption is only correctable here.
 */
export const STEP_BUDGET_HINT =
  'Supersteps a run may spend before it stops. Not laps — a loop that fans out ' +
  'spends several supersteps per lap, so this is not a count of laps. Leave it ' +
  'empty for the default, 50. If a loop never settles, a grader that can pass is ' +
  'the fix; a bigger number only lets it run longer. When this workflow is ' +
  'mounted inside another, it may take less than that run allowed but never more. ' +
  'It sizes this workflow alone: every workflow mounted inside it counts from zero ' +
  'again, so a composition can spend this much for each workflow in it.';

/**
 * The budget a document saved, or `null` when it saved none.
 *
 * Mirrors `workflow_step_budget` deliberately, including reading both
 * spellings: the editor writes `recursionLimit`, and a hand-written package
 * or a script is at least as likely to write `recursion_limit`. Anything
 * that is not a whole number — a string, a float, a `bool` — is *not*
 * interpreted, so the field shows an empty box rather than a value the
 * runtime would ignore.
 */
export function readStepBudget(settings: Readonly<Record<string, unknown>>): number | null {
  for (const key of [STEP_BUDGET_KEY, 'recursion_limit']) {
    const value = settings[key];
    if (typeof value === 'number' && Number.isInteger(value)) return value;
  }
  return null;
}

export type StepBudgetParse =
  | { readonly ok: true; readonly value: number | null }
  | { readonly ok: false; readonly error: string };

/**
 * What a typed box means.
 *
 * **Empty is unset, never zero and never a sentinel.** CLAUDE.md's rule is
 * `int | None` with `None` meaning unbounded — no non-finite number ever
 * reaches a serialisable field — so an empty box removes the key rather than
 * writing a number that stands for its absence.
 *
 * Out of range is **refused here**, even though the runtime clamps rather
 * than refusing: a field that accepted `5` would show `5` and run `10`, which
 * is a number that lies. Refusing at the door is the only place the two can
 * be made to agree.
 */
export function parseStepBudget(text: string): StepBudgetParse {
  const trimmed = text.trim();
  if (trimmed === '') return { ok: true, value: null };
  if (!/^\d+$/.test(trimmed)) {
    return { ok: false, error: `Enter a whole number of supersteps, or leave it empty.` };
  }
  const value = Number(trimmed);
  if (value < STEP_BUDGET_MIN || value > STEP_BUDGET_MAX) {
    return {
      ok: false,
      error: `A run may be given between ${STEP_BUDGET_MIN} and ${STEP_BUDGET_MAX} supersteps.`,
    };
  }
  return { ok: true, value };
}
