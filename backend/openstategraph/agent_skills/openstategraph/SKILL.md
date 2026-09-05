---
name: openstategraph
description: Build a workflow with OpenStateGraph — interview the developer, file the work as cards on their board, then build it test-first using only the node types, tools and rules the installed package actually has. Use when someone says "use OpenStateGraph" or asks for a workflow, agent graph, router, grader or pipeline in a project that has OpenStateGraph installed.
---

# OpenStateGraph

Fourteen steps, in order. Every later step assumes an earlier one's answer.

## 1. Whose project is this?

Answer this from the ask itself. Two asks, two directories.

- **A workflow in the developer's project** — the normal case. Work here, in
  the current directory, against the *installed* package.
- **A change to OpenStateGraph itself** — a node family, the compiler, the
  editor — belongs in an OpenStateGraph checkout. If this is not one, say so and stop.

Never edit files inside an installed package: the next upgrade deletes them and
nothing warns anybody.

## 2. Which door do you have?

Both doors do the same things in the same order; check yours first.

- **MCP.** If the `openstategraph` server is selected in your client, use its
  tools — `openstategraph init` wrote the config your client reads.
- **The command line.** Otherwise every step has a verb: run `openstategraph
  --help` once; command not found means it is not installed — say that first.

| Step | MCP tool | Command |
| --- | --- | --- |
| what can be composed | `get_node_vocabulary` | `openstategraph nodes [<type>]` |
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
`maxRetries` to that node, with a test that pins the value."* Follow that row and
no other. **Size decides the ritual, never the rules.**

Non-negotiable at every size, and this paragraph is the whole of it: read the
ground rules once per session (step 4); never a node type the registry does not
know, and when nothing registered fits, extend through the family's base, register
it, and only then use it; the failing test is written before the code that passes it;
the card is the one record — a decision left in the conversation is lost with it.

| Size | The ask | The ritual, whole |
| --- | --- | --- |
| **tweak** | one setting, one field, one line | one confirming question · no map, no interview, no triage · one card filed from the ask, `attended` · one failing test, `red` · make it pass, `green` · commit · `finished` · no break-the-fix |
| **change** | one node or one tool added, one rule edited | two or three questions (step 5) · one card · the full loop of step 9, break-the-fix included |
| **feature or slice** | a workflow, several nodes, anything you cannot finish in one sitting | the whole path — the interview, a decision map, a card per decision, triage, then step 9 for each |

A **decision map** — an index of the decisions a concept still owes, each in one
place — belongs to a feature or a slice. Unsure between two rows? Take the smaller.

## 4. Before anything: read the ground rules

Two reads, every time, before the first node exists.

- **The vocabulary** — every node type, every port id and type, what may legally
  connect to what, and the prompt sections that are locked. **Then quote the field
  list for every type you are about to write, in your reply, before you write a
  line of `data`** — the keys and their kinds, copied from `openstategraph nodes
  <type>` (or `get_node_vocabulary`). A field invented is one you did not quote.
- **The rules** — what may be *built* out of them: the interface → abstract →
  base → concrete ladder, extension by registration, cardinality on the port, one
  field schema, tests first, and the rule that settles most arguments: **never
  invent a node type** — never one the registry does not know. Not a rule against
  new types, a rule about order: when nothing fits, extend the family's base,
  register it, and only then use it.

`references/engineering-rules.md` is that text, installed beside this sheet as a
copy of the file the package ships, so the two doors cannot disagree.

## 5. The interview

**How much of this you run was decided in step 3.** A tweak asks one confirming
question and goes to step 9; a change asks two or three — which node or tool, what
check settles it, and the one thing the ask left open. Only a feature runs it all.

Open with *"tell me what the workflow should do, and I will ask you the questions
a senior engineer would ask before building it"*. Then **one question per turn**,
generated from *this* concept's mechanics — never a fixed list read at the
developer; their last answer decides your next. Recommend an answer each time so
they can agree in one word; the decision is theirs and the facts are yours, so go
and look before asking what the installation can answer.

Keep going until every dimension below has a concrete answer **or an explicitly
accepted gap** — an accepted gap is a correct outcome, a silent one is not.

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

If a dimension's honest answer is *this platform cannot do that yet*, say so and
file a card for it. That is a correct outcome, not a failed interview. Long form:
`references/interview.md`.

## 6. Recommend a shape — and ask what will multiply

The interview says what this workflow *does*, not what shape it should *be* — and
the shape decides whether the fifteenth of anything is a new folder or an edit to
the other fourteen. So ask one more question before any card exists:

> **What in this concept is going to multiply?** Specialists, sources, tenants,
> teams, checks, decisions — and how many of each, today.

Read those counts against the catalogue in `references/shapes.md` — its first
table picks the spine, its second names the additions — then say, in one turn:

- **the shape you recommend**, in the platform's own idioms, naming the node
  types it uses, and **what it costs** in calls, folders and test suites;
- **the two you rejected**, one reason each — a recommendation with no rejected
  alternatives is an assertion; the developer cannot weigh what they never saw.

**Name it in the same turn.** Two to four words from the concept's own nouns
(*Support Triage*, *Release Notes*), with the slug it would mint — `workflows/<slug>/`.
A slug is a directory, minted at the first save and frozen there, so this is the only
moment it is free. Proposed, **never silently chosen**: one word from the developer
changes it, and it is the document's `name` when you first save.

Then ask them to confirm the shape and the name: one question, one turn. Only
when they have answered do you size the cards and file them.

A concept with one of everything is one agent, and recommending that is a correct
outcome. The failure this step prevents is the other one: fifteen specialists
built as fifteen of everything on one canvas — every node correct, the shape
wrong, and nobody able to say so until it ran.

## 7. Filing — every decision and every task becomes a card

The board is the memory: a decision recorded only in the conversation is lost at
the end of it. File each with `kanban_file_card` / `openstategraph kanban file`:

- **kind** — `task` or `bug` for work an agent may take; the judgement kind for
  anything a human must weigh, which lands in Needs You.
- **title** — the symptom or the want, never the fix; **story** — the plain-English
  want, in the developer's own words; **done-when** — a check you can run.
- **priority and its reason** — one sentence citing this interview's own
  evidence. A priority with no reason is a guess with a label.
- **blocked-by** — the cards this one waits on. A bare name resolves against
  the board; an id no card carries is named back at you, and triage says so.
- **agent_model / agent_effort** — defaults by shape:

| Shape of the work | model | effort |
| --- | --- | --- |
| mechanical — a rename, a field, a fixture, a doc row | a small model | low |
| judgement — a design, a prompt, an ambiguous defect | a large model | high |

Advice, not a contract. Long form of the card text: the ticket sheet beside this.

## 8. Triage — take the top card

Call `kanban_triage` (or `openstategraph kanban triage`). It answers with the
cards in order and, for each, `why_here` — the rule that put it there. Unblocked
cards that block others come first, by how many they block; then unblocked by
priority; blocked last. Take the top one, or name the rule you are overriding.

## 9. The build loop, once per card

Every card, in this order, no step merged into another. A tweak runs 1, 2, 3,
4, 6, 7 and 8 of it — every step but the deliberate break.

1. **Attend it.** `kanban_attend_card` / `openstategraph kanban attend`. First
   caller wins; if somebody else holds it, take the next card.
2. **Write the failing test first**, at the layer the defect lives; run it and
   watch it fail. A test written after its code asserts what the code does.
3. **`set_stage red`** with the test id and the reason it failed.
4. **Make it pass.** The smallest change that does it.
5. **Break the fix on purpose** and watch the test go red again: that is what
   tells you the test holds the behaviour rather than merely passing beside it.
   Restore. **Skip it only when the test already discriminates the value** rather
   than its presence — `maxRetries == 2` is already red on a wrong value,
   `"maxRetries" in data` is not — and say which of the two you did.
6. **`set_stage green`.** 7. **Commit.** 8. **`set_stage finished`** with the
   commit.

Two standing rules inside the loop:
- **`compile_workflow` or `validate_workflow` before any
  `save_workflow_draft`.** They answer deterministically, no model, no cost;
  never validate a document by running it.
- **Never `run_workflow` unless runs are enabled and the developer has said so.**
  Runs are off by default (`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`) because a run costs
  money. If you do run one while working a card, tag it with the session marker
  `card:<task_id>`, so the patrol can tell your work from the developer's. Long
  form: `references/build-loop.md`.

## 10. Hand the developer a brief

When the last card reaches `finished`, write **at most twenty lines** — in your
reply, and again to `workflows/<slug>/AGENTS.md` under a dated heading, so the
next agent reads what the developer read: the **shape** you recommended in step 6
and they confirmed; the **cards finished**, each with its commit; **what
validates and what runs**, naming the verb and its answer; the **next two or
three steps**, in the order `kanban triage` gave them; and **what only the
developer can supply** — a key, a connection, a decision.

Then the picture, and it is the compiler's: paste the output of
`openstategraph graph workflows/<slug>` (or `compile_workflow`'s diagram).
**Never hand-draw a diagram of a workflow that exists** — you have just built it
and know the shape by heart, which is precisely why the drawing would come from
memory, and two pictures leave the reader no way to tell which one lied.

## 11. Helpers

Spawn a subagent for a card only when it passes **all four** gates: **reproducible
without a person**; **the decision is already made** (the card carries it); **blast
radius contained** (name the files it may touch); **cost** (nothing beyond the card's
budget). Use its `agent_model` and `agent_effort`, and when it returns **verify the
report against the tree** — a report is testimony, the filesystem is evidence. No
subagents? Run the loop inline and say so. `references/subagents.md`.

## 12. Explaining

Explain in text by default, and pick the smallest view that makes the point. A
Mermaid sketch is allowed for one thing only: a **proposed** flow that does not
exist yet. What exists is drawn by the compiler — step 10.

## 13. Environments

Three starting points — a fresh folder, an existing project, an existing LangGraph
codebase — settled by one fact: the tool installs into its own environment and
shares nothing with the project's pins, while the *library* shares them and
requires `langgraph>=1.0,<2`. Read `references/environments.md` first.

## 14. Where this came from

Nothing here is copied and no name is given — a name is a file on somebody else's
machine, and a stranger's agent sent looking for one finds nothing. The practices
are credited instead: a one-question-per-turn interview, planning as an index of
decisions, TDD, and *a report is testimony, the filesystem is evidence*.
