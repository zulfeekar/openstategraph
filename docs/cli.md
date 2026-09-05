# The `openstategraph` command

Every command on the CLI, what it does, and when you would reach for it.

This page is the **only** enumeration of the CLI's commands, flags and exit
codes — `docs/README.md` says so, and
`backend/tests/test_documented_cli_surface.py` holds it to that: it walks the
real `argparse` parser and fails when a command or a flag exists here and does
not appear below, or appears below and does not exist. Everything on this page
was run before it was written down; where a command could not be exercised
without a credential or a dataset, the line says so.

Two rules shape what you find here, and they are worth knowing before you go
looking for something that is deliberately absent:

- **No new logic.** Every command wraps a seam the library already has —
  `load_workflow`, `ValidateWorkflowTool`, `scaffold`, `PackageKnowledge`,
  `api.main:app`, `mcp_server.main`. There is nothing the CLI can do that a
  Python caller cannot.
- **`argparse` only**, no `click` and no `rich`. A project arguing for a
  four-dependency core cannot then spend two more on colour and a decorator
  syntax.

Every command takes its paths from its arguments and works from any directory.
A bare slug (`openstategraph validate starter`) resolves against the project's
workflows root; an explicit path, relative or absolute, is resolved against
the directory you are standing in.

## Which one do I want?

| I want to… | Command |
| --- | --- |
| make a directory I already have into a project | [`init`](#init) |
| start a new package from a scaffold | [`new`](#new) |
| start from a worked example instead | [`examples`](#examples) |
| find out what node types exist, and what each one's fields are | [`nodes`](#nodes) |
| check a package compiles, before anything costs money | [`validate`](#validate) |
| see the topology the compiler actually built | [`graph`](#graph) |
| ask a package a question | [`run`](#run) |
| answer an approval a run is waiting on | [`resume`](#resume) |
| score a package against a dataset whose answers I know | [`eval`](#eval) |
| find out why a model call failed | [`providers`](#providers) |
| write the variable names I need into my own `.env` | [`env-example`](#env-example) |
| read back what a past run *said* | [`threads`](#threads) |
| read back what my runs *cost* | [`runs`](#runs) |
| build or read a package's second brain | [`knowledge`](#knowledge) |
| open the editor on the project I am standing in | [`open`](#open) |
| open the editor, the chat and the API on one port | [`serve`](#serve) |
| let my own LLM compose workflows | [`mcp`](#mcp) |
| hand the package to a different client | [`export plugin`](#export-plugin) |

## Making things

### `init`

```
openstategraph init [directory] [--workflows-dir NAME] [--empty] [--force] [--adopt]
```

Makes a directory an OpenStateGraph project: an `openstategraph.yaml`, a
`.gitignore`, an `AGENTS.md`, the four agent config files below, a workflows
folder and a starter package. Defaults to the current directory. **This is the
one command that creates a project**, and the only thing an install line cannot
carry.

The `AGENTS.md` is the brief a coding agent reads — the lexicon, the compiler
position, the rules that decide whether what it writes is right, and where the
rest of these pages are. It exists because `docs/` and the architecture
principles are repository files: someone who ran `pip install openstategraph`
has the worked examples and none of the rules, so their agent can copy the
*shape* of a package and cannot learn how one is built. A wheel cannot deliver
that at install time — the format is an unpack with no hook to run, which is a
property worth keeping — so the distribution carries the brief and this command
places it.

It goes between `<!-- OPENSTATEGRAPH:START -->` and `<!-- OPENSTATEGRAPH:END -->`
in a file that is otherwise yours. Inside the markers is generated and is
replaced whole on the next run; outside them is never read or moved, so your
own house rules can live in the same file. Re-run `openstategraph init . --force`
after an upgrade to take a newer brief. The bytes placed are the bytes in the
distribution, never a second rendering.

**And it installs the skills your coding agent reads.** Three directories into
each of `.claude/skills/` and `.agents/skills/`: the entry sheet for building a
workflow with this product — the routing check, the interview, the sizing call,
the board and the test-first loop, with its long form in `references/` beside
it — plus one for authoring a well-formed ticket and one for the run patrol.
The rules page under `references/` is written at install time from the file the
wheel carries, so it is the same text `get_engineering_rules` serves over MCP.
[The OpenStateGraph skill](the-openstategraph-skill.md) is what a reader wants
here; this page is what a typist wants.

It is written for a directory that is already yours. A directory with files in
it is not refused — it is reported (*"already has N files in it — this looks
like an existing project"*) and added to. Nothing it did not write is ever
overwritten: run it twice and the second run prints `(already there — left
alone)` beside each line.

**It also points your coding agent at this project's MCP server.** Four agents
read four different files for a project-local stdio server, so `init` writes
all four from one descriptor rather than asking you to paste the same command
line into each:

| File | Agent | Key |
| --- | --- | --- |
| `.mcp.json` | Claude Code | `mcpServers` |
| `.vscode/mcp.json` | VS Code, GitHub Copilot | `servers` |
| `.cursor/mcp.json` | Cursor | `mcpServers` |
| `.codex/config.toml` | OpenAI Codex CLI | `[mcp_servers.openstategraph]` |

An existing file is **merged into**, never replaced: your other servers and any
keys we do not know about are written back exactly as they were. The one case
that writes nothing is an `openstategraph` entry that is already there and
differs from ours — that is a deliberate customisation of yours, typically
`OPENSTATEGRAPH_MCP_ALLOW_RUNS=1`, and a silent overwrite would disarm it. So
would replacing a file that will not parse. Both are reported as `kept`, with
the reason. [`mcp.md`](mcp.md) §1 covers what the entry contains and how to
enable runs.

| Flag | Effect |
| --- | --- |
| `--workflows-dir NAME` | name the packages folder something other than `workflows`, and record it in the config |
| `--empty` | config and `.gitignore` only, no starter package |
| `--force` | waive the *"directory is not empty"* refusal and **nothing else** — it still overwrites no file it did not write, and still refuses to share a workflows root that was already there |
| `--adopt` | take over a `workflows/` that already exists and is not ours, as this project's root |

**A `workflows/` that is already there is reviewed, not assumed.** Without
`--adopt`, `init` stops and prints what is in that directory — every package
by slug, its name and its node count, and any that will not parse and why —
followed by the three ways out: adopt it, name a different root, or move
theirs aside. Seeing the list is the point: sharing a root nobody told you
about is the defect this refusal was written for, and a review answers it
without making the wrong choice for you.

`--adopt` is the second consent, and it is a different one from `--force`:
`--force` says the *project directory* may have things in it, `--adopt` says
the *workflows root* is already full of packages and they are yours to read.
It writes the config pointing at that root, prints the same review as a report
of what the project now reads, and writes **no starter** into it — a starter is
a teaching aid for an empty root, and in somebody else's it is litter under a
slug they may already be using. This is the shape a service in adoption is in:
it already ships workflows, and it wants the canvas over them.

The generated `openstategraph.yaml` is commented, and one of its keys is worth
knowing about before you need it: `prepend_sys_path:`, which is what makes a
package's `tools/*.py` able to `import` the project it lives in. The reasoning
is [`decisions/importing-the-projects-own-code.md`](decisions/importing-the-projects-own-code.md).

### `new`

```
openstategraph new <slug> [name] [--template NAME] [--root DIR]
openstategraph new --list-templates
```

Scaffolds a package from one of the templates in the wheel. `--list-templates`
prints them with a line each on what they are for. An unknown name exits **2**
and lists the valid ones. `--root` writes somewhere other than the project's
workflows root. `--team` is a deprecated alias for `--template team`; it works
and prints a note saying so.

Reach for this when you know the shape you want. If you do not, copy an
example instead — a scaffold is a skeleton, an example is a workflow that
already answers something.

### `examples`

```
openstategraph examples list
openstategraph examples copy <slug> [--root DIR]
openstategraph examples copy --all [--root DIR]
```

`list` prints the worked examples that ship inside the wheel, in reading order
— slug, the pattern each demonstrates, and a one-line purpose. `copy` takes
one into your workflows root **with every package it mounts**.

The copy is **severed**: it is yours, and upgrading the framework never
touches it. An unknown slug exits **2** and lists the real ones. A slug you
already have exits **1** and writes nothing — except a *mounted dependency*
that is already there byte-identical to the shipped copy, which is left alone
and named `already yours, unchanged — kept` rather than refused. An
actually-edited dependency still exits **1**.

`--all` takes the whole gallery, all-or-nothing, and prints the total size and
the largest single file before it writes a byte.

A copied example arrives as a **draft** (`published: false`), so the `/chat`
picker skips it until you publish it. The command says so.

## Checking things

### `nodes`

```
openstategraph nodes [<type>]
```

**Read this before you write a `data` block.** With no argument it lists every
node type this installation has, with its label and the line the editor's
palette shows. With a type it prints that type's fields — key, kind, whether it
is required, a picker's accepted values, and the hint the inspector shows — and
its ports, each with its direction, its port type and how many links it takes
(`unlimited` is a bus, such as an agent's `tools`). A type whose out-ports are
generated from its config, like a router's `branch:<name>`, says so.

No model is called and no provider extra is needed: this is the same
vocabulary the MCP tool `get_node_vocabulary` publishes, rendered for a
terminal, and it is generated from the node catalogue rather than written
down — so a node type added in the editor appears here without anybody
editing this page.

Exit **2** on a type id nothing resolves, with the nearest real ids named. The
question it exists to stop being guessed at is the one
[`validate`](#validate)'s *unknown field* finding reports after the fact:
`route.classifier` takes `branches`, `rules`, `fallback` and `matchMode`, and
never a `systemPrompt`.

### `validate`

```
openstategraph validate <package | workflow.json>
```

The compiler's plan and findings — **no model is called and no provider extra
is needed**, which is what makes this the gate to put in CI. Exit **1** on
blocking findings.

It answers three questions a plan held in memory cannot:

- does every mount name a package that is actually there, **and** stop short
  of mounting its own package again;
- does every bound tool have an implementation *in this installation* —
  built-in, an installed distribution, or the package's own `tools/`;
- what did the compiler notice while it actually built the graph.

A document copied without its package's `tools/`, and a package whose mount
chain closes on itself, fail here rather than at the first run.

#### The document against what its own node types declare

A plan is built *from* a node's `data` and never asks whether those are the
values that node reads. So a whole workflow of confident nonsense used to
print `VALID` — a router configured through a key it does not have, sixteen
agents whose prompt was a JSON object, a *Database file* holding the word
`mssql`. Six more findings close that, all of them read off the same node
catalogue the editor generates, none of them costing a model call:

| Finding | What it means |
| --- | --- |
| **unknown field** | a key under `data` that no field on that node type declares, so nothing reads it |
| **wrong kind** | a container where a scalar goes — an object in a paragraph field, a list where a number belongs |
| **not an option** | a value outside a picker's own list, so the node silently falls back to its default |
| **missing file** | a field that names a file — `tool.sql-query`'s *Database file* — pointing at nothing inside the workflows root |
| **no branches** | a classifier with edges leaving it and no branches configured: it has nothing to choose between |
| **unknown port** | an edge on a port the node's type does not declare, in or out |

Two are deliberately narrow, because a check that refuses a working document
is a check people learn to skip. A **picker whose list depends on what is
installed** — the model field, the package field — publishes no list, and a
value it cannot check is never refused. A **combobox** is not checked against
its suggestions at all: typing what does not exist yet is what that control is
for.

Every one of them is reported by `validate_workflow` over MCP and by the
editor's own validate as well, from the same list.

When a `tools/` module is present but will not import, the report names **the
module the interpreter could not find** and the two ways to fix it — an
editable install of the project, or `prepend_sys_path:`. It does not tell you
to move a folder that is already in place.

Findings appear under `PROBLEMS FOUND:` and move the exit code. Anything under
`Notes:` does not: a note cannot fail your CI, so it is kept out of the list
that can.

### `graph`

```
openstategraph graph <package> [--model MODEL] [--xray | --no-xray]
```

The compiled topology as Mermaid **text**, on stdout. Never a network call —
`draw_mermaid_png()` would post your graph to a third-party API and is not
used anywhere in this project.

`--xray` (the default) opens every mounted package to any depth, as nested
`subgraph` blocks. `--no-xray` draws what LangGraph itself holds — one box per
mount — which is the honest picture when a mount is the thing you suspect.

Unlike `validate` it *builds* the graph, so a package with an agent needs a
provider extra installed; without one it exits **3** and names the `pip
install` line. `--model` picks which model the build resolves, though nothing
is invoked.

### `eval`

```
openstategraph eval <package> [--dataset FILE] [--limit N] [--model MODEL]
                              [--threshold X] [--repeat N] [--json]
```

Grades the package against the golden dataset in its `evals/` folder. **This
one runs a model**, and is the only command on this page that does so without
being asked a question.

| Flag | Effect |
| --- | --- |
| `--dataset FILE` | use one dataset instead of the folder. A path that is not there exits **1** and says so |
| `--limit N` | stop after N cases |
| `--model MODEL` | grade with a model other than the package's own |
| `--repeat N` | ask each case N times and report whether the answers agreed. Each repetition is its own thread, so it is the question asked again rather than a follow-up. Reported, never gated |
| `--threshold X` | exit **1** below a score you are willing to defend. Default 0 — report, do not gate |
| `--json` | the scorecard as JSON |

The metric, and why it is not string comparison, is in
[Evaluation](evaluation.md). *(The flags above were exercised against a
missing dataset, which is the path that needs no credential; a scored run
needs a provider key.)*

## Running things

### `run`

```
openstategraph run <package> "<question>" [--model MODEL] [--thread-id ID]
        [--session-id ID] [--trace-file FILE] [--knowledge-dir DIR]
        [--context k=v] [--json]
```

Ask a package a question. This is the whole first five minutes: you do not
have to write a Python file to find out whether a package works.

| Flag | Effect |
| --- | --- |
| `--model MODEL` | override the model for this run |
| `--thread-id ID` | continue a conversation instead of starting one |
| `--session-id ID` | the sitting this run belongs to. A thread is one conversation; a session groups several. Pass `card:<task-id>` while working a patrol-board card, so the next patrol skips this run instead of filing a card about it (`kanban-patrol/08`) |
| `--trace-file FILE` | write the run's trace as it happens |
| `--knowledge-dir DIR` | read the second brain from somewhere other than the package |
| `--context k=v` | supply one declared run-context value; repeatable. It is `key=value`, and JSON is refused with **2**. A key the workflow does not declare is refused with **1** and a sentence naming the workflow |
| `--json` | the whole `RunResult` rather than the answer text |

**A paused run exits 1.** A run stopped at a `human.approval` gate has not
failed and has not answered — it is waiting — so it prints the pause, the
thread id and the exact `resume` line that finishes it, and does not claim
success.

### `resume`

```
openstategraph resume <package> <thread-id> (--approve | --reject)
        [--feedback "…"] [--model MODEL] [--trace-file FILE]
        [--knowledge-dir DIR] [--json]
```

Answer the approval a run is paused on and let the rest of it happen. **The
decision is required** — there is no default and nothing infers one.
`--feedback` is a note on a rejection; passing it with `--approve` is refused
with **2** rather than silently dropped.

A thread that is not stored, is not paused, or belongs to another package is
refused with **1** and a sentence. Otherwise the flags are `run`'s. It
**executes**, so it announces the thread, the gate and the decision on stderr
before it acts.

## Looking back

### `threads`

```
openstategraph threads list [--workflow SLUG] [--user EMAIL] [--session ID]
                            [--limit N] [--workflows-root DIR] [--json]
openstategraph threads show <thread-id> [--workflow SLUG]
                            [--workflows-root DIR] [--json]
```

What the checkpointer stored — what a run **said**. `list` is newest first and
stays scannable: a paused thread is noted in a footer rather than expanded
inline. `show` replays one thread checkpoint by checkpoint and prints
`(a recording, not a re-run — no model or tool was called to show this)`,
because it is a profiler and not an execution.

A paused thread's `show` also prints the gate's message, the candidate, and
the exact `resume` line that finishes it.

### `runs`

```
openstategraph runs list [--workflow SLUG] [--thread ID] [--session ID]
                         [--limit N] [--workflows-root DIR] [--json]
openstategraph runs export [--to FILE] [--limit N] [--workflows-root DIR]
openstategraph runs path [--workflows-root DIR]
```

What this machine has run — what a run **cost**. One row per turn, newest
first, **whichever door ran it**: the library (`ask`/`resume`, and so this CLI
and a package's own `tests/`), the two HTTP run endpoints, and the MCP
`run_workflow` tool all write the same row.

Three kinds of row that are not failures and are not successes either:

| `kind` | What happened |
| --- | --- |
| `stopped` | a reader pressed Stop or closed the tab. The model call already issued was still paid for |
| `exhausted` | the turn spent its **whole step budget** and reached no answer. No node failed — the ceiling stopped a graph that was running perfectly well — which makes it the most expensive row in the table |
| `failed` | a node failed |

It reads a local sqlite file written with no configuration at all. `runs path`
prints where, so you can point `sqlite3` at it and write your own query; it
prints `memory` when the store has been opted out.

`runs export` writes the same rows as a JSON array, to stdout or to a file,
**with the cadence** — every burst of streamed output a run produced, each
chunk carrying its own measured offset, so a replay shows what the answer
actually looked like arriving. Run it **before** truncating a store that has
grown large; nothing here ever deletes a run. It refuses rather than
under-delivers: if the cadence cannot be read it writes no file and exits
non-zero, because a file missing how its answers arrived is not a copy of the
store and must not be truncated against.

`threads` and `runs` are complements, not alternatives: one holds what was
said, the other what it cost and what executed.

### `kanban`

```
openstategraph kanban file --kind {task,bug,grilling} --title TEXT --story TEXT
                           --done-when TEXT --priority {high,med,low} --reason TEXT
                           [--area {ui,ux,frontend,backend,test,docs}]
                           [--blocked-by ID ...] [--agent-model NAME]
                           [--agent-effort LEVEL] --actor NAME [--workflows-root DIR]
openstategraph kanban attend <task-id> --actor NAME [--workflows-root DIR]
openstategraph kanban stage <task-id> {red,green,finished} --actor NAME
                            [--test-id ID] [--reason TEXT] [--commit SHA]
                            [--workflows-root DIR]
openstategraph kanban answer <task-id> --actor NAME --answer TEXT
                            [--workflows-root DIR]
openstategraph kanban show <task-id> [--workflows-root DIR]
openstategraph kanban release <task-id> [--threshold-seconds N] [--workflows-root DIR]
openstategraph kanban triage [--board NAME] [--workflows-root DIR]
```

These seven verbs are the whole of the loop a coding agent runs against the
board — file, triage, attend, show, stage, answer, release. [The OpenStateGraph
skill](the-openstategraph-skill.md) is the order it runs them in and why.

The CLI door onto one card of the patrol board (`kanban-patrol/19`), beside
the MCP one (`kanban-patrol/16`) — for a coding agent that can shell out but
is not attached to this project's MCP server. Both doors call the identical
`kanban_store.set_stage`, never two implementations of the claim logic.

`file` is the one verb here that **creates** a card rather than moving one
already on the board (`osg-agent-experience/25`). The patrol files what it
found in the run store, and a reader can go and look at the thread behind the
card; a card filed out of a conversation has no such thread, so the brief is
required rather than defaulted. `--story` (the plain-English want),
`--done-when` (the check that settles it) and `--reason` (why it is that
urgent) are refused blank, because an empty string is exactly the shape the
lost conversation would take on the card.

The id is a slug of the title — `<project_id>:idea-<slug>` — so two ideas
given one title are a refusal rather than a silent merge, and `--blocked-by`
(repeatable) can name a card by an id its filer can predict. `--agent-model`
and `--agent-effort` are advisory: what to give a subagent that takes the
card, left empty when nobody had an opinion rather than filled with a default
that would read as somebody's decision. A `grilling` lands in Needs You, a
`task` or `bug` in Detected, by the same derived rule as everything else on
this board. The `project_id` comes from the project's own committed config,
adopted if it predates the field and never invented per-call
(`kanban-patrol/23`) — the same resolution `patrol run` uses.

`attend` is the exclusive, atomic claim: the first caller wins, a second
caller on an already-attended card exits non-zero and is told exactly who has
it, never a silent overwrite. It also prints the **session marker** for the
card it just claimed — `card:<task-id>` — because from that moment the actor
produces runs, and an unmarked run is read back by the next patrol as fresh
evidence (`kanban-patrol/08`). Hand it to `run`'s session flag above, or as
`run_workflow`'s `session_id` over MCP. `stage` advances one step at a time — skipping
a stage or moving backward exits non-zero with the reason, rather than being
recorded. `show` prints the card's instruction, the same self-contained text
the board's own "Copy instruction" button copies, for pasting into a coding
agent that has no CLI or MCP access at all.

Each stage is also a sentence on the board (`kanban-patrol/19`), so a reader
sees how far a card has got rather than only that somebody has it — the copy
is owned once, in `src/view/board/cardStage.ts`:

| stage | what the card says |
| --- | --- |
| `attended` | Queued |
| `red` | In progress — test written |
| `green` | In progress — test passing |
| `finished` | Awaiting review |

`finished` reads "Awaiting review" rather than Resolved because it is a
claim: `17`'s evidence gate is the only thing that moves a card into the
Resolved column.

`kanban-patrol/17`+`21`+`33`: `stage` is evidence-gated, not trust-gated.
Moving to `red` requires `--test-id` and `--reason` both non-empty; moving to
`green` requires `--test-id` and it must *match* the one recorded at `red`;
moving to `finished` requires red and green already durably on the card and
`--test-id` is optional there — the recorded id is the evidence — but if one
is given it is refused, with the row unchanged, when it disagrees with the
one already recorded. A caller missing any of this exits non-zero with the
gap named plainly, the same way a skipped stage already does.

`answer` records the decision on a **Needs You** card (`kanban-patrol/15`,
decided 2026-09-04). A card is in Needs You because the patrol stopped on a
judgement it should not make, and only a person may make it. Recording the
answer sends the card back to **Detected**, carrying the decision — so the
next `attend` picks it up with the judgement already made, and `show` prints
the decision at the top of the instruction. It never reaches Resolved this
way: `17`'s evidence gate is still the only road there.

An answer is **written once**. A blank or whitespace answer is refused, so is
a card that was never in question (a `bug` is in Detected because nothing was
being asked) or one somebody is already working, and a second answer exits
non-zero naming who made the first — never a silent overwrite of somebody
else's decision.

`release` is the human's explicit press on a card the system has already
flagged stale (past `--threshold-seconds`, default 3600 — one hour, no
separate ping tool, every `stage` write is the heartbeat). It refuses,
non-zero, for any card not currently flagged — an active claim, one nobody
has attended, or one already `finished`, is never releasable by accident. A
`finished` card is **never** stale (`kanban-patrol/32`): nobody writes to a
resolved card again, so its heartbeat is old by design, and staleness is
about an abandoned claim rather than a discharged one. A successful release
resets the row to a fresh, unattended state: stage, actor, heartbeat, and
all four evidence fields, so the next attend starts clean.

`triage` answers "what first," not "what is here" — read-only, `--board`
defaulting to `workflows` (`osg-agent-experience/25` slice 4). It excludes
`finished` cards, and a `--blocked-by` naming one is spent, the same rule
`release` already applies to staleness. The order: an unblocked card other
cards are waiting on, most dependents first; then an unblocked card nobody is
waiting on, by priority (`high`, `med`, `low`); then every still-blocked
card, last, in that same sub-order. Each line is `rank`, `task_id` and
title, followed by `why_here` — the one sentence naming which rule placed it
there, the same function (`kanban_store.triage`) the MCP `kanban_triage` tool
answers from, so the two doors can never argue about the order. A board with
nothing to triage prints `nothing to triage` rather than silence.

### `patrol`

```
openstategraph patrol run [--workflows-root DIR]
```

The in-built patrol (`kanban-patrol/07`'s missing prerequisite): reads every
recorded finding (`REDUNDANT_TOOL_CALL`, `UNSTABLE_TOOL_RESULT`,
`NODE_FAILURE`), classifies each one deterministically — no model, `05`'s
richer classifier is a separate open question — and files whatever card
does not already exist. A card whose stage has already left `unattended` is
never touched again on a later run, even if the same finding reappears.

Needs the running project's own `project_id` (in its committed
`openstategraph.yaml`). A project made **before that field existed** is
adopted rather than refused (`kanban-patrol/23`): the id is minted, appended
as the last line of `openstategraph.yaml` under a one-line comment saying
who wrote it and why, paired with the gitignored companion marker, and
printed — `project_id: <uuid>  (minted and written to this project's
config …)`. Nothing above that line is parsed or rewritten; a column-0 key
at end of file is a valid top-level key whatever precedes it, so comments and
order survive untouched. The same adoption happens on `openstategraph .` /
`serve` (printed before the server binds) and on the board's first patrol
request (logged). A config that already carries the key is never touched, and
a carrier where an appended YAML key would mean nothing — a `pyproject.toml`
`[tool.openstategraph]` table, a JSON config — is refused by name with the
line to add by hand.

## Knowing what is configured

### `providers`

```
openstategraph providers [--check]
```

Which model providers are registered, whether each has a credential, its
default model, **which** of the variables it reads actually supplied one, and
the extra it needs. It also prints which config file is in force and whether
a `.env` was found. **The first thing to run when a model call fails.**

Plain `providers` **calls nobody**. `configured` on a row means a credential
is present in this environment — never that the endpoint is reachable — and
the command says so under the list. It is a status command, so it exits **0**
whenever it could report, including on a machine where nothing is configured.

`--check` makes **one real, billable request per configured provider** and
reports which answered. Opt-in because it costs money: a status command must
not spend your budget to render a word. It exits **1** if any configured
provider fails to answer, and **1** when there is nothing to check at all.

### `env-example`

```
openstategraph env-example
```

Prints the provider block of a `.env.example` — **names only, never values** —
generated from the provider registry, to redirect into your own `.env`. Its
first line says how to regenerate it, because a hand-edited copy is one that
goes stale the next time a provider is added.

## Serving things

### `open`

```
openstategraph open [directory] [--host HOST] [--port N] [--no-open] [--create] [--no-input]
openstategraph .
```

One verb, pointed at a folder. Reviews the project, picks a free port, prints
the URL and opens your browser on it. The second form is the same command —
a first argument that is not a known verb and *is* a directory is read as
`open <directory>`, so `openstategraph .` and `openstategraph ~/svc` both
work.

**It says which directory it chose and why**, which is the point of it. The
workflows root is resolved by the ordinary chain — `OPENSTATEGRAPH_WORKFLOWS_ROOT`,
then `workflows_dir:` in your config file, then a checkout, then `./workflows`
— and the report names the winner:

```
project      /Users/me/svc
workflows    /Users/me/svc/workflows
             workflows_dir: in /Users/me/svc/openstategraph.yaml

  half-built    will not parse — workflow.json is unreadable: Expecting property name …
  their-flow    Lens QA — 7 nodes
```

The directory argument decides **where the command stands**, not a new place
in that chain. So a committed `workflows_dir:` still wins over the folder you
named, and when the root it resolved is not inside that folder the report says
so on its own line — which is the failure this verb exists to end: standing in
the wrong place and silently editing another project's workflows.

**It creates nothing without being asked.** `init` is the scaffolding verb; a
verb that quietly scaffolds is a verb you stop trusting to be read-only. When
the workflows directory is missing it offers, in a terminal, to create that
one empty folder, and names [`init`](#init) for everything else. When there is
no terminal — CI, a pipe — it refuses instead, exit **2**, naming `--create`
as the consent flag, because a prompt in CI is a hang. `--no-input` forces
that non-interactive behaviour in a terminal.

A directory that is itself a workflow package (it holds a `workflow.json`) is
refused rather than opened: a project root inside a package would nest
`workflows/` inside it. The refusal names the project directory it thinks you
meant, and does not go there on its own.

`--port` and `--host` behave exactly as they do for [`serve`](#serve), which
is what actually serves: omit `--port` for 8000 or the next free port.
`--no-open` suppresses the browser, which is the flag to reach for in a
script. Needs the server extra.

### `serve`

```
openstategraph serve [--host HOST] [--port N] [--open] [--workers N]
```

The whole product on one origin: editor at `/`, chat at `/chat`, API under
`/api`. The URLs it landed on are printed.

| Form | Port |
| --- | --- |
| no `--port` | 8000, or the **next free port** if 8000 is busy |
| `--port N` | exactly N, or a clear failure if it is taken |
| `--port 0` | the OS picks |

`--host` defaults to `127.0.0.1` — **this machine only**, deliberately not
`0.0.0.0`: this process holds your provider keys and has no authentication, so
publishing it to the network publishes those. `--open` also launches a
browser, and is off by default. Needs the server extra; that extra is the web
layer and carries **no** model integration, so an install without a provider
extra serves an editor that cannot run anything — and says so before it binds.
A source checkout with no built editor serves a *"run the build"* page at `/`
and a fully working API and `/chat`.

Before it binds it prints what Run will actually do — the default model, the
workflows root and what chose it, and **whether a `.env` was read**
(`.env: read, N variables`, or `no .env`; the count, never the names). The
installed command reads the `.env` that sits beside your `openstategraph.yaml`
— the same directories the config file is looked for in, nearest first,
stopping at the git root — into its own environment before anything else runs.
A variable your shell already exports always wins, so
`OLLAMA_API_KEY=… openstategraph serve` overrides the file and a container's
injected secret beats a stale one. A line that is not `KEY=value` is skipped with a warning
naming **the line number only**.

**`--workers` exists only to be refused by name.** It must be 1. `--workers 4`
exits **1** and prints the two reasons — the sqlite checkpointer and store
serialise writes with a per-instance lock that two OS processes do not share,
and the catalogue event fan-out behind the events endpoint is an in-process
queue — rather than silently serving several processes that cannot see each
other's drafts, approvals or events. See [Deploying](deploying.md).

### `mcp`

```
openstategraph mcp [--transport stdio | streamable-http]
```

Runs the MCP server, so your own LLM can compose and inspect workflows.
Defaults to `stdio`, which is what an MCP client launches. Needs the MCP
extra. An unknown transport exits **2**. What the server exposes is
[The MCP layer](mcp.md).

### `export plugin`

```
openstategraph export plugin <package> [--out DIR]
```

Writes the package out as an [Agent Plugins](decisions/agent-plugins.md) v1
bundle — the same thing the plugin-export endpoint previews, actually written
to disk. Defaults to `./<the package's folder name>`; a destination that
already holds files exits **1** and writes nothing.

Everything no portable v1 component type can carry travels under a namespaced
directory, and **every lossy edge is printed as a `note:` on stderr** — what
was carried non-portably, what was excluded, and what was deliberately not
emitted rather than fabricated. Needs no extra and calls no model.

## Knowledge

### `knowledge`

```
openstategraph knowledge list <package> [--knowledge-dir DIR]
openstategraph knowledge build <package> [--source NAME] [--instruction "…"]
                                         [--model MODEL]
```

The package's second brain. `list` prints the topics, their one-line hints,
and each doc's owner and stale badge. `--knowledge-dir` looks elsewhere, which
**drops the badges** — a store outside the package has no source to recompute
against — and a directory that is not there exits **1**.

`build` generates them and prints `written / skipped / collisions / warnings`.
`--source` runs one builder instead of all of them; an unknown name exits
**1** and lists the real ones. `--instruction` steers the agentic builder and
`--model` picks its model. What to build and how to tell a stale doc from a
wrong one is [Testing a second brain](second-brain.md).

## Exit codes

Fixed and few, because they are what CI consumes.

| | |
| --- | --- |
| **0** | success |
| **1** | the run failed, or validation found blocking findings |
| **2** | usage error — bad arguments, unknown command (argparse's own code) |
| **3** | a required extra is not installed; the message names the exact `pip install` line |

There is no fourth code, and adding one is a breaking change under
[the stability contract](stability.md) — the command line follows the Tier 1
deprecation policy even though the Python module does not.

Two cases are worth stating on their own because they are the ones a script
gets wrong:

- **A paused run exits 1.** It has not failed and has not answered. Reporting
  it as success is what let a human-in-the-loop package look finished when
  nobody had decided anything.
- **`providers --check` exits 1 when there is nothing to check**, unlike plain
  `providers`, which exits 0 on a machine where nothing is configured. One is
  a status command and the other is an assertion.
