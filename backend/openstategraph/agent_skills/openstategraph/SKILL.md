---
name: openstategraph
description: Build a workflow with OpenStateGraph — interview the developer, file the work as cards on their board, then build it test-first using only the node types, tools and rules the installed package actually has. Use when someone says "use OpenStateGraph" or asks for a workflow, agent graph, router, grader or pipeline in a project that has OpenStateGraph installed.
---

# OpenStateGraph

Twelve steps, in order. Every later step assumes an earlier one's answer.

## 1. Whose project is this?

Answer this first. Two asks, two directories.

- **A workflow in the developer's project** — the normal case. Work here, in
  the current directory, against the *installed* package.
- **A change to OpenStateGraph itself** — a node family, the compiler, the
  editor. That belongs in an OpenStateGraph checkout.

If the ask is about the platform and this directory is not an OpenStateGraph
checkout, say exactly that and stop. Never edit files inside an installed
package: the next upgrade deletes them and nothing warns anybody.

## 2. Which door do you have?

Both doors do the same things in the same order; check which you have before
promising anything.

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
| read a card | `kanban_show_card` | `openstategraph kanban show` |
| advance a card | `kanban_set_stage` | `openstategraph kanban stage` |
| answer a judgement | `kanban_answer_card` | `openstategraph kanban answer` |
| unstick a stale card | `kanban_release_card` | `openstategraph kanban release` |
| run it | `run_workflow` (gated — step 8) | `openstategraph run` |

## 3. Before anything: read the ground rules

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

## 4. The interview

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

## 5. Sizing — say which one you chose, and why

The interview ends with a size, and the size decides the next move. State the
one you took in a sentence the developer can disagree with.

- **A single-node change** — one field, one edge, one prompt. Go straight to
  the gates: file one card, then step 8. A decision map here is ceremony.
- **A multi-session concept** — several nodes, a new tool, anything you cannot
  finish in one sitting. **Chart a decision map first.** List the decisions
  the concept still owes, resolve them one at a time, and do not start
  building until the ones that block the first card are settled. A decision
  lives in exactly one place; the map is an index, not a store.

Unsure? Ask once. Do not chart a map for a one-line change; do not start
typing into a concept with six open decisions.

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
- **blocked-by** — the cards this one waits on. This is what makes triage
  work; skip it and the board loses its order.
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

Do this for every card, in this order, with no step merged into another.

1. **Attend it.** `kanban_attend_card` / `openstategraph kanban attend`. First
   caller wins; if somebody else holds it, take the next card.
2. **Write the failing test first**, at the layer the defect lives. Run it.
   Watch it fail. A test written after its code asserts what the code does,
   which is not what it should do.
3. **`set_stage red`** with the test id and the reason it failed.
4. **Make it pass.** The smallest change that does it.
5. **Break the fix on purpose** and watch the test go red again. This is the
   step that tells you the test holds the behaviour rather than merely passing
   beside it. Restore.
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

Three starting points, and the tool install is isolated from the project's own
environment in all of them.

- **A fresh folder.** `openstategraph init` and you are ready.
- **An existing project.** `openstategraph init` writes additively — skills,
  agent config files, the workflows root — and touches no dependency.
- **An existing LangGraph codebase.** The developer tool runs from its own
  environment and shares nothing with the project's pins. The *library*
  install does share them, and that is where a clash lives: this package
  requires `langgraph>=1.0,<2`. If their project pins LangGraph 0.x, the
  library install is refused by the resolver, and the refusal is correct. Tell
  them:

  > Your project pins LangGraph 0.x and OpenStateGraph requires 1.x, so the
  > resolver will refuse the library install. The developer tool is
  > unaffected — it runs from its own environment — so you can draw,
  > validate and compile today. Importing a workflow inside your service
  > needs the LangGraph 1.x upgrade first.

  Do not force it with a flag. Do not vendor a copy.

Long form: `references/environments.md`.

## 12. Where this shape came from

Nothing here is copied, and the names are deliberately absent — a name is a
file on somebody else's machine. The shapes are credited instead.

Step 4 is the one-question-per-turn design interview, facts the agent's job
and decisions the developer's. Step 5's map is the practice of planning work
too big for one sitting as an index of decisions rather than a document, and
its gates are a published product/architecture/design/slice workflow. Step 8
is ordinary test-driven development, with the deliberate break made explicit
because it is the step that gets skipped. Step 9 rests on *a report is
testimony, the filesystem is evidence* — learned expensively by people running
many agents unattended.
