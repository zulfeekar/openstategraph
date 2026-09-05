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

### Three tabs, and two of them say they are not built

The board has tabs — `Workflows`, `OSG Engineering` and `GitHub`. Only the
first has anything behind it. The other two say `Not configured` and
`Not available` in as many words instead of showing four empty columns,
because empty columns are a claim (*a patrol ran and found nothing*) rather
than a state.

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

## 8. One board per project, and the project has an identity

Cards live in `workflows/.openstategraph/kanban.sqlite`, keyed by
`project_id + thread_id`. `project_id` is a line in your committed
`openstategraph.yaml`, minted the first time the project is initialised.

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

## Where to go next

- [On the canvas](on-the-canvas.md) — what you are drawing, and the vocabulary
- [The `openstategraph` command](cli.md) — `patrol run`, and the `kanban`
  lifecycle a coding agent drives from a shell
- [The MCP layer](mcp.md) §5a — the same lifecycle for a model, and which name
  lands on the card
