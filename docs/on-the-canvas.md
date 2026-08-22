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

**What the agent is handed on the way back round** is the grader's reason
*and* the answer that was rejected, in full — the text the grader judged,
arriving over the `revise` edge that caused the lap. Without the second half a
retry is not a revision: the agent has no memory of its own last attempt, so it
starts the same work from the same standing start and the grader's objection
never moves (`production-ready` 73). When the previous attempt genuinely
produced nothing there is nothing to quote, and the agent is told only why it
was rejected.

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

Set it with nothing selected: the **Workflow** inspector's *Document* section
has a **Step budget** box beside the name. Leave it empty and every run takes
the default of 50; a number between 10 and 1000 is saved into the document's
`settings` and honoured everywhere the workflow runs — the canvas, `/chat`,
`openstategraph run` and the MCP `run` tool. A caller that names its own
number still overrides it. Raising it is rarely the fix for a loop that will
not settle; a grader that can actually pass is.

**What happens when it runs out.** The run does not crash. When a grader is
asked for another lap and there are barely any supersteps left, it stops
revising, takes its own wired `pass` edge, and the answer it had is published
along with a warning naming the grader and how many supersteps were left. A
budget stop is a *report*, not a failed run: it does not change an exit code,
and it is worded differently from the grader running out of its own attempts,
because those are two ceilings with two different fixes.

**"Barely any left" is read off the drawing, not a fixed number.** A grader
looks at the budget once per lap, so what it needs before it may ask for
another one is: enough supersteps for that lap, and then enough for
everything its `pass` branch still has to cross. A grader wired straight to
an output needs three; one wired to a formatter, then a guardrail, then an
output needs five. That is why splicing a node into either branch does not
make a loop start crashing again. A mount counts as one superstep like any
other node, because the mounted workflow runs as a separate graph with a
counter of its own.

**The ceiling a mount runs under is the run's; the mounted package may only
ask for less.** A child starts counting from zero and is given the same
ceiling as the run that mounted it, so a parent of three steps and a child
drawn with a loop are sharing one number that was probably chosen for the
parent. A step budget saved on the mounted package *is* consulted, in one
direction only: it can lower that ceiling for the child, and it can never
raise it. A package that saved 20 supersteps inside a run given 200 stops
itself at 20; a package that saved 1000 inside a run given 50 gets 50, and if
it then runs out the mount says so and names both numbers — the one the
package saved and the smaller one the run could give. It says so on the
gentler outcome too: when the child's own grader stops the loop early under a
ceiling smaller than the package asked for, the run reports the overruled
number once, however many times that package is mounted. A package that asked
for less, or asked for more and never ran low, is told nothing extra. The asymmetry is the
point: a caller who names a step budget has said what any one workflow in
their run may cost, and a mounted package able to raise it would make that
ceiling meaningless. *Any one* — not the whole composition; the paragraph
after next is what that difference costs. When a mounted workflow
does run out, the two outcomes are the ones above, one level down: with enough
slack the child's own grader stops the loop and publishes, and the warning
naming it arrives under the mount (`mount-review/grader1`); with less than the
slack the child cannot stop itself, and the mount reports that it spent the
run's whole step budget without producing an answer. That last one **is** a
failed step — a mount promises a task in and an answer out, and there is no
candidate to publish.

**The number sizes one workflow, not a whole composition — and that is worth
knowing before you set it.** A mount is a separate run with a superstep counter
of its own, so a step budget of 60 does not mean the composition spends 60: a
top workflow with six mounts below it may spend up to seven sixties. Measured,
on a package drawn with a loop that never settles: three levels deep costs
exactly what one level costs, and three copies side by side cost three times.
**Depth on its own is free; what costs is how many mounts are drawn.**

That total is bounded rather than open-ended, and bounded before the run
starts: every mounted workflow is compiled when the parent is, a workflow that
mounts itself is refused there, and each mount's ceiling is the run's or the
smaller number that package saved. So the worst case is arithmetic on the
drawing, and you can ask for it:

```python
with load_workflow("workflows/desk") as desk:
    print(desk.composition_step_budget())   # e.g. 420, for a run of 60
```

It is a ceiling, not a forecast — a real run reaches it only if every loop in
every one of those workflows runs out. Nothing shares one allowance across the
composition on purpose: under a shared, decrementing number a mounted workflow
would behave differently depending on what ran before it, and a mount is one
*isolated* step. Nothing divides the ceiling by depth either, for the same
reason a smaller number is rarely the fix — it would quietly starve the
innermost loop, which is the one hardest to predict.

It belongs to the **package**, so inside a mounted instance the box — and the
name beside it — is disabled with a line saying so. An instance's own state is
`data.overrides`, which is keyed by a step and a field; a workflow's name and
settings belong to no step, so there is nowhere in a mount for them to go.
Change them in the package and every mount of it changes.

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
- **From outside, the mount card says so too.** A mount that pins anything
  reads `· n overridden` beside its census, where *n* is how many of the
  child's nodes this instance has pinned; a mount that follows the package
  says nothing extra. That is what lets one glance at a parent canvas answer
  *which of these follow the package, and which are pinned* — the exception to
  the by-reference promise is visible without opening each one. The count is
  read from the mount's own data, so it is still right when the runtime is
  unreachable and the census is not; overrides that will not parse are left to
  the inspector's validator and count as nothing rather than as a guess.

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

**And what the child noticed reaches you.** A mounted package compiles inside
your build and is never run on its own, so until `workflow-gallery` 75 anything
its compile found — a tool it could not bind, a stale sentence in one of its
prompts, a grader of its own with no `revise` edge — was recorded where nobody
reads it. Those sentences now ride the mounting workflow's warnings, behind
`Inside mounted workflow "<package>":`, and behind the whole chain of packages
when the mount is nested (`outer/inner`). Mount the same package three times and
it still says its piece once: a finding its compile recorded belongs to the
package, not to the mount.

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
| **cache result for** | seconds a node's answer is reused when its input repeats | a speed setting; a memory |
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
