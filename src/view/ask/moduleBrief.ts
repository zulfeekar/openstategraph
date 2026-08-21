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
 * ## What the brief must carry, and why the wording is not free
 *
 * The generated module has to **inherit the architecture rather than sit
 * beside it**, which is the whole point of asking rather than guessing. The
 * five shape rules below are **not authored here**. They are
 * `openstategraph.generated_module_contract.CLAUSES`, and
 * `backend/tests/test_a_generated_module_is_checkable.py` fails if this file
 * stops carrying any of them verbatim.
 *
 * CLAUDE.md allows a hand-mirror of a Python contract only where a drift test
 * pins it, and the mirror earns its place for the usual reason: this text has
 * to render in a chat composer with no server necessarily reachable.
 *
 * ## Why the pin exists — the clause that was fiction for a day
 *
 * This brief used to instruct every developer who pressed the button to *"read
 * state, context and memory through `ToolRuntime`, not around it"*.
 * **`ToolRuntime` does not exist in this platform.** It is a LangChain
 * construct we do not surface; `docs/decisions/special-agents-2026-08.md`
 * records it as *"new mechanism — flagged, not decided"*. A tool here gets its
 * validated `Args` and nothing else — config through `configure(data)`, the
 * run through `langgraph.config.get_config()`, memory through `get_store()`,
 * and graph state not at all.
 *
 * Seven tests in this file's own spec held that sentence, all green, because
 * every one asked whether the **words** were present. None asked whether the
 * thing they name **exists here**. That is now the contract's first gate, and
 * it is on the Python side because that is where the seams are.
 *
 * The `workflows/` wording is load-bearing for the same kind of reason:
 * `workflows/` is only the **convention** — the root is resolved per call from
 * `OPENSTATEGRAPH_WORKFLOWS_ROOT`, then `workflows_dir:` in
 * `openstategraph.yaml`, then the checkout, then `./workflows` — so a brief
 * naming a literal `workflows/…` path is wrong for anyone who configured one,
 * and wrong inside an installed wheel. That is the exact failure
 * `workflows_root.py` exists to end. "Beside its `workflow.json`" is true
 * whatever the root is called.
 *
 * Written as a brief the developer can edit before sending, because they know
 * their business logic and this only knows the gap.
 *
 * ## The lines are load-bearing, and for a day they did not arrive
 *
 * This function was correct and its output was still unreadable: the composer
 * was a single-line `<input>`, and the HTML value sanitisation algorithm
 * strips CR and LF from an input's value. Twelve lines became one 909-
 * character run-on — `provides it.What`, `SlackBefore`, `logicThen` — with
 * nothing thrown and nothing reported (`every-workflow-green` 40). Every test
 * here stayed green, because they all read the value this function *returns*.
 * So: a change that makes the brief longer or more structured is only as good
 * as the control it lands in, which is now a `TextArea` and pinned by
 * `composerHoldsAMultiLineBrief.test.ts`.
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
    // Verbatim from `generated_module_contract.CLAUSES`. The slug is
    // interpolated into the first one because a path is easier to act on than
    // a description of a path; the rest are the clause text unchanged.
    `- it lives in the ${where} package's own tools/ folder, beside its ` +
      `workflow.json — never in the installed package`,
    '- it takes config through configure(data), the run through ' +
      'langgraph.config.get_config(), and memory through get_store() — ' +
      'a tool cannot read graph state',
    '- it is a concrete leaf on the existing tool ladder — a BaseTool ' +
      'subclass that implements _execute',
    '- it declares its card fields in node_fields and reads exactly those ' + 'keys in configure',
    '- any credential is named as an environment variable, never a value',
  ].join('\n');
}
