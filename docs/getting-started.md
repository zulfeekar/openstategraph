# Getting started

You cloned the repository. This page takes you from that to a workflow you
authored yourself, running against a real database, answering a real question.

Two people arrive here, and they want different things:

- **The developer** wants to open the canvas, understand the palette, change
  something, and see the compiled LangGraph. Follow every section.
- **The end user** wants to ask a question and get an answer. Sections
  [1](#1-prerequisites), [2](#2-start-the-stack) and [5](#5-ask-it-something--chat)
  are enough; the canvas is optional.

## 1. Prerequisites

| | |
| --- | --- |
| **Node** | 20 or newer (developed against 22) |
| **Python** | 3.11 or newer (developed against 3.12 / 3.13) |
| **Docker** | only for `./start` (the production stack). `./start dev` needs no Docker. |
| **A local model runtime** | **not needed.** The backend defaults to Ollama *cloud*. |

No API key is required to get a first answer. Nothing here needs an account
with us, a hosted control plane, or a credit card.

## 2. Start the stack

```bash
git clone <your-fork-or-this-repo> && cd openstategraph
npm install
./start dev
```

`./start dev` runs [`scripts/dev.sh`](../scripts/dev.sh), which supervises both
processes and restarts either if it crashes:

- **editor** — Vite on <http://localhost:5273>
- **runtime** — `uvicorn --reload` on <http://localhost:8000>

Stop with `./start stop`; follow status with `scripts/status.sh`.

The containerised alternative is `./start` on its own: one origin, port 8000,
serving the editor, `/chat` and the API together. Use it when you want the
production shape rather than hot reload.

> **One worker, deliberately.** The human-in-the-loop checkpointer is an
> in-process `InMemorySaver`, so a second worker cannot resume another
> worker's run. Scaling out needs a persisted checkpointer first.

The editor opens on a seeded demo that runs with **no credentials at all**:
the canvas preview's default model is `Mock · Offline`, a deterministic
simulator that exercises the real execution path (it requests a tool, then
answers from the tool's result).

## 3. Models and credentials

There are two separate model paths, and conflating them is the most common
first-hour confusion.

| | Canvas **Run** button (preview) | Backend runtime (Chat, saved workflows) |
| --- | --- | --- |
| Where the call is made | your browser | the Python process |
| Credentials | entered in the editor's credentials dialog, kept in this browser's `localStorage` | environment variables on the backend process |
| Default | `Mock · Offline` | Ollama **cloud** |

**Backend environment.** Nothing is required. Copy `.env.example` to `.env` to
set any of:

| Variable | Effect |
| --- | --- |
| `ANTHROPIC_API_KEY` | backend model resolution prefers Anthropic when set |
| `OPENAI_API_KEY` | checked next, if Anthropic's key is absent |
| `OPENSTATEGRAPH_OLLAMA_MODEL` | overrides the Ollama cloud model id (default `ollama:gpt-oss:120b-cloud`) |
| `OPENSTATEGRAPH_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` (default `INFO`) |

**Ollama means Ollama cloud.** A bare `ollama:` selection resolves to the
cloud model, the picker sorts `-cloud` models first, and a local model has to
be named explicitly. This is a rule with evidence behind it: a local
`llama3.1:8b` answered a Chinook database question from parametric knowledge —
confidently, about global music revenue, having queried nothing — while
`gpt-oss:120b-cloud` wrote a correct two-join `GROUP BY` in 23 seconds. Never
judge a wiring change against a local model; a weak model makes a bug and a
capability gap look identical.

**Browser-side keys** (canvas preview) are stored in `localStorage` and sent
straight from the page to the vendor. That is an acceptable trade for a
local-first editor and the dialog says so — use a scoped, revocable key.

## 4. Run Store Analytics

`page-analytics` ("Store Analytics") is the comprehensive example. It uses
every generic node type at once over the shared Chinook database: intent
routing with a conversation fallback, a supervisor with three worker
archetypes, report formatting, a grader revise loop, human approval, an email
dispatcher (dry-run without SMTP), a quick-metric agent, a mounted Team, and
the focused `chinook-nl-to-sql` example mounted as a subgraph.

1. In the editor, open **Manage workflows** (the document icon in the top bar,
   or `Mod+Shift+F`).
2. Under **Saved Workflows**, open *Store Analytics*.
3. Press **Run** (`Mod+Enter`), or ask through Chat — see below.
4. Watch the node cards. Status flows along the links as each node runs.

Two honest caveats about the canvas **Run** button, both deliberate:

- Nodes that compile to graph *constructs* rather than steps — the Router, the
  Grader, the Orchestrator, discovered backend tools — **refuse to run in the
  browser and say so**. A router compiles to `add_conditional_edges` in Python;
  there is nothing honest for a browser preview to do with it. They exist as
  registered executors rather than being omitted, because a node with no
  executor is silently skipped, and silence is worse than a refusal.
- **Preview execution is sequential**, so a run stays legible on the canvas.
  The compiled LangGraph is the thing that fans out.

Press **View compiled graph** in the top bar to see what the compiler actually
produced — rendered from `draw_mermaid()` locally, with no graph ever sent to
a third party.

### Watching a run, and stopping one

While a run streams, the activity trace beside the conversation shows more
than node names. When a run creates children — an orchestrator's `Send`
fan-out, a deep agent's `task` call, or a mounted Team or subgraph starting —
a row appears reading **`⤷ spawned <label>`** with the first ~120 characters
of the instruction it was given. A spawn is an *announcement*, not a step: it
takes no time of its own and occupies no lane in the timeline, it just names
the child before the child produces anything. That is deliberate — the failure
mode it exists to prevent is a run that looks stalled while five workers are
busy. Spawns appear in the chat trace only; there is no canvas animation for
them.

The **Run** button becomes **Stop** while a run is streaming (so does the
composer's Send). Stop is honest about where it can and cannot reach:

- **It really does stop the backend**, not just your browser. Aborting the
  request closes the SSE stream; the server races that disconnect against each
  frame and stops pulling the graph's generator, so **no further supersteps are
  scheduled**.
- **It cannot interrupt work already dispatched.** Tasks LangGraph handed to
  its executor for the *current* superstep run to completion — a blocking model
  call has no cancellation seam — and their results are discarded. Draining
  measures at roughly 15 seconds for an early stop and up to ~75 seconds in the
  middle of a fan-out. The stream ends immediately; the process quietens after.
- **Stopping a run paused at an approval discards only the local prompt.** The
  thread is checkpointed, so it is still resumable.

## 5. Ask it something — `/chat`

<http://localhost:8000/chat> is the customer-facing side: no canvas, just a
conversation. A concierge workflow routes your question to whichever published
workflow can answer it, and streams the run back token by token.

Try:

> Which genre earned the most revenue, and which country bought the most?

Every figure in the answer is checkable: there is exactly **one** sample
database in this repository —
`workflows/chinook-nl-to-sql/data/Chinook_Sqlite.sqlite`, the standard Chinook
music store — and both examples evaluate against it. One database, one source
of truth, no invented numbers.

## 5b. Ask it something without the stack — the CLI

Neither the editor nor the server is needed to run a workflow. Install the
backend once and the `openstategraph` command is on your `PATH`:

```bash
pip install -e "backend[ollama]"

openstategraph run ./workflows/chinook-nl-to-sql "How many invoices are there?"
openstategraph validate ./workflows/chinook-nl-to-sql   # exit 1 if it will not compile
openstategraph graph ./workflows/chinook-nl-to-sql      # Mermaid text, no network
openstategraph new my-flow                              # scaffold ./workflows/my-flow
```

`--json` on `run` prints the whole result — answer, decisions, outputs,
warnings, attempts, thread id — which is what you want when the answer is
wrong. Exit codes are fixed (`0` ok, `1` failure, `2` usage, `3` a missing
extra), so `openstategraph validate` is a CI gate as it stands.

Without installing at all, every command is
`PYTHONPATH=backend python3 -m openstategraph.cli …`.

## 6. Now extend it

The three directions from here:

- **Use it in a project of your own** — read
  [Using OpenStateGraph in your project](adoption.md). Fork/checkout, artifact
  or MCP, with the upgrade friction of each stated honestly.

- **Arrange existing pieces differently** — read
  [Patterns](patterns.md). Seven shapes, one question re-shaped seven ways,
  and the criteria for choosing between them.
- **Add a capability that does not exist yet** — read
  [Building an atom](building-an-atom.md). A tool node is a TypeScript
  definition plus a Python `BaseTool`, and adding one touches no engine code.

A workflow is a package under `workflows/<slug>/`: `workflow.json` and
`AGENTS.md` are required; `tools/`, `functions/`, `middlewares/`, `tests/` and
`data/` are discovered by convention. `openstategraph new <slug> [--team]`
scaffolds one (as do `scripts/new_workflow.py` and `scripts/new_team.py`,
which call the same code).

That is the value: your flow is **a file in git** — reviewable in a pull
request, diffable — and the compiled output is an ordinary Python
`StateGraph`. Import it from a script, exercise it with pytest, deploy it
wherever Python runs. Delete this editor and your workflow still runs.
