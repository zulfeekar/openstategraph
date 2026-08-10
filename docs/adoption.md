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
four-package core, seven extras, `py.typed`, and an `openstategraph` console
script — verified by a CI job that installs it into an empty virtualenv outside
the checkout and runs a workflow there. Mode (b) is a first-class path; what is
still outstanding is one `twine upload`, and this page says exactly where.

---

## (a) Fork / checkout — the primary mode today

**The repository is the workspace.** There is no "install OpenStateGraph into
your app" step, because your workflows live inside the checkout, next to the
two shipped examples.

```bash
git clone <your-fork-of-openstategraph> openstategraph
cd openstategraph
npm install
./start dev
```

That gives you two processes, supervised by [`scripts/dev.sh`](../scripts/dev.sh):

- **editor** — the Vite SPA on <http://localhost:5273>
- **runtime** — `uvicorn --reload` on <http://localhost:8000>

Stop with `./start stop`; watch with `scripts/status.sh`. No API key is needed
to get a first answer — the backend defaults to Ollama **cloud** and the canvas
preview defaults to `Mock · Offline`.

### Where your work goes

```bash
openstategraph new my-thing                   # or: openstategraph new my-team --team
# in a checkout, without installing:
python3 scripts/new_workflow.py my-thing      # or scripts/new_team.py
```

That scaffolds `workflows/my-thing/`. From then on you are editing files in
**your** fork:

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
`/chat` and the API from a single origin on port 8000.** The frontend calls
`http://localhost:8000` absolutely, so map that port as-is. `./workflows` is
bind-mounted, so a workflow saved in the container lands in the repo.

One worker, deliberately: the human-in-the-loop checkpointer is an in-process
`InMemorySaver`. Scaling out needs a persisted checkpointer first.

### Upgrading — the honest part

You forked, so upgrading is a merge:

```bash
git remote add upstream <the-upstream-repo>
git fetch upstream
git merge upstream/main
```

The friction is real and worth stating before you commit to this mode:

- **Your workflows sit in a tracked directory of the upstream tree.** They are
  *your* files with *their* siblings (`chinook-nl-to-sql`, `page-analytics`,
  `concierge`, `workflow-architect`) around them. Adding files rarely
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
openstategraph run ./workflows/chinook-nl-to-sql "How many invoices are there?"
```

That is the whole first five minutes. The rest of the commands each wrap a
seam the library already has — there is no behaviour in the CLI that
`load_workflow` does not have:

| Command | What it does |
| --- | --- |
| `openstategraph run <package> "<question>"` | ask it. `--model`, `--thread-id`, `--trace-file`, `--knowledge-dir`, and `--json` for the whole result rather than the answer |
| `openstategraph validate <package\|workflow.json>` | the compiler's plan and findings. **Exit 1** on blocking findings, so it is a CI gate |
| `openstategraph graph <package>` | the compiled topology as Mermaid **text**, on stdout. Never a network call — but it *builds* the graph, so a package with an agent needs a provider extra installed (exit 3 otherwise). `validate` needs no provider |
| `openstategraph new <slug> [name] [--team]` | scaffold a package into `./workflows` (`--root` to change that) |
| `openstategraph knowledge list <package>` | the second brain's topics and their one-line hints (`--knowledge-dir` to look elsewhere) |
| `openstategraph knowledge build <package>` | generate them; prints `written / skipped / collisions / warnings`. `--source` runs one builder, `--instruction` steers the agentic one, `--model` picks the model |
| `openstategraph serve [--host --port]` | the editor's HTTP API. Needs `openstategraph[server]` |
| `openstategraph mcp [--transport stdio\|streamable-http]` | the MCP transport. Needs `openstategraph[mcp]` |

Exit codes are fixed, because they are what CI consumes: **0** success, **1**
run or validation failure, **2** usage error, **3** a required extra is missing
(the message names the exact `pip install` line). Every command takes its paths
from its arguments, so it works from any directory.

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
| `.warnings` | tools/functions/subgraphs the package names but could not be resolved |
| `.ask(question, *, thread_id=None, recursion_limit=50)` | run it once, get a `RunResult` |
| `.as_tool(name=…, description=…)` | this workflow as one LangChain tool (see below) |
| `.mermaid()` | the compiled topology as text, no network call |
| `.slug` / `.package_dir` / `.document` | what it loaded, and from where |

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
| `.warnings` | the workflow's unresolved capabilities, carried along |
| `.attempts` | how many grader revise laps the run took |

> At 1.0 this becomes a plain dataclass with `.answer`. Build on the five
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

Arguments worth knowing:

- **`model`** — a model string (`"anthropic:claude-haiku-4-5"`,
  `"ollama:gpt-oss:120b-cloud"`), resolved through the *same* path the HTTP API
  uses, or an already-built LangChain model object, passed through untouched.
  Omit it and you get the document's own `settings.model` if it names one,
  otherwise the environment default: `ANTHROPIC_API_KEY` → Claude,
  `OPENAI_API_KEY` → GPT, else Ollama **cloud**. A node that names its own
  model still wins over all of it.
- **`checkpointer`** — optional. By default the package's own
  `settings.checkpointer` decides (sqlite, or an in-process saver), which is
  what lets a `human.approval` node pause and `ask(thread_id="...")` continue a
  conversation. Pass a Postgres saver to own durability yourself.
- **`knowledge_dir`** — where the package's second brain is read from.
  Convention (`<package>/knowledge`) stays the default, because
  discovery-by-convention is why this function takes one argument. Override it
  when knowledge is shared between two packages, lives outside the repository,
  or is a fixture directory in a test. It names the directory holding the
  `<topic>.md` files, not the package above it.
- **`trace_file`** — appends one JSON line per `ask()`: question, slug,
  decisions, attempts, warnings, duration, and the answer's **length**. The
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
classifiers, a console script, a lean core and seven extras — built, `twine
check`-clean, and proven by CI's `clean-install` job, which installs it into an
empty virtualenv **outside** the checkout and runs a workflow there. What is
outstanding is one `twine upload` by the maintainer. So the command that will
be the headline is written here as the shape it takes, clearly flagged:

```bash
pip install "openstategraph[ollama]"     # ← after the first release
```

Until that tag ships, install exactly the same artifact from a checkout:

```bash
# Build the wheel and install it anywhere — this is the artifact CI verifies.
python3 -m build /path/to/openstategraph/backend
pip install "/path/to/openstategraph/backend/dist/openstategraph-0.3.0-py3-none-any.whl[ollama]"

# Or editable, from the checkout. The extras are the install story: the core is
# four packages and you add only what your workflow uses —
# [anthropic] [openai] [ollama] [deep] [sqlite] [server] [mcp], or [all].
pip install -e "/path/to/openstategraph/backend[ollama]"

# Or nothing at all, if you would rather not install.
PYTHONPATH=/path/to/openstategraph/backend python your_service.py
```

Either way you get the console script and the same import package. Measured
from a real clean venv: **36 distributions** for the core, **38** with
`[ollama]` — down from 78 before 0.3.0. The Docker image is the third option;
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

- **Build it** with `openstategraph knowledge build <package>`, or the
  Knowledge card's rebuild in the editor. Generated files carry a marker
  comment; `openstategraph knowledge list <package>` prints each topic with its
  one-line index hint.
- **Claim it by editing it.** The first save through the editor strips the
  generated marker, and a claimed doc is never regenerated over. There is no
  autosave — editing a topic is a dialog with an explicit Save, and the result
  lands in git as a diff.
- **Stale is a badge, not a rewrite.** Each generated marker records a hash of
  the brief the doc was written from. When the underlying source moves, the
  hash stops matching and the topic is badged stale — including topics you have
  claimed, because a claimed doc can go out of date too. Topics written by the
  agentic explorer have no recomputable brief and are never badged: unknown is
  not stale.

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
- **`/chat`** (<http://localhost:8000/chat>) is the customer-facing surface: no
  canvas, just a conversation. A concierge workflow routes the question to
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
