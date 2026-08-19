/**
 * The opening move of the "build one" interview.
 *
 * A run said it needed something **no shipped tool provides**
 * (`capabilityGap`, `every-workflow-green` 34). The developer is owed a door,
 * and a card whose button did nothing would be worse than no card at all.
 *
 * So the button seeds the composer with a brief that starts the interview in
 * the chat that is already open. No new subsystem, no promise the product
 * cannot keep today — and the questions are the owner's own: *what does it do,
 * what does it solve, which kind of module is it,* then a name **close to the
 * business logic**.
 *
 * ## What the brief must carry, and why each line is here
 *
 * The generated module has to **inherit the architecture rather than sit
 * beside it**, which is the whole point of asking rather than guessing:
 *
 * - it lands in the package's own `tools/` folder — beside its
 *   `workflow.json`, in the package the user owns — and **never** in the
 *   installed distribution, which is the framework we ship.
 *
 *   Said that way on purpose. `workflows/` is only the **convention**: the
 *   root is resolved per call from `OPENSTATEGRAPH_WORKFLOWS_ROOT`, then
 *   `workflows_dir:` in `openstategraph.yaml`, then the checkout, then
 *   `./workflows` — so a brief naming a literal `workflows/…` path is wrong
 *   for anyone who configured one, and wrong inside an installed wheel. That
 *   is the exact failure `workflows_root.py` exists to end, where
 *   `platform_list_workflows` answered "No workflows exist yet" with the
 *   adopter's workflows sitting right there. "Beside its `workflow.json`" is
 *   true whatever the root is called;
 * - it takes state, context and memory through `ToolRuntime`, not by reaching
 *   around that seam. `.scratch/the-atom-has-no-context/` exists because "what
 *   is in the context when I extend?" had no answer, and a generated module
 *   that reaches around it teaches every later author the wrong shape;
 * - it is a concrete leaf on the existing ladder, not a loose function;
 * - it declares its card and its data keys, so the editor can draw it and the
 *   existing contract tests can see it;
 * - it names an environment variable for any credential and never carries a
 *   value.
 *
 * Written as a brief the developer can edit before sending, because they know
 * their business logic and this only knows the gap.
 */
export function moduleBrief(gap: string, slug: string | null | undefined): string {
  const where = (slug ?? '').trim() || 'this workflow';
  const missing = gap.trim() || 'a capability this workflow does not have';
  return [
    `Build a new tool for ${where}. Nothing in the library provides it.`,
    '',
    `What is missing: ${missing}`,
    '',
    'Before writing anything, ask me:',
    '- what it does, and what problem it solves',
    '- which kind of module it is',
    '- what it needs from the run (state, context, memory, a credential)',
    '- a name, unique here and close to the business logic',
    '',
    'Then build it to this shape:',
    `- it lives in the ${where} package's own tools/ folder, beside its `
      + `workflow.json — never in the installed package`,
    '- it reads state, context and memory through ToolRuntime, not around it',
    '- it is a concrete leaf on the existing tool ladder',
    '- it declares its card fields and its data keys',
    '- any credential is named as an environment variable, never a value',
  ].join('\n');
}
