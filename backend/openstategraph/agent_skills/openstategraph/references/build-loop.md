# The build loop — long form

Read this when step 9 of `SKILL.md` is the step you are on. One card at a
time, start to finish, before the next card is attended. A **tweak** (step 3)
runs every step of this page but 5, the deliberate break. It is not exempt from
the two stage writes: the board's `finished` gate reads the test id, the reason
it failed and the green off the card, so a card that skipped them is refused at
the last step with nothing to show for the work.

Two doors this page owns because step 2's table no longer lists them: a
judgement card is answered with `kanban_answer_card` /
`openstategraph kanban answer`, and a workflow is run — only when runs are
enabled and the developer has said so — with `run_workflow` /
`openstategraph run`.

**If triage hands you nothing, ask where the board is before concluding there
is none.** `openstategraph kanban where` prints the file, the reason that file
was chosen, and whether it exists yet — the address depends on whether
OpenStateGraph is installed or run from a checkout, so a board written by one
and read by the other is two files (`osg-agent-experience/65`). *No board here
yet* and *the board is empty* are different sentences and only one of them
means there is no work.

## 1. Attend

MCP: `kanban_attend_card`. CLI: `openstategraph kanban attend <task_id>
--actor <you>`.

Attending is exclusive: the first caller wins and the second is told who holds
it. If you are refused, take the next card from triage rather than waiting.

If a card is held by somebody who has plainly stopped, the board flags it
stale and `kanban_release_card` / `openstategraph kanban release` is the
explicit, deliberate unstick. It is not a way to take a card off a working
agent.

Read the card before you start: `kanban_show_card` /
`openstategraph kanban show <task_id>` prints the whole self-contained
instruction — the story, the done-when, the evidence, the model and effort.

## 2. The failing test, at the layer the defect lives

**First, before any implementation.** Run it and read the failure. A test you
did not watch fail is a test you have not established anything with.

*The layer the defect lives* is the part people get wrong. If a document
compiles to the wrong graph, the test belongs at the compiler, not at the HTTP
route that happens to call it. If a prompt produces an unparseable answer, the
test belongs at the parser with the answer the model actually produced pasted
into it — not at a live run.

Prefer a deterministic layer wherever one exists. `compile_workflow` and
`validate_workflow` answer without a model, so a test that asserts on their
verdict costs nothing and cannot flake.

## 3. `set_stage red`

MCP: `kanban_set_stage`. CLI: `openstategraph kanban stage <task_id> red
--actor <you> --test-id <id> --reason "<why it failed>"`.

Both fields are the evidence, and the board demands them: the test's
identifier, and the reason it failed in your own words. "It failed" is not a
reason. "`test_router_names_a_known_branch` failed: the router answered
`writer: draft` and the parser required a bare key" is.

## 4. Make it pass

The smallest change that turns that test green. Not the refactor you can see;
not the second feature you noticed. Those are cards.

## 5. Break the fix, and watch it go red again

The step that gets skipped, and the only one that proves the test holds the
behaviour rather than merely passing beside it. Revert or corrupt the change
you just made — comment out the line, flip the condition — run the test, see
red, then restore.

If the test stays green while the fix is broken, the test is asserting
something else and you have learned that now rather than in three months.

Back up the file you are about to break, or make the break something you can
reverse exactly. Do not rely on a version-control command to undo edits that
are not yet committed.

## 6. `set_stage green`

Same tool and verb, `green`. This is the claim that the test now passes and
that you have seen it fail — both.

## 7. Commit

One card, one commit, wherever the work allows it. The message says what was
wrong and what was ruled out, not just what changed. Stage the files you
touched by path; other people work in this repository too.

## 8. `set_stage finished`, with the commit

`openstategraph kanban stage <task_id> finished --actor <you> --commit <sha>`.
The commit is required here, and that is deliberate: `Resolved` is a column
about evidence, and a card that reached it with no commit is a claim nobody
can check.

## The two standing rules

**Compile before you save.** `compile_workflow` or `validate_workflow` first,
`save_workflow_draft` after. They are deterministic — no model, no credentials,
no cost — and they name the defect precisely. A document saved without them is
a defect the developer finds instead of you.

**Do not run workflows casually.** Runs are gated off by default
(`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`) because they cost money. Run only when the
developer has enabled runs *and* asked for one in this conversation. When you
do, pass the session marker `card:<task_id>` — over MCP as the session id, on
the CLI as `--session-id card:<task_id>` — so the project's own patrol can
tell your work from the developer's traffic and does not later file cards
about its own shadow.

## The one number that reads backwards: a revision loop's budget

A grader's `maxAttempts` counts **candidates judged**, including the one in
hand — so it is one more than the number of times the answer gets sent back.
`2` sends it back once. `1` never sends it back at all: the first candidate is
also the last, and the grader force-passes it.

That matters because *"send it back once"* is the sentence a developer says,
and `1` is the number it reads like. When they say it, type `2`, and say which
number you typed and why. `guard.check` carries the same field with the same
arithmetic. Neither `validate` nor `graph` will object to `1` — the document is
entirely legal, it just cannot revise — so this is one of the few numbers you
have to get right by reading rather than by checking.

The **step budget** is a different ceiling and is not this: it counts
supersteps for the whole workflow, and one lap of a loop can cost several.

## Where a tool binding is visible, and where it is not

`openstategraph graph` cannot show you one. A tool binds *into* an agent —
the edge lands on that node's `tool` port and produces no control flow at all
— so a diagram of the graph is exactly the wrong place to look for it, and an
absent tool looks like a correct picture.

`openstategraph validate` is the one that says: its `Tool bindings:` line
prints the map of tool node to the nodes each one is bound into, and `none`
when nothing is bound. Read it every time you wire a tool, because "the tool
is on the canvas" and "the agent can call it" are two different facts and only
the second one runs anything.

Two things the line will not tell you, both of which refuse at run time:

- **A path field that points at nothing.** `tool.mssql-query`'s `allowlist`
  and the `tool.sql-*` family's `database` are resolved **under the workflows
  root**, and a path that lands outside it is refused — a hard refusal, not a
  convention, so a file one directory above `workflows/` cannot be reached
  however it is spelled. `validate` checks these against the disk and names
  the node and the field.
- **A credential.** The `connection` field holds the *name* of an environment
  variable. Nothing static can know whether it is set, so an unset one is a
  refusal at the first call, naming the variable.

## When a card turns out to be wrong

Two honest outcomes, and both are fine:

- **Already true.** The behaviour the card asks for is present. Add the test
  that pins it, cite the evidence, and finish the card.
- **Not reproducible.** Say so, do not commit a speculative change, and put
  what you tried on the card. A card sent back with what was ruled out is
  worth more than a fix that fits no defect.

Never mark a card finished for work that is half done. File the remainder as
its own card and say which half shipped.
