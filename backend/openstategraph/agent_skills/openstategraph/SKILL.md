---
name: openstategraph
description: Build a workflow with OpenStateGraph — interview the developer, file the work as cards on their board, then build it test-first using only the node types, tools and rules the installed package actually has. Use when someone says "use OpenStateGraph" or asks for a workflow, agent graph, router, grader or pipeline in a project that has OpenStateGraph installed.
---

# OpenStateGraph

Twelve steps, in order. Every later step assumes an earlier one's answer.

## 1. Whose project is this?

Answer this first, and from the ask itself: a workflow *in* a project is the
first case below, and only a platform change is worth inspecting a directory
to settle. Two asks, two directories.

- **A workflow in the developer's project** — the normal case. Work here, in
  the current directory, against the *installed* package.
- **A change to OpenStateGraph itself** — a node family, the compiler, the
  editor. That belongs in an OpenStateGraph checkout.

If the ask is about the platform and this directory is not an OpenStateGraph
checkout, say exactly that and stop. Never edit files inside an installed
package: the next upgrade deletes them and nothing warns anybody.

## 2. Which door do you have?

Both doors do the same things in the same order; check yours before promising
anything.

- **MCP.** If the `openstategraph` server is selected in your client, use its
  tools — `openstategraph init` wrote the config your client reads.
- **The command line.** Otherwise every step has a verb. Run
  `openstategraph --help` once; command not found means the tool is not
  installed, and that is the first thing to say.

| Step | MCP tool | Command |
| --- | --- | --- |
| what can be composed | `get_node_vocabulary` | read the installed `compile/port_specs.json` |
| what may be built | `get_engineering_rules` | `references/engineering-rules.md` beside this sheet |
| compile-check | `compile_workflow`, `validate_workflow` | `openstategraph validate` |
| draw what compiled | `compile_workflow`'s diagram | `openstategraph graph` |
| save a draft | `save_workflow_draft` | edit `workflow.json` in the package |
| file a card | `kanban_file_card` | `openstategraph kanban file` |
| what to pick up | `kanban_triage`, `kanban_list_cards` | `openstategraph kanban triage` |
| claim a card | `kanban_attend_card` | `openstategraph kanban attend` |
| advance a card | `kanban_set_stage` | `openstategraph kanban stage` |

The rest of the board — reading a card, answering a judgement, unsticking a
stale one, running a workflow — is in `references/build-loop.md`.

## 3. How big is this? Decide it now, before you ask anything

Classify the ask from the words the developer already used, then say the size
back in one line they can disagree with — *"This is a tweak: I will add
`maxRetries` to that node, with a test that pins the value."* Follow that row
and no other. **Size decides the ritual, never the rules.**

Non-negotiable at every size, and this paragraph is the whole of it: read the
ground rules once per session (step 4); never a node type the registry does
not know, and when nothing registered fits, extend through the family's base,
register it, and only then use it; the failing test is written before the code
that passes it; the card is the one record, because a decision left in the
conversation is lost at the end of it.

| Size | The ask | The ritual, whole |
| --- | --- | --- |
| **tweak** | one setting, one field, one line | one confirming question · no map, no interview, no triage · one card filed from the ask · one failing test · make it pass · commit · `finished` · no break-the-fix |
| **change** | one node or one tool added, one rule edited | two or three questions (step 5) · one card · the full loop of step 8, break-the-fix included |
| **feature or slice** | a workflow, several nodes, anything you cannot finish in one sitting | the whole path — the interview, a decision map, a card per decision, triage, then step 8 for each |

A tweak's card is filed and finished in one sitting: no `attend`, no
`red`/`green` — file it, then stage it `finished` with the commit. A
**decision map** belongs to a feature or a slice only; it is an index of the
decisions the concept still owes, not a store, and a decision lives in
exactly one place.

Unsure between two rows? Take the smaller one and say so: being wrong there
costs one more question, and guessing larger costs everything in the row.

## 4. Before anything: read the ground rules

Two reads, every time, before the first node exists.

- **The vocabulary** — every node type, every port id and type, what may
  legally connect to what, and the prompt sections that are locked. Guessing
  these produces documents that fail validation for reasons the verdict can
  only explain afterwards.
- **The rules** — what may be *built* out of them: the interface → abstract →
  base → concrete ladder, extension by registration, cardinality on the port,
  one field schema, tests first, and the rule that settles most arguments:
  **never invent a node type**. Never a type the registry does not know — not
  a rule against new types, a rule about order. When nothing registered fits,
  extend through the family's base, register it, and only then use it.

`references/engineering-rules.md` is that text, installed beside this sheet as
a copy of the file the package ships, so the two doors cannot disagree.

## 5. The interview

**How much of this you run was decided in step 3.** A tweak asks one
confirming question and goes to step 8. A change asks two or three — which
node or tool, what check settles it, and the one thing the ask left open.
Only a feature or a slice runs every dimension below.

Say this, then start:

> Tell me what the workflow should do, and I will ask you the questions a
> senior engineer would ask before building it.

**One question per turn**, generated from *this* concept's mechanics — never
a fixed list read at the developer. Their last answer decides your next
question. Recommend an answer each time so they can agree in one word; the
decision is theirs and the facts are yours, so go and look before asking
something the installation can answer.

Keep going until every dimension below has a concrete answer **or an
explicitly accepted gap**. An accepted gap is a correct outcome; a silent one
is not.

| Dimension | The question it answers |
| --- | --- |
| Input | what goes in, from whom, in what shape |
| Output | what comes out, and who reads it |
| Steps | which node type carries each step — named, from the vocabulary |
| Judgement | where a revision loop belongs, and what ends it |
| Tools | what must be fetched, from where, with whose credentials |
| Ground truth | what may not be invented, and what happens when it is missing |
| Budget | the step budget, and the token budget for the whole build |
| Done | what "done" looks like, as something you can check |

If a dimension's honest answer is *this platform cannot do that yet*, say so
and file a card for it. That is a correct outcome, not a failed interview.

Long form: `references/interview.md`.

## 6. Filing — every decision and every task becomes a card

The board is the memory: a decision recorded only in the conversation is lost
at the end of it. File each with `kanban_file_card` (or
`openstategraph kanban file`), carrying:

- **kind** — `task` or `bug` for work an agent may take; the judgement kind
  for anything a human must weigh, which lands in Needs You.
- **title** — the symptom or the want, never the fix.
- **story** — the plain-English want, in the developer's own words.
- **done-when** — the check that settles it. Something you can run.
- **priority and its reason** — one sentence citing evidence from this
  interview. A priority with no reason is a guess with a label.
- **blocked-by** — the cards this one waits on, by the **full id** filing
  printed. A bare slug resolves to nothing and strands the card forever.
- **agent_model / agent_effort** — defaults by shape:

| Shape of the work | model | effort |
| --- | --- | --- |
| mechanical — a rename, a field, a fixture, a doc row | a small model | low |
| judgement — a design, a prompt, an ambiguous defect | a large model | high |

These two are advice, not a contract. A platform that cannot choose its own
model treats them as advice and says so.

Long form of the card text: the ticket sheet installed beside this one.

## 7. Triage — take the top card

Call `kanban_triage` (or `openstategraph kanban triage`). It answers with the
cards in order and, for each, `why_here` — the rule that put it there.
Unblocked cards that block others come first, by how many they block; then
unblocked by priority; blocked last. Take the top one. If you want a different
card, say which rule you are overriding and why.

## 8. The build loop, once per card

Do this for every card, in this order, with no step merged into another. A
tweak runs 2, 4, 7 and 8 of it and files its card at 1's place (step 3).

1. **Attend it.** `kanban_attend_card` / `openstategraph kanban attend`. First
   caller wins; if somebody else holds it, take the next card.
2. **Write the failing test first**, at the layer the defect lives. Run it.
   Watch it fail. A test written after its code asserts what the code does,
   which is not what it should do.
3. **`set_stage red`** with the test id and the reason it failed.
4. **Make it pass.** The smallest change that does it.
5. **Break the fix on purpose** and watch the test go red again. This is the
   step that tells you the test holds the behaviour rather than merely passing
   beside it. Restore. **Skip it only when the test already discriminates the
   value** rather than its presence — `maxRetries == 2` is already red on a
   wrong value, `"maxRetries" in data` is not — and say which of the two you
   did. Test-first is not weakened either way: the red step stays.
6. **`set_stage green`.**
7. **Commit.**
8. **`set_stage finished`** with the commit.

Two standing rules inside the loop:

- **`compile_workflow` or `validate_workflow` before any
  `save_workflow_draft`.** They answer deterministically, no model, no cost.
  Never validate a document by running it.
- **Never `run_workflow` unless runs are enabled and the developer has said
  so.** Runs are off by default (`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`) because a
  run costs money. If you do run something while working a card, tag it with
  the session marker `card:<task_id>`, so the project's own patrol can tell
  your work from the developer's.

Long form: `references/build-loop.md`.

## 9. Helpers

Spawn a subagent for a card only when it passes **all four** gates:

1. **Reproducible without a person** — no question you would have to ask.
2. **The decision is already made** — the card carries it.
3. **Blast radius contained** — you can name the files it may touch.
4. **Cost** — no model calls beyond the budget the card states.

Use the card's `agent_model` and `agent_effort`. Brief it with the card's own
text and the engineering rules, nothing else. When it returns, **verify its
report against the tree** — the commit, `git status`, the tests — because a
report is testimony and the filesystem is evidence. Then say what it did, in
three lines. A platform with no subagents runs the loop inline and says so;
nothing else changes.

Long form: `references/subagents.md`.

## 10. Explaining

Explain with **text shapes** by default: a numbered list, a small table, an
indented tree, a fenced pseudo-graph. Pick the smallest view that makes the
point.

A Mermaid sketch is allowed for exactly one thing: a **proposed** flow that
does not exist yet. What exists is drawn by the compiler — `compile_workflow`
returns the diagram of the graph it actually built, and `openstategraph graph`
prints it. Never hand-draw a workflow that compiles: your sketch and the
compiler will disagree eventually and the reader cannot tell which one lied.

## 11. Environments

Three starting points — a fresh folder, an existing project, an existing
LangGraph codebase — and one fact that settles all three: the tool installs into
its own environment and shares nothing with the project's pins, while the
*library* shares them completely and requires `langgraph>=1.0,<2`. Read
`references/environments.md` before promising anything about an install.

## 12. Where this shape came from

Nothing here is copied and no name is given — a name is a file on somebody
else's machine, and a stranger's agent sent looking for one finds nothing. The
shapes are credited instead: a one-question-per-turn design interview, planning
as an index of decisions rather than a document, ordinary test-driven
development, and *a report is testimony, the filesystem is evidence*.
