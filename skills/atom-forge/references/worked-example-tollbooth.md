# Worked example — the tollbooth memory segment

A real interview, conducted live with the owner on **2026-08-15**. It is the
example this skill ships with because it exercises every part of the procedure:
a redirect fired on dimension 1, the scope question decided the backend without
the backend ever being named, and the read side turned out to be three jobs at
one position — which is where the name came from.

**Provenance.** The answers below are quoted verbatim from the record the
interview produced, `.scratch/install-experience/tickets/17-the-tollbooth-memory-segment.md`.
Read that ticket alongside this file; it is the spec, and this file is how the
spec was arrived at. The question wordings are this skill's
(`interview-questions.md`); the answers are the owner's.

The starting request was memory — the same ask recorded in
`.scratch/install-experience/tickets/02-memory-is-a-story-not-a-feature-list.md`
in the owner's own words: *"context memory, summarisation on fraction of 0.8,
episodic memory, procedural memory etc… unknowns are: existing LangGraph might
have already a memory, or whatever the user's existing project has."* That is a
feature list, not a module. The interview's job was to find the module inside it.

---

## Q1 — Trigger

> *What makes this happen? Is it the flow reaching this point, a condition on
> the data, or the model deciding it is time?*

**A.** *"deterministic — fires whenever flow crosses it."*

**What it decided.** A **node**, not a tool — and the redirect fired in the
other direction at the same moment, which is the useful part. Model-decided
writes were named and sent away:

> *"(Model-decided writes stay the existing `save_memory` tool; the interview's
> redirect rule.)"*

So the module is not "memory". It is the *deterministic half* of memory, and the
model-decided half already existed in `backend/openstategraph/memory.py`. Had
the interview started at "let's build a memory node", both halves would have
ended up inside it and the drawn node would have been the one that lies.

## Q2 — Payload

> *What exactly moves through it — which bytes, produced by whom? And does
> producing them cost tokens?*

**A.** *"upstream output verbatim. Zero tokens."*

**What it decided.** No model call in the write path, so honesty gate 8 is
satisfied by construction and the card may say zero tokens truthfully. Verbatim
also means the node is testable without a provider and the write is
reproducible. Everything the developer might have wanted "summarised first"
becomes an agent node upstream — a separate box, separately paid for.

## Q3 — Scope and lifetime

> *Who else can see this, and when is it gone? Only this step? The rest of this
> run? The next time the same person comes back? Every run of this workflow,
> forever?*

**A.** *"workflow scope in the durable Store (wave 2's backend — survives
restarts). A named segment; the same name placeable between several node pairs,
every position hitting one ledger."*

**What it decided.** The backend, without the question ever being "checkpointer
or Store": *every run of this workflow, forever* maps to `MemoryScope.WORKFLOW`
in `backend/openstategraph/memory.py`, and the Store is durable by default since
install-experience wave 2. A thread-scoped checkpointer was excluded by the same
sentence, because run 2 is a new thread.

The second half of the answer was volunteered and is the more interesting one:
**the segment is named, and a name can appear at several positions.** That makes
the identity of the memory the *name*, not the node — several tollbooths, one
ledger. It is also what makes the smoke test meaningful: run 1 writes at one
position, run 2 reads at another.

## Q4 — Read side

> *Who reads it back, and how does it reach them — a port, a prompt section, the
> card, a tool result?*

**A.** *"the tollbooth — each crossing FURNISHES (injects the segment's
accumulated content downstream as a prompt-composition context section,
machinery not editable), RECORDS (appends the crossing's upstream output), and
SHOWS (card displays segment name + entry count, WYSIWYG like the mount
census)."*

**What it decided.** Three surfaces at one position, and the metaphor that names
the node. Each surface brought a rule with it:

- **Furnish** — a **Context** section of the composed prompt, which is machinery
  and therefore not editable. Only Rules are the developer's. This is the
  `RouterNode` lesson applied before the bug rather than after it.
- **Record** — append, not replace, which is what makes retention a real
  question (Q5).
- **Show** — the card carries segment name and entry count, and it must be true
  *before* a run, following the mount census precedent.

## Q5 — Retention

> *What is the biggest this can get?* (the payload follow-up, asked once
> "appends" was on the table)

**A.** *"last-20 entries by default, a visible card field (`int | None`, None =
unbounded — never Infinity)."*

**What it decided.** Honesty gate 3, satisfied in the answer itself. A visible
field rather than a constant, because an unbounded ledger silently becomes a
context-window failure three months later, at which point the number nobody can
see is the one that needs changing.

## Q6 — Tier and family

> *Is this an atom, a molecule, or an organism — and which family does it join?*

**A.** *"tier: molecule? — the interview's tier question decides against
`vocabulary.test.ts`"*

**What it decided.** A question mark is an honest answer, and it scores on the
readiness card because it names its own resolution: the tiers are declared in
`src/nodes/vocabulary.ts` and locked by `src/nodes/vocabulary.test.ts`, so the
answer is settled against the test rather than by preference. Atoms are inputs,
tools and outputs; a node that transforms state and composes prompt context sits
with the molecules.

## Q7 — Ports and cardinality

> *What comes in, what goes out, what type is each, how many links each?*

**A.** *"ports `in: result → out: result` (pass-through + enrichment;
cardinality per the port rules)"*

**What it decided.** One typed input, one typed output, same type — the node is
transparent to the graph, which is what lets the same segment name sit between
several node pairs without changing what flows. Cardinality is deferred *to the
rules*, correctly: inputs default to 1, outputs to unlimited, `maxConnections`
on the descriptor, `null` and never `Infinity`.

## Q8 — Compile target

> *Name the LangGraph construct this becomes.*

**A.** *"a real state-transforming node using the Store's workflow scope"*

**What it decided.** Gate 4 passes: this is a `StateGraph` node that does
something no existing node does — reads and writes a workflow-scoped Store
namespace at a drawn position. Compare the refusal it would have hit otherwise:
*"A Loop node would compile to nothing new."*

## The gates, as run in the interview

> *"Honesty gates already applied in the interview: no markdown-in-package
> backend (read-only wheel); no model calls in the write path; reducer rule if
> any new state key is multi-writer."*

Three of the ten, tripped and resolved *during* the questions rather than
afterwards — which is the intended behaviour. The markdown-in-package option was
the obvious first design and died on gate 1.

---

## The resulting spec

What the interview produced, as `17-the-tollbooth-memory-segment.md` records it:

| Dimension | Settled |
| --- | --- |
| Trigger | deterministic; fires whenever flow crosses it |
| Payload | upstream output, verbatim, zero tokens |
| Scope | workflow scope in the durable Store; a **named** segment, one ledger across positions |
| Read side | furnish (locked Context section) · record (append) · show (card: name + entry count) |
| Retention | last 20 by default; visible field, `int | None` |
| Tier | molecule, decided against `vocabulary.test.ts` |
| Ports | `in: result` → `out: result`, pass-through plus enrichment |
| Compile target | a state-transforming `StateGraph` node over the Store's workflow scope |
| Gates | read-only wheel, no model call in the write path, reducer rule if multi-writer |

Node type: `memory.segment`.

**The build**, in the pipeline's order: TS card and field schema (segment name,
retention, an inject toggle) → backend builder → registration → `npm run
generate:ports` → package tests → a gallery example (the 23rd, following the
shipped pattern) → site gallery note.

**The smoke that proves it**, which is readiness-card line 10 and the reason the
scope answer had to be durable:

> run 1 writes, run 2 (new thread) reads run 1's entry downstream

on Ollama cloud. Two runs, two threads, one ledger. Nothing less demonstrates
the module; nothing more is needed.

---

## What to take from this example

- **The redirect is the productive move, not the obstruction.** Q1 removed half
  the requested feature by finding it already built.
- **The scope question paid for itself twice** — it chose the backend, and its
  volunteered second half (a *named* segment) became the module's identity.
- **A question mark can be a complete answer** when it names how it resolves.
- **Gates fire mid-interview.** The first design died on gate 1 before anyone
  wrote a file, which is the cheapest possible place for it to die.

---

**Honesty note (2026-08-15, added by the skill's first live client):** this
worked example itself scores 8/10 on the readiness card — it numbered
*Retention* as its fifth question and never ran the failure-modes dimension,
and it treated three honesty gates as "already applied". The first build run
caught that, refused to start at 8, and closed both gaps from the repository.
The complete card — all ten lines, the six failure-mode sentences, all ten
gates run — is recorded in
`.scratch/install-experience/tickets/17-the-tollbooth-memory-segment.md`.
Follow the card, not this example's shortcut.
