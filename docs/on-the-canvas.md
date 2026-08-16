# On the canvas: what each thing is

You have the editor open and a palette down the side. This page is the answers
you need before the first drag, in the order you need them. It assumes nothing
except that you can see a canvas.

Everything else in `docs/` is written for someone extending, deploying or
integrating. This one is for someone **drawing**.

---

## 1. A workflow is a folder

What you draw is saved as `workflows/<slug>/workflow.json` — a folder on disk,
not a row in a database. Beside it live the things the workflow uses: `tools/`,
`functions/`, `skills/`, `knowledge/`, `tests/`.

That folder is the whole artifact. You can commit it, copy it, or hand it to
someone else, and it compiles to a plain LangGraph `StateGraph` — an ordinary
Python object that runs anywhere Python runs. The editor authors it; nothing
you draw depends on the editor to run.

---

## 2. Atoms, molecules, organisms — and only one tier you can get two ways

The palette is ordered by **what a thing is made of**:

| Tier | What it is | How you get one |
| --- | --- | --- |
| **atom** | no logic — an input, a formatted output | drag |
| **molecule** | one reasoning step — an agent, a router, a grader | drag |
| **organism** | a whole working assembly | **draw it, or drag it** |

That last row is the one worth remembering, because it answers most of the
questions people arrive with.

**An organism is an assembly, not an item.** A supervisor with its workers and
a join is an organism — but you build it by drawing four molecules, not by
dragging one card. A revision loop is an organism too, and you can get it
*either* way: draw it here, or drag in a workflow that already contains one.

Organisms are the only tier with two routes. Atoms and molecules you drag;
assemblies you draw *or* mount.

---

## 3. A revision loop is two edges

This is the shape most people come for: **run a step, check it, run it again
with the problems included.**

You build it with the pieces already in the palette:

```
input → agent → grader ──(pass)──→ output
          ↑                │
          └───(revise)─────┘
```

The grader's `revise` output connects back to the agent's `feedback` input.
That is the whole mechanism. There is no Loop node, and there does not need to
be — a loop is a **cycle in the graph**, not a wrapper around one.

Two things the editor does for you here:

- **You cannot draw a loop by accident.** A cycle is only legal when it closes
  on a `feedback` port, and `revise` is the only output that produces one. Any
  other backward edge is refused, with a message pointing you at the grader.
- **A loop always has a way out.** `revise` is a grader's *conditional* branch,
  so the cycle contains a decision by construction — it cannot spin forever
  because nothing is choosing.

The safety net underneath is the **step budget**. It is counted in
*supersteps*, not laps: with a fan-out, one lap can cost several. Do not read
it as "maximum retries" — the grader's own attempt limit is that.

> Starting from `openstategraph new my-thing --template routed-qa` gives you
> this shape already wired, with a router in front of it.

---

## 4. A mount runs another workflow as one step

Drag **Workflow** onto the canvas and point it at a saved workflow's slug. It
becomes one node: a task goes in, an answer comes out. It is the only mount
card in the palette — see *Workflow or Team?* below for what happened to the
second one.

**By reference, not by copy.** This is the part worth being precise about:

- The mount **points at** the package. Edit that package and every mount of it
  sees the change.
- Editing *inside* a mount does **not** change the package. Your change is
  stored as an **override on the parent** — the document with the mount node in
  it. The child package's bytes do not move, and other mounts of the same
  package are untouched.
- The editor shows you which fields you have overridden, and offers a revert
  that puts the package's own value back.

So one saved workflow is a **class**, and each mount of it is an **instance**
with its own settings. Two mounts of one package are two independent instances.

Opening one has its own address — `?w=concierge/wf-music` is "the `wf-music`
mount inside `concierge`", not the package on its own.

**What crosses the boundary, and what does not:** the question goes in and the
answer comes back. The child gets its own graph state, its own tools, its own
knowledge and its own memory namespace — none of the parent's working state
reaches it, and the parent never sees the child's.

The one deliberate exception: **the conversation does cross.** A mounted child
that talks to a person needs the dialogue so far, or it re-asks a question that
was already answered one message ago. Working state is isolated; the
conversation is shared.

### Workflow or Team?

**There is no longer a choice, because there was never a difference.** Until
schema v3 the palette offered a second organism, `team.workflow`, beside
`workflow.subgraph`. This page used to tell you to weigh them. That advice is
withdrawn: the two compiled through one backend builder with no branch and
identical ports, so the only things separating them were a different glyph, an
`outcome` field that turned out to be documentation, and a "loops until its
grader passes" note that the *mounted child document* earns. None of those is a
kind of node. Schema v3 collapsed Team into Workflow, and a saved document
still carrying `team.workflow` is rewritten on load — same node id, same slug,
same `overrides`, same authored `outcome` text.

So **a team is a package shape, not a node type**: a supervisor, its workers
and a grader wired into a revision loop, living in `workflows/<slug>/` and
mounted with the same Workflow card as anything else. `openstategraph new
my-team --template team` still scaffolds exactly that.

The two things the old Team card claimed both survived, and both moved to where
they were already true:

- **Expected outcome** is now an optional field on the Workflow card, labelled
  *Expected outcome (documentation)*. It is not read by the compiler. It says
  what this mount is for; enforcement is the **child package's own grader
  criteria**, and nothing links the two automatically.
- **"loops until its grader passes"** is shown for any mount whose child
  document really does have a grader with a wired `revise` edge. It was always
  earned from the child rather than granted by the card, which is why it did
  not need a node type of its own.

The card also states the gap now. Write an outcome on a mount whose child has
no grader and it reads **"no grader — nothing checks the outcome"**; where the
child has a grader that never routes `revise`, **"its grader never revises —
nothing sends a weak answer back"**. A run in that state also emits a
developer-channel `runtime_warnings` entry naming the node and the slug. Loud,
never fatal.

The cost you are weighing is in **the package you point at**, never the card.
A supervisor-and-workers package buys a planning call and a fan-out; if the
work has one worker role, that is a planner you pay for and do not use.

---

## 5. A template is a copy, and then it is gone

`openstategraph new my-thing --template routed-qa`, or **New Workflow → Start
from** in the editor, gives you a starting document. That is all it is:

| | Original | If the original changes later |
| --- | --- | --- |
| **Mount a workflow** | a package you can open and edit | **every instance changes** |
| **Start from a template** | a starter document | **nothing changes** — the link was severed on use |

Nothing records which template you started from, deliberately: a document with
a second, invisible owner is a document nobody can reason about.

So *"template"* and *"mount"* are not two words for the same idea. One is
copy-paste; the other is a live reference.

---

## 6. An example is a whole package, and you take a copy of it

`openstategraph examples list`, or the **Examples** shelf in the Workflows
panel, shows the worked examples — one per pattern the canvas can
express. They ship *inside* OpenStateGraph, not inside your project, which is
why they never appear in your workflow list, in `/chat`, or to a workflow that
asks the platform what exists. Until you take one, they are not yours.

```
openstategraph examples copy evaluator-optimizer
openstategraph run workflows/evaluator-optimizer "Write a two-sentence release note."
```

An example is on the **copy** side of the table above, and for a plain reason:
those files live inside the installed package. A mount is a live reference, so
mounting one would mean your workflow quietly changing on your next
`pip install -U`, pointing at a folder you cannot edit. Copying severs it — the
copy is an ordinary package of yours, a draft until you publish it, and nothing
upstream reaches back into it.

Several examples mount others, so a copy brings those too (`nested-mounts`
writes three folders). The command says which before it writes them.

`openstategraph examples copy --all` takes the lot — all-or-nothing, so one
folder already in the way means nothing is written, and the size and count are
printed *before* the first byte, because one of these examples ships a 1 MB
database.

**The verb is `copy`, and there is no `eject`.** They would be two names for
one act: taking a finished package out of the install and into your project,
severed. And half of "eject" would be a lie — in the ecosystem the word borrows
from, ejecting is the hidden thing leaving the framework for good, while these
files stay exactly where they were, read-only and replaced on your next
upgrade. **A package is a definition. A template creates one. A mount
instantiates one. An example is a finished package you take a copy of.**

| | Original | If the original changes later |
| --- | --- | --- |
| **Mount a workflow** | a package you can open and edit | **every instance changes** |
| **Start from a template** | a starter document | nothing changes — severed on use |
| **Copy an example** | a whole package inside the install | nothing changes — severed on copy |

Where a template differs: a template is *rendered* (your name goes into it) and
gives you empty `tools/` and `tests/` directories to fill. An example is copied
byte for byte, already full — its tests, its knowledge store, its eval fixture,
and for `sql-qa` a database — because it is the package that was actually built
and run, and its `AGENTS.md` records what it answered.

---

## Glossary

The words this product uses, and what each one must not be mistaken for.

| Word | Means | Not |
| --- | --- | --- |
| **workflow** | a folder with a `workflow.json`; compiles to a `StateGraph` | a run, a template |
| **package** | the same folder, seen as a reusable definition | a PyPI distribution *(that sense exists too, in the install docs)* |
| **mount** | a node that runs another workflow, **by reference** | a copy; inline expansion |
| **instance** | one mount of a package, with its own overrides | a second copy of the package |
| **override** | a per-instance setting, stored on the **parent** | an edit to the package |
| **revision loop** | grader `revise` → agent `feedback`; ends when the grader passes or the budget runs out | an agent's internal tool-calling |
| **step budget** | supersteps a run may take | "max retries" or "iterations" |
| **template** | a starting document; produces a workflow and stops existing | a node type; a live link |
| **example** | a finished package shipped in the install; you take a **copy** | one of your workflows; something you mount |
| **organism** | a whole assembly — drawn or mounted | only the things you can drag |

---

## Where to go next

- [Getting started](getting-started.md) — install, first run, the shipped example
- [Patterns](patterns.md) — seven arrangements and when each earns its keep
- [Ports and edges](ports-and-edges.md) — the type system, and every rule that
  refuses a connection
- [Building an atom](building-an-atom.md) — when you want a node that does not
  exist yet
