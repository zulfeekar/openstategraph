# The patrol board: what your own runs are telling you

You are in the editor and there is a radar icon in the top bar. Press it and a
board slides in with four columns and cards on it — cards about runs you
already made, filed by something you never started.

This page is what those cards are, who is allowed to move them, and what each
column will not let you do. It assumes you have run a workflow at least once
and nothing else.

Everything here is the board itself. The two doors onto a single card are
reference pages of their own: [the `openstategraph` command](cli.md) for
`kanban` and `patrol`, and [the MCP layer](mcp.md) §5a for the same lifecycle
over MCP.

---

## 1. A patrol reads runs; it does not run anything

A **patrol** is a pass over the findings this project has already recorded
against its own runs. It calls no model and asks no question — it reads what
`run_findings` noticed while your workflows ran, decides what each finding is
worth, and files a card for anything not already on the board.

Three findings exist today, and they are the whole of what a card can be about:

| Finding | What was seen |
| --- | --- |
| `REDUNDANT_TOOL_CALL` | one tool, several calls, the same answer every time |
| `UNSTABLE_TOOL_RESULT` | one tool, several calls, different answers |
| `NODE_FAILURE` | a node that failed after its retries were spent |

A patrol is **idempotent by design**: a card is identified by
`project_id + thread_id`, so a second pass over the same evidence files
nothing new, and a card whose stage has already left `unattended` is never
touched again even if the finding reappears. The patrol files new work; it
never re-litigates work somebody claimed.

**And it skips the work done on the board itself.** Reproducing a card's
defect means running a workflow, and that run is recorded like any other — so
a patrol reading everything eventually reads its own reflection and files a
card about the work done on the last card. The key above does not save it:
that thread is genuinely new. The rule is a marker on something a run already
records, the **session** it belongs to: a run made while working card
`<task-id>` carries the session `card:<task-id>`, a patrol driver's own runs
carry a session beginning `patrol:`, and both are skipped by the next pass.
`kanban attend` prints the marker for the card it just claimed, the board's
copied instruction carries it, and every door takes it — `openstategraph run`
as a session flag, `run_workflow` as `session_id`. An unmarked run is
ordinary traffic and is still read (`kanban-patrol/08`).

### Four ways to start one

- **The board's own button.** An empty board says `No patrol has run yet` and
  carries `Run patrol`, because a blank screen that means *nothing has looked*
  and a blank screen that means *everything is clean* are two different facts
  and one appearance.
- **The command line.** `openstategraph patrol run`.
- **MCP**, for a model composing against this project.
- **The bundled skill file.** `openstategraph .` installs
  `.claude/skills/kanban-patrol/SKILL.md` (and the same file under
  `.agents/skills/`) into your project, so a coding agent that scans either
  directory can run the loop itself through whichever door it has.

A patrol outlives the board. Close the panel and it keeps going; the top bar
shows a mark while one is live, and the board carries one sentence about the
last one — `Patrol running…`, a finished line naming how many cards it filed,
or the reason it failed, printed rather than softened.

A patrol needs the project's own `project_id`, the identity in §7. Without one
it stops and says so rather than inventing an identity.

---

## 2. Four columns, and two of them are places you arrive

| Column | What it means | What you can do |
| --- | --- | --- |
| `Detected` | the patrol is confident; it needs doing, not deciding | hand it to an agent |
| `Needs You` | the patrol stopped on a judgement only a person may make | `Answer` |
| `In Progress` | somebody, or an agent, is on it | **nothing** |
| `Resolved` | closed, and carrying its evidence | **nothing** |

Only the first two are ever *filed* into. `In Progress` and `Resolved` are
**reached**: the first by a claim, the second by evidence. A patrol that could
open a card straight into Resolved would be closing work nobody did.

Which column a card is in is **derived, never stored** — from what kind of
thing it is and what has happened to it since. Kind is fixed at filing and
never moves; the lifecycle is the only thing an actor changes. Lifecycle
outranks kind, which is why a claimed judgement leaves `Needs You`: somebody
is already answering it, and leaving it there would invite a second person to
answer it too.

**`In Progress` having no control is a decision, not an omission.** It is the
board's only defence against two actors working one card, which is why the
claim underneath it is atomic against the database rather than advisory.

The wire names for the same four are `detected`, `needsYou`, `inProgress` and
`resolved`; that is what an agent filtering the board asks for.

### Three tabs, and what each one has behind it

The board has tabs — `Workflows`, `OSG Engineering` and `GitHub`.

`Workflows` is this project's own board and is always live. **`OSG
Engineering` is the shared maintainers' board, and it is live whenever
`OPENSTATEGRAPH_KANBAN_URL` names one** — same four columns, same cards, same
live updates, reading the rows whose `board` column says so. Unset, it says
`Not configured` and names that variable, so the sentence tells you what to
set rather than only that something is missing. `GitHub` says `Not available`,
because this product has no GitHub connection yet.

Neither unbuilt tab shows four empty columns, because empty columns are a
claim (*a patrol ran and found nothing*) rather than a state.

---

## 3. What a card offers, and why none of it is "assign"

Nothing on this board can start a coding agent, because a browser cannot. So
the card does not pretend to: it hands you the text you paste into whichever
agent you actually run.

- **`Copy instruction`** puts a self-contained brief on the clipboard —
  nothing installed required. It carries the task id, the title, where the
  finding was seen, the classifier's own sentence about *why this matters*
  when it wrote one, an instruction to work test-first, and the four
  `openstategraph kanban` lines that report progress back. The *why* line is
  the one that makes a card actionable: `Context: workflows · gap` tells an
  agent nothing; *"asked the same table 4 times"* tells it everything.
- **`Copy ID`** is just the task id, for an agent that already has the CLI or
  MCP door and can read the row live.
- **`Answer`** is the `Needs You` control. The patrol stopped on a judgement
  it should not make, so the card is waiting on a decision rather than on
  work.
- **`Attend`** is the underlying claim the two copy buttons hand off: it moves
  a card to `In Progress` and makes it claimable. It is exclusive and atomic —
  the first caller wins, and a second is told exactly who has it.
- **`Release`** appears only on a card the system has already flagged. §6.

An agent may never claim a card in `Needs You`. That refusal is structural, in
the store, not a convention an agent is trusted to observe.

---

## 4. An In Progress card says how far it has got

A column answers *somebody has this*. It does not answer the question a reader
is actually asking, so the card says the stage instead:

| stage | what the card says |
| --- | --- |
| `attended` | `Queued` |
| `red` | `In progress — test written` |
| `green` | `In progress — test passing` |
| `finished` | `Awaiting review` |

**And it says it while you watch.** A coding agent moving a card is another
process writing the store, so since `osg-agent-experience/36` an open board
holds a stream (`GET /api/kanban/events`) on which the server reports that the
store changed, and the board refetches — a card filed or advanced from the CLI
or over MCP moves in front of you, with no Refresh. Refresh is still there for
a board that was closed when it happened.

`finished` reads `Awaiting review` and not Resolved on purpose. `finished` is
a **claim**; the evidence gate in §5 is the only thing that carries a card
into the Resolved column, so a finished card that has not cleared the gate is
still In Progress and says the truthful thing — it is waiting on a reader, not
on work.

---

## 5. Resolved demands evidence, and it is recorded as it happens

A card reaches `Resolved` by carrying proof that a test went red and then
green. The proof is recorded **at the transitions**, never re-typed at the
end:

- **`red`** needs a test id and the reason it failed, both non-empty.
- **`green`** needs the test id to *match* the one recorded at `red`. A
  different test passing is not evidence that this one does.
- **`finished`** needs red and green already durably on the card, plus the
  commit. No evidence argument is accepted here, because there is nothing left
  to assert — only what already happened.

A caller missing any of it is refused by name, with the gap stated plainly.
The card then shows its evidence: the test id on the face of it, the red
reason behind it.

The order matters as much as the fields. Recording the whole story at the end
would be a claim about the past written by whoever wanted the card closed;
recording each half as it happens is the difference between evidence and
assertion.

---

## 6. Stale is a flag, and Release is yours to press

Every stage write is a heartbeat. A claim with no heartbeat for an hour is
**flagged**, and nothing else happens: flag, never auto-release. The card says
so — *attended, nothing new in over an hour* — and offers `Release`, which a
person presses.

`Release` resets the row all the way back: stage, actor, heartbeat and all
four evidence fields, so the next claim starts clean. A partial reset would
bleed one attempt's evidence into the next.

Two guards, and both matter:

- **You can only release what was already flagged.** The button cannot invent
  staleness. If somebody resumed the card in the meantime, the release is
  refused rather than clobbering them.
- **A `Resolved` card is never stale, so it never offers `Release`.** Nobody
  writes to a resolved card again — that is what resolved means — so its
  heartbeat is old by design. Staleness names an *abandoned* claim, not a
  discharged one, and `Release` is the one control here that destroys data.

---

## 7. Fan-out is not repetition, and the card says which

The same finding — one tool, several calls, the same answer — is three
different problems depending on where the calls came from, and a card that
called them all "redundant" would send an agent to write a fix for something
nobody did:

- **One node asked the same question several times.** Real sequential
  repetition, real cost, and the remedy is a note on the tool. Priority rises
  with the call count.
- **Several parallel workers each asked once.** Pure fan-out. The run still
  paid for every call, but nobody wrote a loop and a tool note fixes nothing;
  the remedy, if it is worth one, is a lookup shared *across* workers. Filed
  low, whatever the count.
- **Some of each.** Neither sentence is honest on its own, so the card says
  both counts and names both remedies.

The distinction is the call's namespace, and it is drawn by the classifier
rather than left to whoever reads the card.

---

## 7a. A run where nothing came back is not waste, and its card is keyed by the refusal

The patrol's first three kinds all ask *was this asked twice*, and a warehouse
that has stopped answering is not asked twice — three different SELECTs are
three different calls, so they group into nothing. That is how a full day of
*HYT00 Login timeout expired* refusals produced no card at all and was
found by hand
(`osg-agent-experience/74`). `every-tool-call-failed` is the kind that asks
the other question — *did anything come back* — and it fires when every call a
run made was refused, and refused the same way.

Its card is keyed by the **refusal's first line**, not by the thread, because
one expired client secret refuses every call across every conversation
somebody opens: one card, with the count of runs and refused calls on it,
rather than forty. The story quotes the refusal, names the tool type and the
**names** of the environment variables its connection reads — never a value —
and the provider's own error code when there is one.

---

## 8. One board per project, and the project has an identity

Cards live in a SQLite file called `kanban.sqlite`, keyed by
`project_id + thread_id`. `project_id` is a key in your committed config —
`openstategraph.yaml`, `.yml`, `.json` or the `[tool.openstategraph]` table of
your `pyproject.toml`, all four of which can hold it
(`team-board-and-gap-reports/01`) — minted the first time the project is
initialised, or written into an older config the first time a board needs it.

**Where that file is depends on how OpenStateGraph is installed, so ask
rather than assume:**

```
openstategraph kanban where
```

It prints the address, the reason for it, and whether there is a board there
yet — and it answers on a project that has never filed a card, which is the
moment you need it. Three sources decide the address, in this order:
`OPENSTATEGRAPH_STATE_DIR` if you set it; `workflows/.openstategraph/` when
the command is run from an OpenStateGraph source checkout; otherwise this
machine's per-user state directory (`~/Library/Application Support/`,
`$XDG_STATE_HOME`, `%LOCALAPPDATA%`), in a folder keyed to your workflows
root. This document used to state the second of those three as if it were the
whole rule, which sent a reader looking in the one place their board was not
(`osg-agent-experience/65`).

**By default the board is machine-local state, and that is a decision rather
than an oversight.** It is not committed, a clone does not carry it, and a
colleague cannot see it — unless the team of you have pointed
`OPENSTATEGRAPH_KANBAN_URL` at one shared database, which §9 below describes
and which changes only *where* the cards are. So **a card is not a record**: it
is a working queue for the agents driving this checkout. Anything that has to survive the machine —
a decision, a defect, an argument — belongs in a commit, a ticket or a
document, and the card is the thing that points at it.

It is committed on purpose — a bare path moves and a bare name is not unique —
and that creates the obvious hazard: copy the file into a second folder to
bootstrap a new project and two projects now share one identity, silently. So
a **companion marker** is written beside it, under the gitignored
`.openstategraph/` directory, at the moment the id is minted. An ordinary
clone or `cp -r` carries the id and not the companion, and the mismatch is
reported as its own state rather than guessed at in either direction: *we
minted it*, *we found ours*, and *we found someone else's* are three different
sentences and the caller prints the right one.

A project made before that field existed is told so, and pointed at the
upgrade, rather than having an identity invented for it.

---

## 9. Team board — one board, several laptops

Everything above describes the board as machine-local, and that is still the
default and always will be. Set one variable and it is not:

```bash
export OPENSTATEGRAPH_KANBAN_URL="postgresql://user:password@host:5432/board"
```

Unset, cards live in `kanban.sqlite` exactly as §8 describes. Set, they live in
that database, and everyone who sets the same URL is looking at the same board.
Set but unreachable is neither: it **raises when the board is opened**, naming
the variable. A board that quietly fell back to a local file when the shared
one was asked for would be two people disagreeing about what the board says,
discovered a week later.

**The editor is the one exception, and it is not a quiet one**
(`team-board-and-gap-reports/18`). A server asks once, at startup: if the
shared board opens, every door reads it and nothing else happens. If it does
not, the sentence is recorded rather than raised — `GET /api/health` carries it
as `team_board_error`, the OSG Engineering tab prints it in place of the cards
it cannot show, one line goes to the log, and the process serves the **local**
board so that the editor's own Workflows tab and the live stream keep working.
Before that, a missing driver arrived as a two-hundred-line traceback on every
SSE reconnect and a 500 for the tab, while `/api/health` still said `ok`. The
answer is taken once, so **restart** after fixing whatever it named.


It is a **different variable from `OPENSTATEGRAPH_POSTGRES_URL`**, which is the
checkpointer's and means "put this deployment's durable run state here". One
setting meaning both would put your cards in somebody's checkpoint database the
first time they configured durability.

`pip install 'openstategraph[postgres]'` — the same extra the checkpointer
uses, and the variable set without it is a refusal that says so rather than a
board that is quietly empty.

**Name every extra you already have, in one line.** `uv tool install --force`
**replaces** the tool environment with exactly what the command names, so
repairing one extra drops the rest — which is how a team-board install lost
`[server]` and stopped starting at all (`osg-agent-experience/79`). On an
editor that uses the team board that line is six extras, not one:

```bash
uv tool install --force 'openstategraph[mcp,mssql,ollama,postgres,server,sqlite]==0.3.0rc18'
```

The version is named in full for the reason the front page gives: the shipped
version is a pre-release, and `uv` excludes those from an unpinned requirement,
so the same line without `==` resolves nothing and reads like a missing
package. It names no index, and did not need to even before `0.3.0rc18` put
this distribution on PyPI — which is exactly why this line was quietly wrong
until then, and why the sentence that follows is the real instruction.

The product composes the same line for your installation, with your extras and
your version already in it, and prints it in the refusal — so the reliable move
is to paste what it printed rather than to retype this one.

**Which rows are yours.** The shared table carries a `project_hash` column: a
SHA-256 of your project id, never the id itself. Every read and every write
this store makes is scoped to it, so two projects sharing one database do not
see each other's cards. `board` — the column that already separates the
editor's three tabs — separates them there too.

**The schema is SQL you can read.** It ships as numbered files in the package
(`openstategraph/kanban_migrations/`), applied in filename order when the store
opens and recorded so they are applied once. They are ordinary Postgres: a
maintainer with a migration CLI pushes the same directory, and a stranger with
their own database runs the same files by hand. Every file is written to be
safe to apply twice, which is what lets those two paths coexist.

Two appliers means two ledgers, and the store reads both: a file the CLI
already pushed is one the store leaves alone, because the question a runner
asks is what the *database* is at rather than what it happens to have written
down itself (`team-board-and-gap-reports/13`). Each file goes to the server
whole, through libpq's simple query protocol — the one that takes a script
rather than a single command, which is what a `.sql` file is.

**Row level security is on and forced**, with policies keyed on
`project_hash`. Read that precisely, because the honest version is narrower
than the reassuring one: the URL above is normally an owner-level role, and an
owner-level role on a managed Postgres has `bypassrls` — forcing RLS closes the
table-owner exemption, not that one. So the policies are the floor for every
*other* reader, and the store's own `where project_hash = …` is what scopes
your own reads. A reader arriving with a narrower role declares which project
it is (`app.project_hash` on its connection) and sees that project and nothing
else; a reader that declares nothing sees nothing.

**Nobody gets `delete`.** Not through a policy, not through a grant, and there
is no delete on the store's interface at all. Retention on a shared board is a
job that runs as the owner, not something a card-filing door can do by
accident.

**How the shared store is tested, and how you run that yourself.** Every rule
the board has — stage order, the evidence gate, the atomic claim, an answer
written once, the digest moving on a write and standing still on a read — is
one parametrised suite, `backend/tests/test_kanban_store_contract.py`, run
against every implementation there is. Two of them need nothing: SQLite, and
an in-memory store that exists only so the rules are proven against more than
one concrete on an ordinary run. The third needs a database, so it is gated on
a variable of its own:

```bash
OPENSTATEGRAPH_KANBAN_TEST_URL="postgresql://user:password@host:5432/scratch" \
  python3 -m pytest backend/tests/test_kanban_store_contract.py -q
```

Unset — which is how CI runs, and how it will stay — the Postgres cases skip
with a message naming that variable. Set, they run, and a failure is a
failure. **It is deliberately not `OPENSTATEGRAPH_KANBAN_URL`**: that one
points at your real board, and a suite that filed and staged cards against
whatever you had exported would be writing on the board it is meant to be
independent of. Point it at a scratch database. The suite scopes each case to
a fresh random `project_hash` and deletes nothing, for the reason in the
paragraph above.

---

## Where to go next

- [On the canvas](on-the-canvas.md) — what you are drawing, and the vocabulary
- [The `openstategraph` command](cli.md) — `patrol run`, and the `kanban`
  lifecycle a coding agent drives from a shell
- [The MCP layer](mcp.md) §5a — the same lifecycle for a model, and which name
  lands on the card
