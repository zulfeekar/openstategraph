# Using OpenStateGraph in your project

On a fine day a developer decides to use this in their project. What do they
actually do?

There are three ways in, and they are genuinely different — different install,
different upgrade story, different thing living in your repository. Pick one
deliberately; mixing them is where confusion starts.

| | (a) Fork / checkout | (b) Artifact | (c) MCP |
| --- | --- | --- | --- |
| You run | the whole stack | nothing of ours in prod | an MCP server process |
| Your workflow lives in | `workflows/<slug>/` **in your fork** | your own repo | your own repo |
| Who authors the graph | you, on the canvas | you, once, anywhere | your own LLM client |
| Upgrading | `git merge upstream` | bump the runtime you vendored | restart the server |
| Maturity | mature | **a built wheel + a CLI; the PyPI upload is pending** | works, no auth layer |

> **One honest framing before any of them.** OpenStateGraph is a *compiler*,
> not a runtime. Whatever route you take, the thing you end up owning is a
> plain LangGraph `StateGraph` and a folder of ordinary files. The editor is an
> authoring tool, not a dependency of what you author.
> [What this is](what-is-this.md) is the longer version, including what we
> deliberately do not own and when not to use us at all.

**The checkout is no longer the only path.** It was, before 0.3.0, and much of
this page was written then. Today the backend is a distribution: one wheel, a
four-dependency core, a set of named extras, `py.typed`, and an `openstategraph`
console script — verified by a CI job that installs it into an empty virtualenv
outside the checkout and runs a workflow there. Mode (b) is a first-class path;
what is still outstanding is the **PyPI** upload, and this page says exactly
where. (`0.3.0rc1` is tagged, built and on **TestPyPI**; the publish step is a
GitHub environment gate a maintainer approves, not a command anyone types.)

---

## The shortest path — one install, one command, the whole product

**The wheel carries the canvas.** It did not until now: we called this a
*visual* workflow builder and shipped 215 KB of Python with no UI, so the
canvas existed only for people who cloned the repository or ran Docker. The
built editor now ships as package data.

```bash
pip install "openstategraph[server,ollama]"
openstategraph init my_demo && cd my_demo
openstategraph serve --open
```

> **That first line does not work yet.** `openstategraph` is not on PyPI —
> `0.3.0rc1` reached TestPyPI and the publish gate has not been approved. Until
> it is, build and install the same artifact from a checkout; the recipe is in
> [Be honest about the install](#be-honest-about-the-install) below, and the
> other two lines are unchanged. This line is written as the shape it takes
> rather than deleted, because it is the shape, and hiding it would leave the
> page with no headline at all.

That is one process serving the whole product from **one origin**:

| Path | What it is |
| --- | --- |
| `/` | the editor — the canvas, the inspector, the run panel |
| `/chat` | the customer chat surface: no canvas, just a conversation |
| `/api/…` | the HTTP API both surfaces use |

The two surfaces are **one process over one workflows directory**, and
publishing is what connects them: you draft on the canvas, click Publish, and
the workflow becomes visible in `/chat`. A draft never appears there. (The
whole rule is in *The publish story*, below.)

### The project directory and the workflows root are two different nouns

`openstategraph init my_demo` makes **the project directory** — yours, named by
you, and the only command that creates one. Nothing creates a project
implicitly: `serve` in an unconfigured directory tells you what to run rather
than scattering a `workflows/` folder somewhere you did not choose.

Inside it is **the workflows root**, `workflows/`, which holds
`<slug>/workflow.json` packages. That name is a convention nobody types
(`--workflows-dir flows` renames it and every surface follows, because every
surface asks the same resolver). The project is what you name; `workflows` is
plural because it holds many.

`init` writes three things and prints a fourth:

| | |
| --- | --- |
| `openstategraph.yaml` | commented, no secrets, `workflows_dir:` set. Found by walking **up** from wherever you run a command to the git root — so it still applies from inside `workflows/starter/`. `pyproject.toml [tool.openstategraph]` carries the same keys if you would rather not add a file; a project with both gets the dedicated file. |
| `.gitignore` | `.env` first, because the next thing you make is a `.env`. |
| `workflows/starter/` | the smallest workflow that runs, pinning no model. `--empty` skips it. |
| *(printed, never written)* | the `.env` variable names. A generator that emits a credential file is a generator whose output someone commits. |

If the directory already exists, `init` refuses and names both ways forward —
another name, or `--force`, which waives only the "not empty" precondition and
still overwrites nothing it did not write. The confirmation is a flag rather
than a prompt because exit codes are this CLI's API for CI, and a command that
blocks on stdin hangs a CI job.

**A `workflows/` that was already there is refused too, and `--force` does not
waive that one.** It cannot: a non-empty directory is already refused, and a
directory that does not exist cannot contain a `workflows/`, so `--force` is
the only way to reach the collision at all — a flag that both reaches a check
and waives it is a check that never runs. What waives it is the marker instead:
a target carrying an `openstategraph.yaml` is *ours*, and so is its workflows
root, which is why re-running `init --force` on a project you made stays
idempotent. A target with no config file is somebody else's, and the refusal
names an unused root to pass to `--workflows-dir` and the `mv` that frees the
name. The reason it matters is what happens next rather than what is
overwritten — nothing is overwritten — the store scans that root for packages,
so sharing it means reading directories OpenStateGraph did not write.

`OPENSTATEGRAPH_WORKFLOWS_ROOT` points the workflows root elsewhere, and beats
the file, for the reason it always did: the file is committed and shared, the
environment is the machine in front of you.

### Ports — what each form means

| You type | What happens |
| --- | --- |
| `openstategraph serve` | port 8000, or the **next free port** if 8000 is busy |
| `openstategraph serve --port 8080` | exactly 8080, or a clear failure if it is taken |
| `openstategraph serve --port 0` | the OS picks a free port |

In every case the last thing printed before the server's own log is the URLs it
actually ended up on — editor, chat and health — so `--port 0` is a usable mode
rather than a guessing game. The editor's API calls are same-origin relative,
so any port works; the absolute `http://localhost:8000` the bundle used to
carry is gone.

`--host` defaults to `127.0.0.1`, **this machine only**. Not `0.0.0.0`: this
process holds your provider API keys and has no authentication, so publishing
it to the network publishes those. `--open` launches a browser; it is off by
default.

### If you are in a source checkout

A clone has no built editor until you build one. `openstategraph serve` there
serves a page at `/` that says so and gives you the two ways out — `npm run
build`, or `./start dev` for the hot-reloading stack. It is never a bare 404,
because a 404 at `/` is indistinguishable from a broken install.

**That guarantee is `serve`'s, not every backend's.** The two-process dev
setup in README's "Terminal 2" — a bare `uvicorn openstategraph.api.main:app`,
which `scripts/dev.sh` also runs — deliberately does not mount the editor at
all: `OPENSTATEGRAPH_SERVE_STATIC` is unset there, Vite owns the editor on
:5273, and `GET /` on :8000 is a plain `{"detail":"Not Found"}`. That is the
expected shape of the dev backend, not a broken install.

---

## (a) Fork / checkout — the primary mode today

**The repository is the workspace.** There is no "install OpenStateGraph into
your app" step, because your workflows live inside the checkout, next to the
shipped example (`chinook-assistant` — one visible package; `concierge` and
`workflow-architect` ship hidden).

```bash
git clone <your-fork-of-openstategraph> openstategraph
cd openstategraph
npm install
./start dev
```

That gives you two processes, supervised by [`scripts/dev.sh`](../scripts/dev.sh):

- **editor** — the Vite SPA on <http://localhost:5273>
- **runtime** — `uvicorn --reload` on <http://localhost:8000>

Stop with `./start stop`; watch with `scripts/status.sh`. The canvas preview
defaults to `Mock · Offline` and answers with no credential at all. The backend
defaults to Ollama **cloud**, which needs `OLLAMA_API_KEY` in `.env` (or
`OLLAMA_HOST`, pointing at a daemon you run); `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` is preferred over it when set.

> This said "No API key is needed to get a first answer." That held only
> because Ollama's `ProviderSpec` declared `env_vars=()` and so was always
> treated as configured — an *ambient* credential (a local daemon signing with
> `~/.ollama/id_ed25519`), not the absence of one
> (providers-and-credentials ticket 02).

### Where your work goes

```bash
openstategraph new --list-templates           # what you can start from
openstategraph new my-thing                   # the default: minimal
openstategraph new my-qa --template routed-qa
openstategraph new my-team --template team
# in a checkout, without installing:
python3 scripts/new_workflow.py my-thing      # or scripts/new_team.py
```

That scaffolds `workflows/my-thing/`.

### Which template

They ship **inside the wheel**, so they are there on a machine that has never
seen this repository, and the editor's **New Workflow → Start from** picker
offers the same set from the same source. `openstategraph new --list-templates`
is the authoritative list; this table is the reading order.

| Template | Start here when | Cost of one run |
| --- | --- | --- |
| `minimal` *(default)* | you are finding out whether any of this works, or you know exactly what you are building and want an empty-ish canvas | one model call |
| `loop` | you want to see a revision loop and nothing else: an agent drafts, a grader reviews, weak answers go back | two, plus one per revision |
| `routed-qa` | you have more than one kind of request to handle, or you want the answer checked before it is returned. Router → agent → grader → output, plus a cheap branch that skips the grader | up to three, plus one per revision |
| `team` | the work splits into parallel subtasks with a supervisor over them, and you intend to **mount** it inside another workflow. The `Workflow` card runs it — "team" names a package *shape*, not a node type | several — a fan-out per subtask |

Every scaffolded package carries an `AGENTS.md` that names what was created and
the next step for that particular shape, plus a `tests/test_shape.py` — the
document loads, its node types are what got scaffolded, and it compiles clean
under the strict default. It asserts the document, not the template, so it
keeps working after you have edited the workflow past recognition; run it with
plain `pytest` from inside the package. `--team` still works as a deprecated
alias for `--template team`.

### Or start from a worked example

Twenty-three finished packages ship in the wheel as well — one per pattern the
canvas can express, each one validated and smoke-run, each with an `AGENTS.md`
recording what it actually answered.

```bash
openstategraph examples list                  # the gallery, simplest first
openstategraph examples copy evaluator-optimizer
openstategraph run workflows/evaluator-optimizer "Write a two-sentence release note."
```

A template is *rendered* into an empty-ish package for you to fill. An example
is **copied whole** — its tests, its knowledge store, its eval fixture, and for
`sql-qa` a 1 MB database — because it is the package that was really built and
run, and rewriting it would make its recorded results untrue.

Two consequences worth knowing before you rely on either:

- **They are not in your project until you copy one.** They live inside the
  installed package, so they never appear in `openstategraph run`'s reach, in
  the `/chat` picker, or to a workflow that asks the platform what exists.
  `sql-qa` will not even open its own database where it ships — the SQL tools
  jail every path inside your workflows root, which is exactly the point.
- **The copy is yours and stays yours.** It is severed on copy: a later
  `pip install -U openstategraph` never reaches back into it. That is also why
  an example is never *mounted* where it lies — a mount is a live reference, and
  a live reference into `site-packages` is a workflow that changes when you
  upgrade something else.

Several of them mount other examples, so a copy brings those too; the command
names them as it writes them. The editor's **Workflows → Examples** shelf is the
same catalogue, over `GET /api/examples`.

From then on you are editing files in **your** fork:

```
workflows/my-thing/
├── workflow.json      required — the graph, vendor-neutral JSON
├── AGENTS.md          required — what this workflow is, for humans and agents
├── tools/             discovered by convention: BaseTool subclasses
├── functions/         plain callables a function.* node names
├── middlewares/       LangChain middleware contributed by slot name
├── skills/            skill documents an agent's skill port can bind
├── knowledge/         the second brain: index tier + doc tier
├── tests/             pytest — these are real tests, not decoration
└── data/              fixtures, sample databases
```

Nothing here is a proprietary format. `workflow.json` is JSON, the rest is
Python and Markdown. That is the point: **your flow is a file in git**,
reviewable in a pull request and diffable.

### Production shape

```bash
./start          # build + run the Docker image, then http://localhost:8000/
./start logs
```

`./start` builds a multi-stage image — Node compiles the editor, a throwaway
stage builds the Python wheels, and the final layer is Python slim plus the
built `dist/`, `backend/` and `workflows/`. **One container serves the editor,
`/chat` and the API from a single origin on port 8000** — the same serving path
`openstategraph serve` uses, switched on by `OPENSTATEGRAPH_SERVE_STATIC=1`.
Map it to any host port: the editor's API calls are same-origin relative and
follow the page. `./workflows` is bind-mounted, so a workflow saved in the
container lands in the repo.

Approvals persist across restarts: the checkpointer defaults to
`<workflows root>/.openstategraph/checkpoints.sqlite`, which is inside the
bind-mounted `./workflows`, so it outlives the container. The startup log says
which one it got (`approvals persist at …` or `approvals are in-memory and
will NOT survive a restart`); `OPENSTATEGRAPH_CHECKPOINT_PATH` moves it, or
`=memory` opts out.

If your project already runs its own LangGraph checkpointer or store, we
**never go looking for it** — reuse is explicit, always: pass the object
(`load_workflow(…, checkpointer=…, store=…)`) or set the variable
(`OPENSTATEGRAPH_CHECKPOINT_PATH`, `OPENSTATEGRAPH_MEMORY_PATH`,
`OPENSTATEGRAPH_POSTGRES_URL`). When you do neither, we create our own,
announce where it lives, and touch nothing of yours. The reasoning is
recorded in `docs/decisions/memory-architecture.md`.

One worker, and a second one is **refused at startup** rather than warned
about: `SqliteSaver` and `SqliteStore` are single-process by their own
documentation (a per-instance `threading.Lock`, which two processes do not
share), and the live catalogue-event fan-out is an in-process queue. Postgres
is available (`pip install 'openstategraph[postgres]'`,
`OPENSTATEGRAPH_POSTGRES_URL`) and moves durable state into a database your
operations team backs up — it does not raise the ceiling, because the event
half has no cross-process transport yet. Deploying for other people —
authentication, the committed reverse-proxy configs, the threat model — is
[docs/deploying.md](deploying.md).

### Upgrading — the honest part

You forked, so upgrading is a merge:

```bash
git remote add upstream <the-upstream-repo>
git fetch upstream
git merge upstream/main
```

The friction is real and worth stating before you commit to this mode:

- **Your workflows sit in a tracked directory of the upstream tree.** They are
  *your* files with *their* siblings (`chinook-assistant`, `concierge`,
  `workflow-architect`) around them. Adding files rarely
  conflicts; deleting the shipped examples to tidy up guarantees a conflict on
  every upgrade. Leave them, or delete them once in a commit you are willing to
  re-resolve.
- **Any edit you make to `src/`, `backend/` or `scripts/` is a merge you own
  forever.** If you can express the change as a *registration* — a node type, a
  tool, a provider, a validation rule — do that instead; the extension points
  are registries precisely so that a new capability never edits the engine. See
  [Building an atom](building-an-atom.md).
- **`workflow.json` is versioned with a migration chain**, so documents carry
  forward. Package conventions (`tools/`, `knowledge/`) are discovered rather
  than declared, so new conventions arrive additively.
- **There is no `openstategraph upgrade` command.** Merging is the mechanism.

If that friction is the dealbreaker, you want mode (b).

---

## (b) Artifact — you never run the editor in production

Author once, commit the package to **your own** repository, and run the
compiled graph from your own service. The editor's involvement ends at
authoring time.

What you commit is exactly the package layout above — most importantly
`workflow.json`.

### The fastest path: the command line

You do not have to write a Python file to find out whether a package works.

```bash
openstategraph run ./workflows/chinook-assistant "How many invoices are there?"
```

That is the whole first five minutes. The rest of the commands each wrap a
seam the library already has — there is no behaviour in the CLI that
`load_workflow` does not have:

| Command | What it does |
| --- | --- |
| `openstategraph run <package> "<question>"` | ask it. `--model`, `--thread-id`, `--trace-file`, `--knowledge-dir`, and `--json` for the whole result rather than the answer. A run that stopped at a `human.approval` gate **exits 1** and prints the pause, the thread id and the `resume` line that finishes it — it is not a finished run and no longer says it is |
| `openstategraph resume <package> <thread-id> --approve\|--reject [--feedback "…"]` | answer the approval a run is paused on and let the rest of it happen. The decision is **required** — there is no default and nothing infers one — and `--feedback` is a note on a rejection, refused with **2** on an approval rather than silently dropped. A thread that is not stored, is not paused, or belongs to another package is refused with **1** and a sentence. Same flags as `run` otherwise; **it executes**, so it announces the thread, the gate and the decision on stderr before it acts |
| `openstategraph validate <package\|workflow.json>` | the compiler's plan and findings, plus the two questions a plan held in memory cannot answer: does every mount name a package that is there **and stop short of mounting its own package again**, and does every bound tool have an implementation **in this installation** (built-in, an installed plugin, or the package's own `tools/`). **Exit 1** on blocking findings, so it is a CI gate. A document copied without its package's `tools/`, and a package whose mount chain closes on itself, fail here rather than at the first run |
| `openstategraph graph <package>` | the compiled topology as Mermaid **text**, on stdout. Never a network call — but it *builds* the graph, so a package with an agent needs a provider extra installed (exit 3 otherwise). `validate` needs no provider |
| `openstategraph new <slug> [name] [--template NAME]` | scaffold a package into `./workflows` (`--root` to change that) from one of the templates in the wheel — `minimal` (default), `loop`, `routed-qa`, `team`. An unknown name exits **2** and lists the valid ones; `--team` is a deprecated alias for `--template team` |
| `openstategraph new --list-templates` | the templates and one line on what each is for |
| `openstategraph examples list` | the worked examples in the wheel, in reading order: slug, the pattern it demonstrates, and its one-line purpose |
| `openstategraph examples copy <slug>` | copy one into `./workflows` (`--root` to change that), **with every package it mounts**. The copy is severed — an upgrade never touches it. An unknown slug exits **2** and lists the real ones; `<slug>` itself already existing always exits **1** and nothing is written, but a *mounted dependency* that already exists byte-identical to the shipped copy is left alone and named "already yours, unchanged — kept" rather than refused — an actually-edited dependency still exits **1**, same as before. `--all` takes the whole gallery instead of one slug, all-or-nothing, printing the size before the first byte |
| `openstategraph eval <package>` | grade the package against the golden dataset in its `evals/` folder — this one **runs a model**. `--dataset`, `--limit N`, `--model`, `--json` for the scorecard, and `--threshold 0.8` to exit **1** below a number you are willing to defend (default 0, i.e. report but do not gate). The metric is in [Evaluation](evaluation.md) |
| `openstategraph export plugin <package> [--out DIR]` | write the package out as an [Agent Plugins](decisions/agent-plugins.md) v1 bundle — the same thing `GET /api/workflows/<slug>/plugin-export` previews, actually written down. Defaults to `./<the package's folder name>`; a destination that already holds files exits **1** and writes nothing. What no portable v1 component type can carry travels under `org.openstategraph/`, and every lossy edge is printed as a `note:` on stderr. Needs no extra and calls no model |
| `openstategraph threads list\|show` | past runs the checkpointer stored, newest first; `show` replays one checkpoint by checkpoint without re-running it. A `paused` thread's `show` also prints the gate's message, the candidate, and the exact `resume` line that finishes it — `list` only notes in a footer that something is waiting, so the table stays scannable |
| `openstategraph providers` | which model providers are registered, whether each is configured, its default model, the environment variable it reads and the extra it needs. The first thing to run when a model call fails |
| `openstategraph env-example` | print the provider block of `.env.example` — names only, never values — to redirect into your own `.env` |
| `openstategraph knowledge list <package>` | the second brain's topics, their one-line hints, and each doc's owner and stale badge (`--knowledge-dir` to look elsewhere, which drops the badges — a store outside the package has no source to recompute) |
| `openstategraph knowledge build <package>` | generate them; prints `written / skipped / collisions / warnings`. `--source` runs one builder, `--instruction` steers the agentic one, `--model` picks the model |
| `openstategraph init [directory]` | make a directory an OpenStateGraph project — `openstategraph.yaml`, a `workflows/` folder and a starter package. Defaults to the current directory; `--workflows-dir` renames the packages folder, `--empty` skips the starter, `--force` waives the "directory is not empty" refusal and nothing else — it overwrites no file it did not write, and does not waive the refusal to share a pre-existing workflows root. The one command that creates a project, and the only thing the install line cannot carry |
| `openstategraph serve [--host --port --open --workers]` | the whole product on one origin: editor at `/`, chat at `/chat`, API under `/api`. No `--port` takes 8000 or the next free port; `--port N` means exactly N; `--port 0` lets the OS choose; the URLs it landed on are printed. Needs `openstategraph[server,ollama]` — `[server]` is the web layer and carries **no** model integration, so an install without a provider extra serves an editor that cannot run anything, and says so before it binds. `--workers` exists only to be **refused** by name: it must be 1, and `--workers 4` exits with the reason rather than silently serving four processes that cannot see each other's drafts, approvals or catalogue events — see [Deploying](deploying.md) |
| `openstategraph mcp [--transport stdio\|streamable-http]` | the MCP transport. Needs `openstategraph[mcp]` |

Exit codes are fixed, because they are what CI consumes: **0** success, **1**
run or validation failure, **2** usage error, **3** a required extra is missing
(the message names the exact `pip install` line). Every command takes its paths
from its arguments, so it works from any directory.

A **paused run** is the one thing that exits **1** on its own, without the
second half: a run stopped at a `human.approval` gate has not failed and has
not answered — it is waiting — and reporting it as success is what let a
human-in-the-loop package look finished when nobody had decided anything.

A **failed run** is one rule, in one place (`cli.run_exit_code`): the run
produced no answer *and* something went wrong — a step failed, or a capability
did not resolve. Both halves, deliberately. A workflow that answered despite a
missing optional tool degraded rather than failed, and a workflow that legally
answers with nothing did not fail either. *"Something went wrong"* means
`RunResult.failures`, **not** `.warnings`: a run's warnings also carry reports
about how the answer was reached — a node that produced nothing, a grader that
ran out of attempts, a `revise` verdict with no edge — and those are printed
on stderr without ever changing the exit code. `validate` fails on any finding,
which since production-ready 53 includes a **mount naming a package that is not
in the workflows root** — checked recursively, so a typo two packages down is
caught before the run is.

> **Until the wheel is on PyPI** (see *Be honest about the install*, below),
> `openstategraph` lands on your `PATH` when you `pip install -e
> "/path/to/openstategraph/backend[ollama]"`. Without installing at all, every
> command is also `PYTHONPATH=/path/to/backend python3 -m openstategraph.cli
> …`.

### In your own service

Loading and running a package is one function call, and the argument is the
**package folder**, not the JSON file:

```python
from openstategraph import load_workflow

workflow = load_workflow("workflows/my-thing")

if workflow.warnings:                 # capabilities that could not be resolved
    print("degraded:", workflow.warnings)

answer = workflow.ask("How many invoices are there?")
print(answer)                         # it IS the answer string
print(answer.decisions)               # ...and which branch each router took
```

`load_workflow` returns a small value object:

| | |
| --- | --- |
| `.graph` | the compiled LangGraph `StateGraph` — **the escape hatch** |
| `.warnings` | everything the compiler noticed: capabilities it could not resolve, and reports about the document — an agent whose authored rules still deny the tools wired to it, a grader with no `revise` edge. **Findings from inside a mount are here too**, behind `Inside mounted workflow "<package>":` — and behind the whole chain of packages (`outer/inner`) when the mount is nested. A package mounted three times contributes its sentence once, because a finding recorded by a package's compile is a property of the package rather than of the mount |
| `.failure_warnings` | the half of `.warnings` that is a claim the graph came out **less capable**, and the only half `ask()` puts on `RunResult.failures` — so the only half that can reach an exit code. A stale prompt sentence and an unwired `revise` are on `.warnings` and not here: both describe how the document is *drawn*, and the run does everything it was drawn to do. An unloadable mount is on both. A finding absorbed from a mount keeps the classification it was recorded with, so a report inside a child stays a report here |
| `.ask(question, *, thread_id=None, user_email=None, session_id=None, recursion_limit=None)` | run it once, get a `RunResult`. **`user_email` is who the run is for** — omit it and per-person memory does not bind (see [`deploying.md` §1b](deploying.md)); over HTTP a client may not send it, but here you are the server. `workflow_slug` needs no argument: it comes from the package |
| `.as_tool(name=…, description=…)` | this workflow as one LangChain tool (see below) |
| `.mermaid()` | the compiled topology as text, no network call |
| `.slug` / `.package_dir` / `.document` | what it loaded, and from where |

### More than one workflow: the catalogue

A path per call is right for one package and wrong for a directory of them —
the root ends up restated at every call site, and there is no way to ask what
is in there without compiling it. `Workflows` is the catalogue:

```python
from openstategraph import Workflows

catalog = Workflows("./workflows", model="anthropic:claude-sonnet-4-5")

for row in catalog.published():          # what a customer chat would show
    print(row.slug, row.name, row.node_count, row.edge_count)

billing = catalog.load("billing")        # compiles THIS one
print(billing.ask("How much did we invoice in March?"))
```

Four members, and that is the whole class:

| | |
| --- | --- |
| `.root` | the directory it reads. Absolute, and fixed for the object's life |
| `.list()` | every non-hidden package: `slug`, `name`, `published`, `node_count`, `edge_count`, `saved_at`, `error` |
| `.published()` | only the published, readable ones — mirrors the HTTP listing's `?surface=chat` |
| `.load(slug, **overrides)` | the same `CompiledWorkflow` `load_workflow` returns, from the same function |

**A fresh package is a draft**, so the loop above is empty until something is
published — this is the first thing anyone hits after `openstategraph examples
copy chained-summarizer`, since every shipped example carries `published:
false` and the copy is faithful. Publishing is a decision about *your*
deployment (the editor's Workflows panel, or `"published": true` in
`workflow.json`), never something a copy does on your behalf. Use `.list()`
while you are still building — it shows drafts, and the `published` column says
which is which.

**Listing never compiles.** `.list()` reads one `workflow.json` per package and
stops: no LangGraph import, no model, no API key, and none of the package's own
`tools/*.py` executed. Twenty workflows list instantly, and **one broken
package does not break the list** — it comes back as a row with `error` set,
rather than as a silent omission or an exception. (The HTTP listing still omits
it: a customer surface must not show rubble. A developer asking "what have I
got" wants the opposite.)

Every keyword `load_workflow` takes can be set once on the catalogue and
overridden per call — `model`, `checkpointer`, `store`, `knowledge_dir`,
`trace_file`, and the `tools`/`functions`/`middleware` mappings, which **merge**
rather than replace so a catalogue-wide stub survives a per-call substitution.
`load_workflow(path)` is unchanged and stays the right call for one package.

### Where it reads, and where it writes

Two questions, deliberately not one answer. **Read** is the workflows root,
resolved through five layers — later wins:

| | |
| --- | --- |
| convention | `./workflows` under the process's working directory |
| **the checkout** | `<repo>/workflows`, when `workflows_root.py` is genuinely inside an OpenStateGraph source tree (both `workflows/` and `backend/` present beside it) |
| config file | `workflows_dir:` in `openstategraph.yaml`, resolved **relative to that file**, never to the cwd |
| environment | `OPENSTATEGRAPH_WORKFLOWS_ROOT` |
| argument | `Workflows(root)` — or the package path you hand `load_workflow` |

**The checkout rung is the one that used to be missing here, and it is the one
that decides the answer most often.** Inside this repository it always matches,
so the cwd convention below it is never reached — which is why running a
command from a subdirectory of the checkout still finds the repository's own
`workflows/`, and why an adopter's `./workflows` behaves differently from a
contributor's. Installed from a wheel it never matches, and the convention is
the floor.

There is no `set_workflows_root()`, on purpose: process-wide mutable state is
how two callers in one process come to disagree about which directory they read
with nothing in either call to explain it.

**Write** is the state dir, and it is never assumed to be the read location:

| | |
| --- | --- |
| `OPENSTATEGRAPH_STATE_DIR` | names it outright — a container mounting a writable volume |
| inside a checkout | `<workflows root>/.openstategraph`, where a developer expects it |
| installed | your platform's per-user state directory — `$XDG_STATE_HOME` (default `~/.local/state`), `~/Library/Application Support`, or `%LOCALAPPDATA%` — keyed per project so two projects never share a thread namespace |

`OPENSTATEGRAPH_CHECKPOINT_PATH` still outranks all of it for the checkpoint
file itself, including `=memory` to opt out of durability deliberately.

The consequence worth having: **pointing this at a directory does not put
anything in it.** A workflows root on a read-only mount lists, compiles and
runs; if a write genuinely cannot be made, durability degrades with a warning
that says so rather than the process failing.

### What `.ask()` gives you back

A `RunResult`, which **is** a string — it subclasses `str`, so `.strip()`,
`+`, `json.dumps`, `re.search` and `isinstance(x, str)` all behave exactly as
they did when this returned a bare `str`. Attached to it is what you need when
the answer is wrong and used to require dropping to `.graph.invoke()` with
hand-seeded state:

| | |
| --- | --- |
| `.answer` | the text — identical to the object itself |
| `.decisions` | node id → the branch that router or grader chose |
| `.outputs` | node id → that node's own output |
| `.warnings` | everything worth knowing about this run: the workflow's unresolved capabilities, the steps that broke, and how the answer was reached — a node that produced nothing, a grader that ran out of attempts, a `revise` verdict with no edge |
| `.failures` | the half of `.warnings` that is a claim the run **failed**. This is the one to gate a script on; `openstategraph run`'s exit code reads it |
| `.failed_nodes` | node id → why that step failed, for the nodes whose `.outputs` entry is a failure marker rather than content |
| `.attempts` | how many times a model-driven node was invoked during the run — a cost, not a lap count and not a budget. A cycle holding two agents spends two per lap, and two loops in series both add into it. Each grader's own budget is `maxAttempts`, counted per grader |
| `.usage` | model name → the tokens that model reported (`input_tokens`, `output_tokens`, `total_tokens`, and whatever detail block the provider added, including cache reads). Counted in-process by `langchain-core`'s own usage callback — **no tracer, no account**. **Per model, never one integer**: a run that drives a cloud model and one paid Claude call is only readable while the two are apart. An **empty** mapping means no provider reported, which is *unknown*, not free |
| `.pause` | the gate this run stopped at — `{"message", "candidate"}` — or **`None`** for a run that finished. A pause is not a failure and not a warning: nothing went wrong, the run is *waiting*, and the answer is `workflow.resume(thread_id, decision=…)` rather than a retry |
| `.total_tokens` | every model's `total_tokens` added up, or **`None`** when nothing reported. `None`, never `0` — a run nobody metered did not cost nothing. There is deliberately no dollar figure: tokens are a fact, money is a claim about a vendor's price sheet, and no price table lives in this project. Multiply by your own |

**The split is the point, and it is why `.warnings` is not what a script
should test.** A node that produced nothing is a report about *how* the answer
was reached, not a claim the run failed — a workflow may legally answer with
nothing. `if result.warnings:` is the reader's question ("is there anything I
should look at?"); `if result.failures:` is the script's ("did this break?").

**`.outputs` can hold a sentinel, and `.failed_nodes` is how you tell.** A
step that failed publishes `'[summarise1 failed after retries: …]'` into its
own output slot — deliberately, so the nodes downstream of it still read
*something* — which means a caller reading `.outputs` alone sees a string that
looks like an answer. `.failed_nodes` names exactly those nodes, with the
reason:

```python
result = workflow.ask("Explain what a compiler is.")
for node, reason in result.failed_nodes.items():
    print(f"{node} did not run: {reason}")
```

> At 1.0 this becomes a plain dataclass with `.answer`. Build on the seven
> attributes above, not on the string methods it also happens to have.

### Calling a workflow from an agent you already have

If your team is already on `create_agent`, you do not have to restructure:

```python
billing = load_workflow("workflows/billing").as_tool(
    name="billing_analyst",
    description="Answers questions about invoices and revenue.",
)
agent = create_agent(model, tools=[billing, other_tools...])
```

`as_tool()` returns a LangChain `StructuredTool` with one string argument, the
question. **Be clear about what it is:** the workflow runs as its own graph. It
sees the question and nothing else — not your agent's message history, not its
state, not its tools — and returns its answer as the tool result. That is the
same isolation any subagent has, and it is a feature: the workflow's behaviour
does not change because of who called it. If it needs to know something, put it
in the question.

There is deliberately **no middleware equivalent**. Middleware would have to
decide *when* to consult the workflow, which is a routing policy — and a router
is something this framework already expresses as a document. A second, worse
one inside the library would be duplicated knowledge.

### It is an SDK: what you can substitute

Convention is the default; configuration is the override. Every LangGraph or
LangChain collaborator the runtime uses is the caller's to supply, and the ones
that are not are listed too, with why — an SDK where half the dependencies are
injectable and the other half are built from environment variables inside a
constructor is worse than one that is honest about the line.

| Collaborator | Parameter | Default when omitted | When you'd override |
| --- | --- | --- | --- |
| Chat model | `model=` | the document's `settings.model`, else `default_model:` in `openstategraph.yaml`, else the installation default — the provider integration you installed, preferring one whose credential is set (`openstategraph providers` shows which and why). With the key missing you get a stand-in raising `MissingProviderKey` the first time a node uses it, `MissingProviderPackage` when the extra is absent, and `NoProviderInstalled` when no integration is installed at all | a pre-built model object with your own retry, base URL, temperature or gateway |
| Thread persistence | `checkpointer=` | durable: `<workflows root>/.openstategraph/checkpoints.sqlite` (the package's own `settings.checkpointer: "sqlite"` takes a per-workflow file instead; `OPENSTATEGRAPH_CHECKPOINT_PATH` moves the default, or `=memory` opts out) | a Postgres/Redis saver, so `human.approval` and `ask(thread_id=…)` survive a restart **and** reach more than one process |
| Long-term memory | `store=` | durable: `<workflows root>/.openstategraph/memory.sqlite`, beside the checkpointer's file (`OPENSTATEGRAPH_MEMORY_PATH` moves it, or `=memory` opts out; `OPENSTATEGRAPH_POSTGRES_URL` puts it in a database) | **the sibling of `checkpointer`.** Supply both or neither: durable threads plus an in-memory store is a deployment that forgets facts it told you it remembered |
| Tools | `tools=` | built-ins, then installed plugins, then the package's own `tools/` | a vendored or read-only package, a tool that needs a client you already built (a pooled DB handle, an authenticated API session), one tool stubbed in a test with the rest real |
| Functions | `functions=` | the package's own `functions/` | the same reasons, for `function.*` steps |
| Middleware | `middleware=` | the package's own `middlewares/`, one file per slot | your existing guardrail/redaction/tracing middleware, contributed by slot name without writing a file into the package |
| Knowledge directory | `knowledge_dir=` | the convention, `<package>/knowledge` | knowledge shared between two packages, living outside the repository, or a fixture directory in a test |
| Step budget | `ask(recursion_limit=…)` | the document's own `settings.recursionLimit`, else 50. **Supersteps, not iterations** — one lap of a loop that fans out costs several, so a number chosen as "max attempts" will be several times too small. A saved value outside 10–1000 is clamped rather than refused | a graph that legitimately needs more, and a package you would rather not edit |
| Run trace sink | `trace_file=` | none | you want one JSON line per `ask()` on disk |

#### `settings.memory` — what a package declares about its own memory

The `store=` row above is the *deployment's* answer to "where do memories
live". A package states separately which memory it actually uses, in its
`workflow.json`:

```json
"settings": {
  "memory": { "enabled": true, "scopes": ["user", "workflow"] }
}
```

| Option | Default | Means |
| --- | --- | --- |
| `enabled` | `true` | `false` binds no memory tools at all, even when a store exists |
| `scopes` | all three | `user` (follows the person), `workflow` (this package's own findings), `app` (shared across every workflow) |

The block is **additive** — a document without one behaves exactly as it did
before the block existed, so no existing package changes.

Every agent that binds memory gets three tools: `save_memory`, `search_memory`
and `forget_memory`. Search prints a short handle beside each fact
(`[workflow · a1b2c3d4]`) and forget takes that handle — a wrong fact is
removable, and because search shows only four results per scope, removing stale
ones is what keeps correct ones visible — those four are an arbitrary
window, not the four closest to the query, and every unranked answer says
so in its own last line (`organisms-first-class/26`).

**Retention is a deployment property, not a document one** — how long *this
installation* keeps data is not something a workflow author can answer for the
person running it:

```bash
OPENSTATEGRAPH_MEMORY_TTL_MINUTES=10080   # seven days; unset means never expire
```

It needs a durable store, which you have by default; it says so loudly if you
have opted out of one (`OPENSTATEGRAPH_MEMORY_PATH=memory`), because a store
that loses everything on restart has no retention question to answer. Expiry
deliberately does **not** refresh on read: a stale
fact that keeps surfacing in search results would otherwise become immortal
precisely because it keeps surfacing.

Two properties worth knowing, because they are the reason it is a declaration
rather than a runtime check:

- **Narrowing applies to the tool schema, not to the write.** A scope a package
  does not declare is one the model is never offered, rather than one it is
  offered and then refused. Being told about a capability and rejected for
  using it is the failure mode the scope enum exists to prevent.
- **A declaration this deployment cannot honour is reported, never silently
  dropped.** Declaring memory with no store configured lands a finding on the
  same `warnings` channel as an unresolved tool: *"settings.memory declares
  user … but no memory store is configured."* So does a misspelled scope or an
  unknown option — a typo that quietly does nothing is exactly what a typed
  block removes.

```python
app = load_workflow(
    "workflows/billing",
    model=my_model,
    checkpointer=PostgresSaver(pool),
    store=PostgresStore(pool),                       # the sibling, not an afterthought
    tools={"tool.billing-ledger": LedgerTool(session)},
    functions={"function.redact": redact},
)
```

**Precedence, and the reasoning: built-in < installed plugin < the package's
own files < these arguments.** An explicit mapping is the most specific source
there is. The filesystem describes what a package *shipped*; an argument
describes what *this process* is to run, and only the caller knows which is
right. The reverse order would make substitution impossible — a package you
vendored could veto your own application.

A caller-supplied capability that collides with a discovered one is therefore a
**deliberate substitution, not a duplicate**, and is never reported on
`.warnings`. That list means "this run lost a capability"; filling it with
things you asked for is how a list that matters gets ignored.

#### What stays internal, and why

| Not injectable | Why |
| --- | --- |
| The compiler (`WorkflowCompiler`) | it is not a collaborator, it **is** the product. A pluggable compiler is a second runtime, and [we are a single-target compiler on purpose](what-is-this.md) |
| The state schema and its reducers | `workflow.json` is the vendor-neutral contract, and the reducers are a named enum by design. A swappable schema would make a document's meaning depend on the host |
| The workflows root / `WorkflowStore` | **derived, not chosen**: a subgraph node names a sibling slug, so the root is `package_dir.parent` by definition. Deriving it is why this function takes one argument |
| Skills context | discovery produces *text*, not an object. Injecting it would be prompt authoring, and the prompt is composed — preamble, context, your rules, output contract — not handed over |
| `retry` / `timeout` / `cache` policies | per LangGraph these are `add_node` parameters, so they belong to the **workflow document** and compile to graph assembly. Putting them on the loader would be a second spelling of one feature |
| The trace sink | `trace_file` is a file sink on purpose. A pluggable tracer would be us inventing a span model to compete with LangSmith and OpenTelemetry, which already exist and which `.graph` reaches directly |
| Advisor mode | editor-only, per call, and it must never be reachable from `/chat` or MCP |

#### The three with nuance the table cannot hold

- **`model`** — a model string (`"anthropic:claude-haiku-4-5"`,
  `"ollama:gpt-oss:120b-cloud"`), resolved through the *same* path the HTTP API
  uses, or an already-built LangChain model object, passed through untouched.
  Omit it and you get the document's own `settings.model` if it names one,
  then `default_model:` in `openstategraph.yaml` if the project declares one,
  then **the installation default**: the provider integration you have installed.
  That last rule is what makes the install line the mental model — `pip
  install 'openstategraph[anthropic]'` and Anthropic is your default, with no
  configuration at all. Among installed integrations, one with a credential
  set wins; among several, the first registered; and an installed integration
  with no key yet still wins, so the one thing left to do names *your*
  vendor's variable. `openstategraph providers` prints which won and why.
  A node that names its own model still wins over all of it.

  A credential in your environment does **not** outrank `default_model:`: it
  is a fact about your machine, not a request about this project. It feeds the
  election, one rung below.

  A model reference may be written in full (`anthropic:claude-opus-4-1`) or as
  a bare provider (`anthropic`, `ollama:`), which resolves to that provider's
  own default.
  With no provider credential set at all, `build_chat_model` returns an
  `UnconfiguredProvider` that raises `MissingProviderKey` naming the exact
  variable — on first *use*, not at construction, so a workflow whose nodes
  never call a model still runs. (Until providers-and-credentials ticket 02
  Ollama needed nothing here; that was ambient daemon credentials, not a
  keyless provider.)
  A provider whose **integration package** is not installed takes the same
  path and raises `MissingProviderPackage`, whose message is the `pip install`
  line. Both gaps are checked together and reported in one sentence, so
  setting the key does not reveal the extra one run later.
- **`knowledge_dir`** — where the package's second brain is read from.
  Convention (`<package>/knowledge`) stays the default, because
  discovery-by-convention is why this function takes one argument. Override it
  when knowledge is shared between two packages, lives outside the repository,
  or is a fixture directory in a test. It names the directory holding the
  `<topic>.md` files, not the package above it.
- **`trace_file`** — appends one JSON line per `ask()`: question, slug,
  decisions, attempts, warnings, per-model token usage, duration, and the
  answer's **length**. The
  answer text itself is deliberately not written: a trace file gets committed,
  emailed and pasted into issues, and the answer is the one field of a run that
  reliably carries a customer's data — while `decisions` and `attempts` are
  what actually tell you which way the graph went. It is a file sink, not a
  tracing system; LangSmith and OpenTelemetry already exist. A path that cannot
  be written logs a warning and never fails the run.

### Why not just compile it yourself?

Because it works, and that is the problem. This shape —

```python
runtime = NodeRuntime(model=init_chat_model(...))          # DON'T
graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
```

— compiles, runs, and returns an answer. It also never wires the package's own
`tools/`, `functions/`, `middlewares/`, `skills/` or `knowledge/`, because
those are discovered from the package **directory**, which a bare document
knows nothing about. Run the Chinook example that way and
`runtime.unresolved_tools` holds all three of its tools while the agent
cheerfully replies *"we need to call chinook_list_tables"* — a workflow that
looks like it works and answers nothing. The symptom to watch for is an agent
answering from memory instead of failing.

`load_workflow` derives the workflows root and the slug from the folder you
hand it, wires the capability registries, injects the long-term memory store,
and surfaces anything it could not resolve on `.warnings` (plus one `WARNING`
log line) rather than raising. When you need more than one question and an
answer, drop to `.graph` — it is a plain compiled LangGraph object, so
`.stream()`, `.astream_events()`, `.get_state()` and interrupt/resume are all
right there.

`ask()` has a sibling for the one case that needs no drop at all:
`workflow.resume(thread_id, decision="approve" | "reject", feedback="…")`
continues a run a `human.approval` node paused, and returns the same
`RunResult`. `workflow.pause(thread_id)` asks what a thread is waiting for
without resuming it, and answers `None` for a run that finished. A thread the
checkpointer has never seen, one that is not paused, and one belonging to a
different package each raise `ThreadNotResumable`, which is catchable apart
from your own `ValueError`s.

**Streaming that into your own frontend is its own page.**
[Wiring a workflow into your app](wiring-it-in.md) has the worked
`.astream_events()` loop — what to seed, which event carries the finished
state, and what `ask()` was doing for you that the loop now has to do — plus
the four `configurable` identity keys in one table.

### What you actually install

The runtime dependencies are declared in
[`backend/pyproject.toml`](../backend/pyproject.toml). To run a compiled
workflow in-process you need:

| Package | Why |
| --- | --- |
| `langgraph>=1.0` | the graph the compiler targets |
| `langchain>=1.0`, `langchain-core>=1.0` | `create_agent`, messages, tools |
| `deepagents>=0.7` | only if a node uses the Deep Agents tier |
| `pydantic>=2.9` | tool argument schemas — the single source of truth |
| one provider package | `langchain-ollama`, `langchain-anthropic` or `langchain-openai` — whichever your `model` names |

**You do not need `fastapi` or `uvicorn` to run a workflow in-process.** They
are dependencies of the *editor's server*, not of the compiled graph, and the
`load_workflow` path imports neither — a pinned test asserts exactly that by
importing in a subprocess and checking `sys.modules`. `mcp` is likewise only
needed if you run the MCP transport.

### Be honest about the install

**The wheel is real; the PyPI upload has not happened yet.** From 0.3.0 the
backend is a proper distribution — `hatchling`, `LICENSE`, `py.typed`,
classifiers, a console script, a lean core and named extras — built, `twine
check`-clean, and proven by CI's `clean-install` job, which installs it into an
empty virtualenv **outside** the checkout and runs a workflow there.

**`0.3.0rc1` has already been through the train**: tagged on the remote, built,
uploaded to **TestPyPI**, and installed from that index into an empty
virtualenv outside any checkout by the `rehearsal` job. What is outstanding is
the **`pypi` job**, which waits on a required reviewer in a GitHub environment
— an approval, not a `twine upload` anybody types. See
[Releasing](releasing.md). So the command that will be the headline is written
here as the shape it takes, clearly flagged:

```bash
pip install "openstategraph[ollama]"     # ← after the first release
```

Until that release ships, install exactly the same artifact from a checkout:

```bash
# Build the wheel and install it anywhere — this is the artifact CI verifies.
# The filename carries whatever `backend/pyproject.toml` says the version is
# (0.3.0rc1 today), so glob it rather than typing it.
python3 -m build /path/to/openstategraph/backend
pip install "$(echo /path/to/openstategraph/backend/dist/openstategraph-*.whl)[ollama]"

# Or editable, from the checkout. The extras are the install story: the core is
# four packages and you add only what your workflow uses —
# [anthropic] [openai] [ollama] [deep] [sqlite] [server] [mcp] [postgres]
# [bastion], or [all] — which is everything except [bastion], held out
# because it is AGPL and that is not a licence to hand someone by default.
pip install -e "/path/to/openstategraph/backend[ollama]"

# Or nothing at all, if you would rather not install.
PYTHONPATH=/path/to/openstategraph/backend python your_service.py
```

Either way you get the console script and the same import package. Measured
from a real clean venv on 2026-08-10, and recorded in `backend/pyproject.toml`'s own dependency comment: **36 distributions** for the core, **38** with
`[ollama]` — down from 79 before 0.3.0 (the figure `backend/pyproject.toml` records; this page said 78). The Docker image is the third option;
it already contains the runtime, so a service that shells out to the container
needs nothing installed locally.

The distribution is named `openstategraph` (it was `openstategraph-backend`
before 0.3.0); the import package is `openstategraph` either way.

---

## (c) MCP — your own LLM composes the workflow

You do not open the canvas at all. You point an MCP client (Claude, Cursor, an
in-house agent) at the server, and your own model composes the document while
OpenStateGraph acts as ground truth and artifact factory.

```bash
python -m openstategraph.mcp_server                       # stdio
OPENSTATEGRAPH_MCP_TRANSPORT=streamable-http \
  python -m openstategraph.mcp_server                     # server deployment
OPENSTATEGRAPH_MCP_ALLOW_RUNS=0 ...                       # no model-touching tool
```

The artifacts land in **the client's own repository** — the server writes
nothing in the primary flow. The full worked example, including the client
config JSON and a document that genuinely validates, is
[The MCP layer](mcp.md). The decision record and its honest limits (no
authentication layer, chief among them) are
[`decisions/mcp-layer.md`](decisions/mcp-layer.md).

---

## What artifacts you own

Every one of these is a plain file. None of them is a blob in our database,
because there is no database.

| Artifact | Where | Format | Who writes it |
| --- | --- | --- | --- |
| `workflow.json` | `workflows/<slug>/` | versioned JSON, vendor-neutral | the editor, or your LLM via MCP |
| `AGENTS.md` | `workflows/<slug>/` | Markdown | you |
| `tools/*.py` | `workflows/<slug>/tools/` | Python `BaseTool` subclasses | you |
| `functions/*.py` | `workflows/<slug>/functions/` | plain callables | you |
| `middlewares/*.py` | `workflows/<slug>/middlewares/` | LangChain middleware, contributed by slot name | you |
| `skills/*` | `workflows/<slug>/skills/` | skill documents | you |
| `knowledge/*` | `workflows/<slug>/knowledge/` | Markdown, index tier + doc tier | generated, then owned by you |
| `tests/*.py` | `workflows/<slug>/tests/` | pytest | you |
| `data/*` | `workflows/<slug>/data/` | fixtures, SQLite, CSV | you |

Two properties worth naming, because they are what "you own it" means:

- **Diffable.** A change to a graph shows up in a pull request as a change to
  JSON, not as "someone edited the flow in the UI on Tuesday".
- **Runnable without us.** `tests/` runs under plain `pytest`; the compiled
  graph runs under plain Python. Delete this editor and the package still
  works.

### `knowledge/` — generated, then claimed

The second brain is the one artifact that starts machine-written, so it has an
explicit hand-over rather than a convention:

- **One per workflow.** A package has one `knowledge/` directory, so the canvas
  allows one Knowledge atom — the store's visible declaration and the build
  button's home. A workflow you *mount* is a different package with its own
  store, so a root and a mounted team each hold one and they never collide;
  the child seeks its own knowledge, never the parent's.
- **Build it** with `openstategraph knowledge build <package>`, or the
  Knowledge card's **Build second brain** button in the editor. Generated files
  carry a marker comment; `openstategraph knowledge list <package>` prints each
  topic with its one-line index hint.
- **Building is build time, never run time.** A run only ever *reads* these
  docs — no node compiles to a builder, nothing in a graph can reach one, and
  publishing does not rebuild as a side effect. The knowledge an answer relies
  on predates the question.
- **A root workflow's docs are pointers, not copies.** For each child it
  mounts, the root gets one coarse page — what that child answers, when not to
  route there, and a drill pointer when the child has a store of its own.
  Never the child's table-level detail. Children it does not mount are not its
  business and get no doc.
- **A project has no store of its own — it is a *source*.** There is no
  `workflows/knowledge/`; a project's second brain is the union of its
  packages' stores. A workflow that wires a platform tool
  (`tool.platform-list-workflows`, `tool.platform-describe-workflow`) can see
  the whole project, so the project counts as one of its sources and it gets a
  *catalogue* page per package those tools show — what each is for and when it
  is the wrong answer — minus the ones it mounts, which get the better routing
  page instead. A draft or hidden package gets no catalogue page, because the
  platform tools would refuse to describe it either.
- **Claim it by editing it.** The first save through the editor strips the
  generated marker, and a claimed doc is never regenerated over. There is no
  autosave — editing a topic is a dialog with an explicit Save, and the result
  lands in git as a diff.
- **Stale is a badge, not a rewrite.** Each generated marker records a hash of
  the brief the doc was written from. When the underlying source moves, the
  hash stops matching and the topic is badged stale — including topics you have
  claimed, because a claimed doc can go out of date too. Topics written by the
  agentic explorer have no recomputable brief and are never badged: unknown is
  not stale. `openstategraph knowledge list` prints both the owner and the
  stale badge, so this is checkable without opening the editor.

**Checking that a store is right** — coverage, index quality, stale versus
wrong, and whether the store earns its place at all — is
[Testing a second brain](second-brain.md).

---

## The publish story — draft in the editor, live in `/chat`

Authoring and serving are separated by one deliberate human action.

```
draft on the canvas  ──►  Save  ──►  workflow.json (published: false)
                                          │
                                     a human clicks Publish
                                          ▼
                            published: true  ──►  visible in /chat
```

- **Saving writes a draft.** `published` is `false` until someone flips it.
- **`/chat`** (`/chat` on whatever origin the server reported — 8000 by
  default) is the customer-facing surface: no canvas, just a conversation. It
  is the *same process* as the editor, reading the *same* workflows directory;
  publishing is the only thing that decides what appears there. A concierge workflow routes the question to
  whichever *published* workflow can answer it and streams the run back token
  by token. Drafts are invisible there.
- **Publishing is never automated.** It is not exposed over MCP, and MCP's
  `save_workflow_draft` refuses to overwrite an already-published workflow.
  That is the trust boundary: a machine may compose and propose; a human looks
  at the graph and decides it may talk to customers.
- `list_workflows(surface="chat")` is the same filter, read-only.

---

## Which mode should you pick?

- **Trying it, or building workflows as your product** → (a). It is the mode
  everything is tested against.
- **Workflows are a component of an existing Python service** → (b). Install
  the wheel (from the checkout until the PyPI upload lands — the artifact is
  the same one) and use `load_workflow`, the CLI, or `as_tool()` inside an
  agent you already have.
- **Your team already lives inside MCP clients and wants graphs generated from
  a chat** → (c), behind your own reverse proxy.

Next: [Getting started](getting-started.md) for the first run,
[Patterns](patterns.md) for what to build, [The MCP layer](mcp.md) for the
worked MCP example.
