---
name: openstategraph
description: Build a workflow with OpenStateGraph — interview the developer, file the work as cards on their board, then build it test-first using only the node types, tools and rules the installed package actually has. Use when someone says "use OpenStateGraph" or asks for a workflow, agent graph, router, grader or pipeline in a project that has OpenStateGraph installed.
---

# OpenStateGraph

Thirteen steps, in order. Every later step assumes an earlier one's answer.

## 1. Whose project is this?

Answer from the ask itself. **A workflow in the developer's project** is the
normal case: work here, in the current directory, against the *installed*
package. **A change to OpenStateGraph itself** — a node family, the compiler,
the editor — belongs in an OpenStateGraph checkout; if this is not one, say so
and stop. Never edit files inside an installed package: the next upgrade
deletes them and nothing warns anybody.

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

Non-negotiable at every size: read the ground rules once per session (step 4);
never a node type the registry does not know — extend, register, then use, and
step 4 says how; the failing test comes before the code that passes it; the card
is the one record, since a decision left in the conversation is lost with it.

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
check settles it, the one thing the ask left open. Only a feature runs it all.

Open with *"tell me what the workflow should do, and I will ask you the questions
a senior engineer would ask before building it"*. Then **one question per turn**,
generated from *this* concept's mechanics — never a fixed list read at the
developer; their last answer decides your next. Recommend an answer each time so
they can agree in one word; the facts are yours, so go and look before asking what
the installation can answer. Keep going until each of the **nine dimensions** below
has a concrete answer **or an explicitly accepted gap** — an accepted gap is
correct, a silent one is not.

| Dimension | The question it answers |
| --- | --- |
| Input | what goes in, from whom, in what shape |
| Output | what comes out, and who reads it |
| Steps | which node type carries each step — named, from the vocabulary |
| Judgement | where a revision loop belongs, and what ends it |
| Tools | what must be fetched, from where, with whose credentials |
| Ground truth | what may not be invented, and what happens when it is missing |
| Units | what every pinned numeric column is measured in — a unit, or "unknown" |
| Budget | the step budget, and the token budget for the whole build |
| Done | what "done" looks like, as something you can check |

If a dimension's honest answer is *this platform cannot do that yet*, say so and
file a card: a correct outcome, not a failed interview. `references/interview.md`.

## 6. Recommend a shape — and ask what will multiply

The interview says what this workflow *does*, not what shape it should *be*, and
the shape decides whether the fifteenth of anything is a new folder or an edit to
the other fourteen. Ask one more question before any card exists:

> **What in this concept is going to multiply?** Specialists, sources, tenants,
> teams, checks, decisions — and how many of each, today.

Read those counts against the catalogue in `references/shapes.md` — its first
table picks the spine, its second names the additions — then say, in one turn:

- **the shape you recommend**, in the platform's own idioms, naming the node
  types it uses, and **what it costs** in calls, folders and test suites;
- **the two you rejected**, one reason each — a recommendation with no rejected
  alternatives is an assertion; the developer cannot weigh what they never saw.

**Name it in the same turn.** Two to four words from the concept's own nouns
(*Support Triage*), with the slug it would mint — `workflows/<slug>/`, a directory
minted at the first save and frozen there, so this is the only moment it is free.
Proposed, **never silently chosen**; it is the document's `name` when you first
save. Then ask them to confirm shape and name: one question, one turn. Only then
do you size the cards and file them.

A concept with one of everything is one agent, and recommending that is a correct
outcome. The failure this step prevents is the other: fifteen specialists built as
fifteen of everything — every node correct, the shape wrong, nobody able to say so
until it ran.

## 7. Filing — every decision and every task becomes a card

The board is the memory: a decision left in the conversation is lost with it.
File each with `kanban_file_card` / `openstategraph kanban file`:

- **kind** — `task` or `bug` for work an agent may take; the judgement kind for
  anything a human must weigh, which lands in Needs You.
- **title** — the symptom or the want, never the fix; **story** — the want in the
  developer's own words; **done-when** — a check you can run.
- **priority and its reason** — one sentence citing this interview's own
  evidence. A priority with no reason is a guess with a label.
- **blocked-by** — the cards this one waits on; a bare name resolves against the
  board, and triage names back an id no card carries.
- **agent_model / agent_effort** — defaults by shape:

| Shape of the work | model | effort |
| --- | --- | --- |
| mechanical — a rename, a field, a fixture, a doc row | a small model | low |
| judgement — a design, a prompt, an ambiguous defect | a large model | high |

Advice, not a contract; long form of the card text is the ticket sheet beside this.

## 8. Triage — take the top card

Call `kanban_triage` (or `openstategraph kanban triage`). It answers with the cards
in order and, for each, `why_here` — the rule that put it there. Unblocked cards
that block others come first, by how many they block; then unblocked by priority;
blocked last. Take the top one, or name the rule you are overriding.

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
6. **`set_stage green`.** 7. **Commit.** 8. **`set_stage finished`**, commit named.

Two standing rules inside the loop:
- **`compile_workflow` or `validate_workflow` before any
  `save_workflow_draft`.** They answer deterministically, no model, no cost;
  never validate a document by running it.
- **Never `run_workflow` unless runs are enabled and the developer has said so.**
  Runs are off by default (`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`) because a run costs
  money. If you do run one while working a card, tag it with the session marker
  `card:<task_id>`, so the patrol can tell your work from the developer's. Long form:
  `references/build-loop.md`.

## 10. The gate, then the brief

When the last card reaches `finished`, run the gate **before you write a word of
the brief**, and quote each answer. Green tests and a VALID verdict are not
"clean": both were true of a document whose canvas held four red diagnostics
nobody had looked at.

1. `openstategraph validate workflows/<slug>` (or `validate_workflow`) — no
   `PROBLEMS FOUND:` **and** no `Notes:`. It reads the document against every
   node type's own fields and ports, and its notes name any node with nothing
   wired into it.
2. Those are the checks the canvas draws in red, so **a browser look is not
   required** — do not ask the developer for one.
3. One smoke run with a neutral question, ending at **exactly one** exit. `run`
   prints `This run finished at more than one Output` when it did not; that
   line is a failure, not a note.
4. `openstategraph graph workflows/<slug>` (or `compile_workflow`'s diagram) for
   the picture. Explain in text otherwise, and **never hand-draw a workflow that
   exists** — a Mermaid sketch is for a **proposed** flow only, because two
   pictures leave the reader no way to tell which one lied.

Then **at most twenty lines**, in your reply and again to
`workflows/<slug>/AGENTS.md` under a dated heading — no card field carries a
gate, so that file is the record. Open with **Not clean yet:** and every warning
the gate printed, verbatim, or the two words **no warnings**; never nothing, and
never a summary. Then the **shape** step 6 confirmed; the **cards finished**,
each with its commit; **what validates and what runs**, naming the verb and its
answer; the **next two or three steps** in `kanban triage`'s order; **what only
the developer can supply** — a key, a connection, a decision; the diagram last.

## 11. Helpers

Spawn a subagent for a card only when it passes **all four** gates: **reproducible
without a person**; **the decision is already made** (the card carries it); **blast
radius contained** (name the files it may touch); **cost** (nothing beyond the card's
budget). Use its `agent_model` and `agent_effort`, and when it returns **verify the
report against the tree** — a report is testimony, the filesystem is evidence. No
subagents? Run the loop inline. `references/subagents.md`.

## 12. Environments

Three starting points — a fresh folder, an existing project, an existing LangGraph
codebase — settled by one fact: the tool installs into its own environment and
shares nothing with the project's pins, while the *library* shares them and
requires `langgraph>=1.0,<2`. Read `references/environments.md` first.

## 13. Where this came from

Nothing here is copied and no name is given — a name is a file on somebody else's
machine, and a stranger's agent sent looking for one finds nothing. The practices
are credited instead: a one-question-per-turn interview, planning as an index of
decisions, TDD, and *a report is testimony, the filesystem is evidence*.
