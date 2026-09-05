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

**And you are not the only writer of that file.** A coding agent editing
`workflow.json` while you watch the board is the normal way of working on a
real project, so the editor no longer assumes the document it loaded is still
what is on disk. Every save says which version it is editing, and one that
would overwrite somebody else's change is refused: the file is left alone, this
workflow stops saving automatically, and you are told, with the two choices
spelled out. **Open it again from Workflows** to take the version on disk,
discarding what is on screen — after a refusal that open does not put your
unsaved edits back, because they are the thing you just chose against. Or
**press Save** to overwrite the file with what is on screen. Nothing is decided
for you, and neither version is thrown away until you say which one you want.

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

**One molecule is not a reasoning step, and it says so by sitting in its own
section.** `Resolution` holds the **Resolve vocabulary** node: it looks up
what the words in a question mean in your domain — *"persian gulf" is called
`Middle East Gulf (MEG)` on `load_shipping_region_v2`* — before the model
runs, and costs no model call. It is a **step**, not a tool on the agent's
bus, and the difference is the point: a step runs every time, and a tool is
chosen. When the model chose which source told it what a word meant, it chose
differently on different runs.

It also reports what it **covered**. A lookup that finds nothing looks exactly
like a word that was never ambiguous, so the node says which is which: a
source that declares what it holds gives a conclusive *not covered*, one that
does not says so plainly, and a failed search is neither.

**Resolve source** is the same section's second node and the same idea about
a different question: *which of the stores that could answer this is
answering it?* A warehouse often holds one figure from several systems of
record — a balances desk, a plant tracker, a public dataset — at different
grains, and two of them can disagree while both are right. So the node asks
your catalogue which ones are live, settles on the one the question named or
the one your data declares as its default, and hands the answer the
alternatives it did **not** take. What a reader gets is *"the figures for
Russian gasoline supply come from BAV… this data also holds JODI and the
plant tracker, and they can disagree. Ask for one by name"* — rather than a
number with no lineage.

It reports coverage for the same reason, and the two states it must never
blur are *there is nothing to choose* (your catalogue declares one source)
and *we could not tell* (it declares none). And where several sources are
live and nothing settles which, it chooses **nothing**: that is a question
for the person asking, not a coin toss.

### Three SQL atoms, and the difference between them is not the dialect

`Tools · atoms` holds three ways to read a database, and picking the wrong one
is not a small mistake — the fields do not mean the same things.

**What all three share is one sentence:** every one of them runs a single
read-only `SELECT`, caps the rows it returns, hands back the same markdown
table, and answers a mistake with a refusal a model can act on rather than an
exception — that is the family base, and a dialect adds a driver and a
connection to it, nothing more.

| | **Run Query** (`tool.sql-query`) | **Run T-SQL Query** (`tool.mssql-query`) | **Run Databricks Query** (`tool.databricks-query`) |
| --- | --- | --- | --- |
| Reads | a `.sqlite` file inside `workflows/` | an MSSQL server | a Databricks SQL warehouse |
| Points at it with | `Database file` — a path | `Connection variable` — the **name** of an environment variable | three variable **names**: hostname, HTTP path, token |
| Read-only comes from | the driver: SQLite opens the file `mode=ro` and refuses every write however it is spelled | a **statement gate** plus an uncommitted transaction — see below | the **statement gate** alone — see below |
| Which tables may be read | every table in the file | only those an **allowlist** pinned | only those an **allowlist** pinned |

**Read-only is a weaker word on the two warehouse columns, and it is written
down here rather than assumed.** No warehouse driver offers SQLite's `mode=ro`.
`ApplicationIntent=ReadOnly`, which is the string most people expect to close
this for MSSQL, is an availability-group *routing* hint: it chooses which
replica you talk to, and it refuses nothing. So both warehouse atoms guard with
a **statement gate** — exactly one statement, and only a `SELECT` or a
`WITH … SELECT` — and both restrict what it may name to the allowlist.

The T-SQL atom can add one thing the Databricks atom cannot: it opens its
connection without autocommit and rolls it back unconditionally. A Databricks
SQL warehouse has no session read-only mode, and the connector's autocommit
handling has moved between releases, so that atom does not ask for one; a
rollback is attempted on the way out and ignored if the warehouse declines. In
neither case is the engine refusing a write, and a workflow that needs that
guarantee should be given a login that cannot write.

**Every connection field holds a name, never a value.** A workflow document is
committed, so a pasted DSN or token would be a password in a repository; the
field is refused if you type one, and the refusal does not echo it back — a
Databricks token is caught even though `dapi…` is also a legal variable name.
The T-SQL default is `OPENSTATEGRAPH_MSSQL_URL`, ours because ODBC has no
conventional variable to keep a DSN in. The Databricks defaults are the
vendor's own — `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`,
`DATABRICKS_TOKEN` — so a machine already set up for the connector needs no
edits on the card at all. With a variable unset the tool answers a refusal that
names it and sends nothing, one variable at a time so there is one thing to go
and do — which is what a workflow built against a warehouse that does not exist
yet does on every run, on purpose.

**The `Allowlist YAML` field is not optional and is not a convenience.** It
names a file inside `workflows/` whose `resolvers` each carry a `pin:` map,
and the **values** of those maps — `dbo.invoice_line_v2`, not `dbo.invoice_line` —
are the only tables a query may name. A pin is a human's choice of *which
version* of a logical table is safe to read, so naming the unversioned logical
name is refused too. Anything unpinned comes back with the whole pin list, so
the model's next attempt is written against tables that exist. Configure no
allowlist and the tool refuses every query: the dangerous default is the one
that reads as configured.

Each driver ships as an extra — `pip install 'openstategraph[mssql]'` or
`pip install 'openstategraph[databricks]'`. The base install carries no
database driver, and a missing one is a refusal that names the extra rather
than an import error.

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
**A grader is shown the run as well as the answer:** when tool calls failed
this run it is handed that record, and a candidate whose every tool call failed
cannot pass on how well it reads — the verdict names the tool and what it
reported, and an exhausted loop publishes with the answer marked unverified.
That is the whole mechanism. There is no Loop node, and there does not need to
be — a loop is a **cycle in the graph**, not a wrapper around one.

**How many laps it gets, and the one number that reads backwards.** *Max
attempts* on the grader counts **candidates judged**, including the one in
hand — so it is one more than the number of times the answer is sent back.
Set it to **2** to send it back once; **1** never sends it back at all,
because the first candidate is also the last and the grader passes it through.
The slider reads both numbers out so the sum is never yours to do. Nothing
refuses a `1`: it is a legal document that simply cannot revise.

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
  on a `feedback` port, and only three outputs produce one — a Grader's or a
  Guard's `revise`, and a Human approval's `rejected` (the table below). Any
  other backward edge is refused, with a message pointing you at the grader.
- **A loop always has a way out.** `revise` is a grader's *conditional* branch,
  so the cycle contains a decision by construction — it cannot spin forever
  because nothing is choosing. A loop with nothing deciding on it is reported
  by the compiler, not only refused by the canvas, because a document can
  arrive without ever being drawn.

**Three nodes can close a loop, and only one of them costs a model call.** The
`revise`-shaped output is a port type, not a node type, so anything that
declares one is a way out of a cycle:

| Node | Decides by | Its way out |
| --- | --- | --- |
| **Grader** (`route.grader`) | a model's judgement | `revise` |
| **Guard** (`guard.check`) | **code** — a package function, no model | `revise` |
| **Human approval** (`human.approval`) | a person, at a pause | `rejected` |

**A Guard is a Grader's mechanical sibling.** It asks the same pass-or-revise
question and answers it by running one of your package's `functions/` against
the candidate — the function returns an empty string to pass, or the sentence
that goes back over `revise`. Same two ceilings as a grader (*Max attempts*,
and the step budget below), same feedback port, same loop.

Write the function with a second parameter — `fn(text, summary)` — and it also
receives this run's own record of its tool calls (how many were made, how many
returned anything, and the last failure's tool and message), so a check can say
*"no evidence arrived"* rather than arguing with the prose; one parameter is
still the contract.

Reach for it whenever the check is **decidable without judgement**: a schema
rule, a lookup against a known set, a format. Routing a deterministic check
through a model is not merely wasteful — the model relays what it was told, so
internal check names have leaked into a customer's answer that way here before.

Three checks need no `functions/` file at all; type the name into *Check* and
the Guard is wired:

| `check:` | Passes when |
| --- | --- |
| `numbers_in_prose` | every figure in the answer traces to something this run retrieved |
| `row_counts_in_prose` | a count of rows is published as rows, not as the things they describe |
| `zero_outside_coverage` | a reported *none* is not really a period the data says it never held |

A package function of the same name still wins. And a Guard on the path is
what silences the compiler's *this answer could carry an ungrounded number*
finding — the finding reports the **absence** of a gate, never the adequacy of
one, because judging a check's contents from the compiler is how a checker
starts reporting success on a wrong answer.

### A Check router — the same function, deciding where rather than whether

A Guard's `revise` is a `feedback` port, so it can only go back to something
that takes feedback: an agent, a router. That is exactly right for a loop and
it is the wrong shape for the other question a package function can answer —
*which way does this go*. An Output takes `result`, and no deterministic node
could hand it one.

**Check router** (`route.check`) is the Guard's sibling on that axis. It runs
one of your package's `functions/` against the candidate exactly as a Guard
does, and reads the return as the **name of a branch** instead of as a
complaint. You list the branches on the card, one out-port each, and every one
of them carries `result` — so an Output, an agent or another fork may hang off
any of them.

| | Decides | Answers with | Its outputs are |
| --- | --- | --- | --- |
| **Router** (`route.classifier`) | a model | one of your branch names | `text`, one per branch |
| **Check router** (`route.check`) | **code** — a package function, no model | one of your branch names | `result`, one per branch, plus `fallback` |
| **Guard** (`guard.check`) | **code** — a package function, no model | `""` to pass, else the sentence to send back | `pass` (`result`) and `revise` (`feedback`) |

The **fallback** port is always there and is not one of your rows. It is taken
when the function returns a name no branch declares, returns nothing, or
raises — and the reason is recorded either way. A name is matched
case-insensitively and a branch's own id works as well as its name, but nothing
outside your own list is ever taken as a branch: an unrecognised answer goes to
`fallback`, never to a guess.

Reach for it when the decision is a **fact the run already has**. The case it
was built for: a question that names no date range must be asked back rather
than answered on an assumed window. A `resolve.vocabulary` already reports the
range as uncovered, for free and without a model — a `route.check` turns that
into the edge that reaches an Output. Sent through a Router instead, the same
question was classified onto a data branch and never asked.

Each branch takes **one** edge, like every other conditional way out.

**An Output prints what reaches it, and nothing else.** It has no text field.
Wiring a branch straight to one publishes whatever that branch was carrying —
the user's own question, usually, handed back to them. The one thing an Output
supplies on its own is the floor beneath an empty run: a run that reaches it
with nothing at all says so, rather than reporting a success that says nothing
(`osg-agent-experience/46`).

**A Static Output prints a sentence you wrote, and nothing else** — the exit
to draw the ask-back onto. One field, one inbound port called `when`, and the
port's value is never printed: it is how the branch *reaches* this exit, not
what the exit says. It is required, because an exit nothing wires to is never
run; it takes many links, because two branches that end in the same reply are
one node. Your `{{key}}` slots are filled from the run's context, exactly as
they are in an Input's prompt.

Two node types rather than one field on the first, deliberately
(`osg-agent-experience/55`). A `text` field on an Output would have to either
lose to arriving content — and something always arrives on an ask-back branch,
which is why that reading never fires — or win over it, which would let a typed
field silently discard a run's answer at the one node where "the run's answer"
is defined. With two types the ambiguity has nowhere to live, and which
behaviour is in force is legible from the canvas rather than from a precedence
rule. The older shape — a `function.<name>` returning a constant, one node in
front of an Output — still works and is now one node more than you need.

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

**What happens when it runs out — the good case first, and it needs a grader.**
When a grader is asked for another lap and there are barely any supersteps
left, it stops revising, takes its own wired `pass` edge, and the answer it had
is published along with a warning naming the grader and how many supersteps
were left. That is a *report*, not a failed run: it does not change an exit
code, and it is worded differently from the grader running out of its own
attempts, because those are two ceilings with two different fixes.

**And the plain case, which is reachable on any document.** The guard above is
a grader looking ahead; a cycle with no grader on it has no guard at all. Then
the budget simply runs out, and the run **ends as an error** — the ceiling
stops it. You get a sentence naming the workflow and the number, explaining
that supersteps are not laps, and saying that what a loop which never settles
needs is a grader that can pass it or an exit its own state can reach, rather
than a bigger number. It is recorded as its own kind of turn — neither a
finished run nor a failed node — because the graph was working perfectly well
when the ceiling stopped it, and because that run was billed for the whole
budget.

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

### A router that opens more than one desk, and what the record says about it

A router's **Match** field has a *Run every match* setting. Turn it on and the
question can belong to several branches at once: every matching desk runs, in
parallel, in the same step.

The record beside the answer names **every** branch that ran — `cost + risk`,
not `cost`. That is worth saying out loud because it used to name one. The
canvas was never the problem: cards light as they run, so both desks glowed
either way. It was the record that outlived the glow, and it reported the run
that opened two desks exactly as it reported the run that opened one.

Over the API the field to believe is **`routes`**: router node id → every
branch label that router matched, on `RunResult`, on `POST /api/runs`, on the
terminal `done` frame and in `openstategraph run --json`. `decisions` is still
there, still one label per node, and it is the label the graph *dispatched* on
— useful for a grader or an approval, which have no branches to report and
never appear in `routes` at all. If the question is *what did this run do*,
read `routes`.

---

## 4. A mount runs another workflow as one step

Drag **Workflow** onto the canvas and point it at a saved workflow's slug. It
becomes one node: a task goes in, an answer comes out. It is the only mount
card in the palette — see *Workflow or Team?* below for what happened to the
second one.

Each of your own packages also has a row in the palette's **Packages** section.
Dragging a row onto the canvas, or Tabbing to it and pressing Enter, mounts it;
the small **Open** control that appears on the row when you hover or focus it
opens that package as the document you are editing, and the address bar becomes
`?w=<slug>`.

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

**And what the child keeps between turns is a choice you make on the card.**
*What the child remembers* has three settings, and the first is what every
mount has always done:

- **Nothing · a fresh run every time.** The default. The mount is one isolated
  step: it is handed the task and the conversation so far, and keeps nothing of
  its own. An approval inside it can still pause and resume *within* one turn.
- **Its own conversation.** The mounted workflow gets a memory of its own on
  this thread. It stops being handed the parent's conversation and keeps its
  own instead, so the second turn picks up where the first left off. Reach for
  this when the mounted workflow genuinely *is* a running dialogue — and not
  otherwise: two of these running at the same time write to the same place and
  conflict. Note what it does and does not carry: the child's own conversation
  and its records of what each of its nodes produced survive; its per-turn
  working scratch — the answer it gave, its revision budget — is reset at the
  start of every turn, exactly as it is for a saved thread of a workflow run on
  its own.
- **Nothing, and it keeps no place of its own.** No record is kept at all. An
  approval step inside such a child *does* still stop the run and can still be
  answered — the pause travels up and the workflow you actually ran holds the
  place — but because the child kept nothing, answering it re-runs the mounted
  workflow **from its first step**, so everything it did before the gate
  happens a second time. Use it only for a child you are sure is a pure
  function of its task — and if it is not, you are told: a mount set to this
  over a workflow that holds an approval anywhere inside it is a compile-time
  finding, printed as a warning when the workflow is loaded, before the run
  reaches the gate. It is advice and not a refusal — the document runs, pauses
  and answers, and no exit code moves. (`openstategraph validate` prints it
  too, since `organisms-first-class` 66 — under **Notes:**, below the verdict,
  which is where a finding that cannot move an exit code belongs.)

  (An earlier version of this line said such a child "cannot pause". That is
  what LangGraph documents about a stateless *subgraph*, and it is not what
  this boundary does: a mount is not a subgraph node, so the interrupt is held
  by the parent's own record. Measured, `organisms-first-class` 64.)

This is a different promise from the default one, which is why it is a setting
and not something inferred: a mount that remembers can answer the same question
differently depending on what came before it.

**When a mounted workflow stops for a person, it says so by name.** A gate
raised inside a mount used to print only its own sentence, so a reviewer
reading `run` or `resume` a day later saw the question and had no way to tell
which document wrote it. Both now print an **asked by** line — the mounted
packages between the workflow you ran and the one asking, outermost first — so
the document to open is on screen beside the question. A gate in the workflow
you actually ran says nothing extra, and neither does a child set to keep
nothing: it stored no place of its own to read the path back from.

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

## 7. Watching a run — the timeline, and the word for what the playhead does

A run gets its own surface at the bottom of the editor. The first run of a tab
brings it up by itself; after that your own answer stands. **`Mod+Shift+L`**
opens and closes it, and there is a control for it in the top bar. It does not cover
the canvas — the canvas gets shorter and the timeline sits below it, because it
is a time axis you read *while* watching the thing it measures. Drag its top
edge for more room.

**Every draggable edge in the editor shows the same grip:** a short bar centred
on the edge, quiet at rest so you can find it without hunting, and a heavier
stroke the moment your pointer or your keyboard focus lands on it. The
timeline's top edge has one; so does the left edge of the chat and inspector
column. If an edge has no bar, it does not move. What you grab is a band a few
pixels wide straddling the edge rather than the line itself, so the drag starts
whether you land just inside the panel or just outside it.

Two things are drawn side by side: **bars** on the left, one row per node with
a time axis over them, and the **trace** on the right, which is the detail for
whichever bar you click.

Its header says **which run this is** — the question it was asked, whether it is
running, the **thread** the run reported, and what it spent in **tokens**. The
thread is the run's own identifier and the one you can look a run up by; it
appears only once the run has told the editor what it is. Two runs of the same
question have the same header without it.

### What a step asked, and what it produced

Click a bar and the column beside it answers in three grains: what the bar
**is** (node, lane, when it opened and closed), what it **asked and produced**,
and then the whole trace.

**Produced** is what that node wrote, on that lap. A revision loop's second
attempt is a bar of its own and carries its own answer, so the first bar keeps
the first draft rather than showing you the last one. A bar that refused —
where a rule rejected the candidate before any model was asked — shows the
check that refused it and the sentence it wrote, and says that no model was
called.

**Asked** is the half the run mostly does not record, and the panel says so
rather than showing you an empty box. The one case it does record is a child
the run **spawned**: a fanned-out worker, a subagent, a background task all
carry the task they were handed, and that is quoted. A top-level node's prompt
is assembled inside the runtime and never reaches the editor.

### Rows — one per node, and a gutter for what ran inside what

**Every node of the workflow gets a row**, named down the left in the order the
run first heard from it, and its bars sit on that row. A node that ran twice —
a revision lap — is two bars on one row, badged `×2`, because it is the same
node and not a second one.

**Every child the run dispatched gets a row of its own, indented under the node
that dispatched it**: a fanned-out worker, a subagent, a background task. Three
workers running at once read as three parallel rows, which is what happened;
two children called `impact-analyst` are two actors and are numbered `1 of 2`
and `2 of 2` so you can tell them apart. The `│` gutter down the left is how
deep each row sits — a child dispatched from inside another child is one level
further in again.

A child's bar is a **measured** start and end: the run dated both. A bar in the
workflow's own rows is a weaker claim, and the panel says so on every bar you
select — it is the span between the frames that arrived, not two dated ends.
The selected bar also says its **depth**, which is the same gutter counted.

**A mounted workflow is a bar, not a row.** It is one node on your canvas, so
it draws hatched on that node's row, at the length its own two dated frames
give it. Its insides are not rows here; the compiled-graph preview is where you
open a mount up.

### Replay — reading the recording back, and spending nothing

When a run has finished, the timeline gains a **transport**: play and pause, a
restart, one step forward or back, and three speeds. A **playhead** moves along
the recording, and a scrub track lets you drag it.

> **Replay here does not re-run anything.** It moves a marker over frames that
> already arrived. No model is called, no graph is executed, nothing is
> charged. It is a profiler.
>
> **LangGraph uses the same word for the opposite thing.** Its *replay* forks
> from a checkpoint, re-executes the nodes and fires the model calls again,
> producing a different run and a new bill. If you arrived from those docs,
> that is not this button.

**Re-run** — forking a run from a checkpoint and executing it again — is not
built here at all. To ask the same question again, ask it again.

Stepping moves **by frame, not by second**: the useful unit is *what happened
next*, and a ten-second model call is one thing happening. The keyboard rows
for play/pause and stepping are in the shortcuts drawer with everything else —
that drawer is the published list of shortcuts, and it is printed from the same
table the editor dispatches from, so it cannot fall behind.

### Four things the timeline refuses to tell you, on purpose

- **A live run gets no scrubber.** While frames are still arriving there is no
  right-hand edge to drag to, and a slider that cannot reach its end is lying
  about what it can do. You get a playhead pinned to the head instead, and the
  transport appears when the run stops.
- **An unmeasured span reads `—`, never `0 ms`.** A dash means *nobody timed
  this*, and it is a different fact from a step that took no time. A run with
  no clock at all is drawn as a run nobody timed, never as an instant one.
- **A lane the run never closed is drawn open-ended**, and says which kind of
  open: a background task still running outside this run, a recording that
  ended owing an account, or a child that simply had not finished. None of them
  is given a number, because the run measured none.
- **A run in flight shows no token count.** Tokens are reported when a run
  finishes, so there is no partial figure to show and none is invented — the
  number a reader is most likely to quote is the worst one to estimate. A run
  that finished and reported nothing reads `—`; a run that called no model at
  all reads `0`, because those are two different facts.

---

## 8. The top bar's radar — what your own runs are telling you

Beside the timeline's control in the top bar there is a **radar** icon, and it
opens the **patrol board**: four columns of cards about runs you have already
made, filed by a pass over the findings this project recorded while those runs
happened. Nothing on it is about the document you are drawing — it is about
what actually ran.

A card is one finding: a tool asked the same question several times, a tool
that answered differently each time, a node that failed after its retries. The
board's job is to say what each one needs **next**, which is why the columns
are `Detected`, `Needs You`, `In Progress` and `Resolved` rather than a list of
severities. `Needs You` is the one to know: it is a judgement the patrol
deliberately did not make, and it is yours to settle.

[The patrol board](the-patrol-board.md) is the whole of it — how a patrol
starts, what each column allows, what a card copies onto your clipboard, and
the evidence a card carries before it is allowed to be `Resolved`.

---

## 9. The bottom bar — what the work has cost

Along the bottom of the editor there is a thin bar with four cells:
**Total**, **Cached**, **This tab** and **Models**. *Total* is every token
every run this project ever recorded has spent — not this document's, not
this sitting's, the whole store. *Cached* is how much of that a provider
served from its own cache. *This tab* is the sitting you are in right now: a
sitting starts when the tab does, survives a refresh, and ends when the tab
closes. *Models* names the models that sitting has used, each with what it spent.

**A cell that has nothing to say says `—`, and it never says `0` instead.**
The two are different claims: `0` means a provider reported a figure and the
figure was nought, and a dash means nobody reported one at all. Most providers
do not report a cache figure, and some report no reasoning tokens — so a dash
there is about the provider, not about your run.

Click the bar and it opens **Tokens spent**, the same figures broken out into
three tables: *Grand total, by model* (input, output, cached, reasoning,
total, with an all-models row read off the wire rather than re-added),
*This tab, by model*, and *Sessions, newest first* — with the sitting you are
in marked **this tab**. Escape closes it. The bar is always there; the
breakdown waits for the first answer to land, because a table of dashes is not
more honest than no table.

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
| **guard** | `guard.check` — the same pass-or-revise verdict a grader reaches, decided by one of your package's functions instead of a model | a permission check; something that only blocks |
| **check router** | `route.check` — the same package function, read as the **name of a branch** rather than as a complaint; every way out carries `result`, so an Output may take one | a Router (a model picks that one); a Guard (that one decides *whether*, not *where*) |
| **step budget** | supersteps a run may take | "max retries" or "iterations" |
| **cache result for** | seconds a node's answer is reused when its input repeats | a speed setting; a memory |
| **template** | a starting document; produces a workflow and stops existing | a node type; a live link |
| **example** | a finished package shipped in the install; you take a **copy** | one of your workflows; something you mount |
| **organism** | a whole assembly — drawn or mounted | only the things you can drag |
| **resolver** | a step that looks up what a word means here, before the model runs, and reports what it **covered** as well as what it found | a tool the agent may choose to call; a table or column lookup |
| **replay** | moving a playhead over a run that already happened — a profiler; nothing is executed and nothing is charged | LangGraph's *replay*, which re-executes nodes and fires the model calls again |
| **re-run** | forking from a checkpoint and executing again, at the cost of the model calls | **not built here** — ask the question again instead |
| **eval** | grading a workflow **offline** against a committed dataset whose answers are known — `openstategraph eval` | the grader node's in-run verdict, which routes rather than scores |
| **slug** | a package's folder name, minted by the backend at first save and then frozen — `workflows/<slug>/`, `?w=<slug>`. The first save is where you are **asked for the name** it is minted from, and the dialog says it cannot be changed afterwards; until then the top bar reads *Untitled* | a title or display name, or anything you choose |
| **system of record** | the store a figure actually came from — named in the answer, with the ones it was not taken from listed beside it | the workflow's database connection; a table |

---

## Where to go next

- [Getting started](getting-started.md) — install, first run, the shipped example
- [Patterns](patterns.md) — seven arrangements and when each earns its keep
- [Ports and edges](ports-and-edges.md) — the type system, and every rule that
  refuses a connection
- [Building an atom](building-an-atom.md) — when you want a node that does not
  exist yet
- [The patrol board](the-patrol-board.md) — the radar in the top bar: what a
  patrol is, the four columns, and the evidence a card carries
