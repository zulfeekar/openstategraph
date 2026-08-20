# Getting started

You cloned the repository. This page takes you from that to a workflow you
authored yourself, running against a real database, answering a real question.

> **Not cloning?** Then you need none of it. `pip install
> "openstategraph[server,ollama]"` followed by `openstategraph serve --open`
> gives you the same product from one process — the canvas at `/`, the customer
> chat at `/chat`, the API under `/api` — because the wheel ships the built
> editor as package data. Node, Docker and this checkout are all optional; see
> [Using OpenStateGraph in your project](adoption.md#the-shortest-path--one-install-one-command-the-whole-product).
> The rest of this page is the *contributor's* path, where the editor is built
> from source and hot-reloads.

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
| **A local model runtime** | **not needed.** The backend defaults to Ollama *cloud*, which needs `OLLAMA_API_KEY`. |

One provider credential is required before anything calls a model:
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `OLLAMA_API_KEY` (or `OLLAMA_HOST`, if
you run your own daemon). Nothing here needs an account with us, a hosted
control plane, or a credit card. The canvas preview still answers with no
credential at all — its default is `Mock · Offline` — and a workflow with no
model-calling node runs with nothing set.

> This said "No API key is required to get a first answer", which was true only
> because Ollama's provider spec declared no environment variables and so was
> always treated as configured. It was not keyless but *ambient*: the cloud was
> reached through a local daemon signing with `~/.ollama/id_ed25519`, a
> credential that never passes through the environment and cannot be seen,
> moved or revoked from one (providers-and-credentials ticket 02).

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
production shape rather than hot reload. `openstategraph serve` gives you that
same one-origin shape without Docker, from an installed wheel or from this
checkout once `npm run build` has run at least once.

> **Approvals persist; still one worker.** The human-in-the-loop checkpointer
> is a SQLite saver at `workflows/.openstategraph/checkpoints.sqlite`, so a
> `human.approval` pause survives the restart `--reload` performs every time
> you save a file. The backend log says which it got on startup — `approvals
> persist at …`, or `approvals are in-memory and will NOT survive a restart`
> (set `OPENSTATEGRAPH_CHECKPOINT_PATH=memory` to choose the latter). The
> worker count stays 1, and asking for more is now refused rather than
> discouraged — `SqliteSaver` is documented single-process and the live
> catalogue-event fan-out is in-process. See
> [Deploying for other people](deploying.md) when this stops being your own
> machine.

The editor opens on a seeded demo that runs with **no credentials at all**:
the canvas preview's default model is `Mock · Offline`, a deterministic
simulator that exercises the real execution path (it requests a tool, then
answers from the tool's result).

> **Only in a checkout.** The seed is `workflows/chinook-assistant/workflow.json`,
> which exists here and does not exist in a `pip install` — so a wheel install
> opens on a blank canvas instead, with the templates and the examples shelf in
> the Workflows drawer. Shipping the demo inside the bundle was
> workflow-gallery ticket 41: a customer met a 13-node graph they had not made
> and could not run.

## 3. Models and credentials

There are two separate model paths, and conflating them is the most common
first-hour confusion.

| | Canvas **Run** button (preview) | Backend runtime (Chat, saved workflows) |
| --- | --- | --- |
| Where the call is made | your browser | the Python process |
| Credentials | entered in the editor's credentials dialog, kept in this browser's `localStorage` | environment variables on the backend process |
| Default | `Mock · Offline` | Ollama **cloud** |

**Backend environment.** Nothing is required to start the backend, and a
workflow that calls no model runs with none of this set — a credential is
checked at the moment a model is *used*, not when one is built
(`UnconfiguredProvider` in `backend/openstategraph/chat_model.py`). Calling a
model needs one of the three provider credentials. Copy `.env.example` to
`.env` to set any of:

| Variable | Effect |
| --- | --- |
| `ANTHROPIC_API_KEY` | backend model resolution prefers Anthropic when set |
| `OPENAI_API_KEY` | checked next, if Anthropic's key is absent |
| `OLLAMA_API_KEY` | configures Ollama **cloud**, the last of the three |
| `OLLAMA_HOST` | *instead* of the key: a daemon you run, local or self-hosted, which needs no key of ours because it owns its own auth. Also the endpoint, ahead of `OLLAMA_ENDPOINT` |
| `OLLAMA_ENDPOINT` | where the cloud is; defaults to `https://ollama.com`, rarely set |
| `OPENSTATEGRAPH_OLLAMA_MODEL` | overrides the Ollama cloud model id (default `ollama:gpt-oss:120b-cloud`) |
| `OPENSTATEGRAPH_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` (default `INFO`) |

The two Ollama variables are alternatives, not a pair —
`ProviderEnvironment.is_configured`
takes **any** of a provider's `env_vars`, so either one alone is enough and
neither means the provider is skipped. With both set, the host wins for routing
and the key rides along as a bearer token. Endpoint precedence is tuple order:
`OLLAMA_HOST`, else `OLLAMA_ENDPOINT`, else `https://ollama.com`. Anthropic and
OpenAI are passed no `base_url`; their SDKs already read `ANTHROPIC_BASE_URL`
and `OPENAI_BASE_URL`/`OPENAI_API_BASE`.

Until providers-and-credentials ticket 02 nothing passed an endpoint at all, so
`ollama.Client` defaulted to `127.0.0.1:11434` — "Ollama means cloud, never
local" was being broken by omission rather than by decision.

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

### Reasoning effort

Every node that drives a model — Agent, Router, Grader, Supervisor, Worker —
carries a **Reasoning** picker directly beneath its model picker, under
*Model* in the inspector. It is one field, declared once and given to those
node types by the fact that they have a model picker at all, so a new
model-driven node type gets it without asking.

It defaults to **Model's default**, which does not send the parameter. That is
not a display default: providers disagree about what their own default is
(`claude-sonnet-4-6` defaults to `high`), so seeding a tier would change how
existing workflows run while looking cosmetic.

**Nothing breaks on a model that cannot reason**, and the two ways that could
go wrong are handled separately because they are different failures:

| | What would happen | What happens |
| --- | --- | --- |
| Provider **rejects** the parameter (OpenAI, on a non-reasoning model) | the run dies for a setting nobody meant to be load-bearing | the parameter is not sent, and the run carries a warning saying so |
| Provider **ignores** it (`ChatOllama` has no `reasoning_effort` field at all) | the card reads "high" over a model that never heard it | same: not sent, and said out loud |

The warning arrives on the run's `warnings` — the same channel that reports an
unresolved tool — so it reaches the run response, the CLI and the MCP preview
without being looked for.

**Capability is discovered, not listed.** A hardcoded set of reasoning-capable
model ids is wrong within a month, so the runtime asks two questions that have
real answers:

- **Can this integration carry the value?** `reasoning_effort` is a standard
  LangChain parameter (`langchain-core>=1.5.2`), declared by each partner
  package as a field whose type enumerates the spellings it accepts.
  `ChatAnthropic` accepts `low`/`medium`/`high`/`xhigh`/`max`; `ChatOllama`
  has no such field.
- **Does this model reason, and at which tiers?**
  `model.profile["reasoning_effort_levels"]`, from the models.dev dataset
  shipped inside each partner package.

Both move when you update your provider packages, not when this repo is
edited. A model whose profile is silent is treated as *unknown*, not as a
refusal — `claude-haiku-4-5` reasons and publishes no tiers, and refusing it
would deny a setting that works.

The editor mirrors the same three states in the picker: the model's declared
tiers where a provider knows them, the common `low`/`medium`/`high` where it
cannot know (a model discovered from `/api/tags` at run time), and — for a
model known not to reason, such as the offline simulator — **no tiers at all**,
just a line naming the model. A control that reaches nothing is worse than no
control.

## 4. Run the Chinook Assistant

`chinook-assistant` is the checkout's worked example, and it is deliberately small
enough to read in a glance. Left to right: a question, a **Router** with five
intents, three destinations, one answer.

| Branch | Goes to | Because |
| --- | --- | --- |
| `data_query` | **Data Analyst** — an agent with the three Chinook tools, behind a grader | it needs the database, and the grader sends a bad answer back until it holds up |
| `greeting` / `off_topic` / `general_knowledge` | **Front Desk** — one agent, no tools | none of the three needs a tool, a database or a second model call |
| `web_lookup` | **Web Researcher** — web search + web fetch | only the live web has the answer |

The analyst is **inline**, not a mount. It used to be a second package
(`chinook-nl-to-sql`) behind a `workflow.subgraph` — and that second package
was what the editor seeded, so a first-time reader opened a graph with no
router in it. One document now, and the loop that matters is on it: agent →
grader → (`revise`) → agent, bounded at three attempts, then the Markdown
output node.

Nothing here is mounted, either. A mounted workflow is worth its keep when
the child has several worker *roles* to plan for; here there is one, so a
supervisor's planning call and fan-out would be paid for and not used.

That cost belongs to the **child package**, not to the card you drag — and
there is one mount card, **Workflow**. A `Team` card used to sit beside it and
compile through the same builder with no branch; schema v3 removed it, because
a glyph, an `outcome` field that nothing enforces and a loop the child document
earns are not a kind of node. A team is now a package *shape* you mount like
any other. The Workflow card carries the optional *Expected outcome
(documentation)* field, and shows "loops until its grader passes" when the
mounted document really does have a grader wired back to its agent.

Two things on this canvas are worth a second look, because they are the
answer to "how do I customise a prebuilt node without editing it":

- The Data Analyst's own **prompt field is empty**. Its rules arrive over the
  `skill` port from the **SQL Analyst skill** card beside it — a Markdown
  file, wired in like any other input.
- Unwire it and the agent still works. Every model-driven node type ships
  built-in rules underneath whatever you write; see
  [the skill layer](decisions/skill-layer.md) for the three layers and how
  `rulesMode` chooses between them.

1. In the editor, open **Workflows** (the button in the top bar, or
   `Mod+Shift+F`). It read *Manage workflows* on this page until 2026-08-16;
   the button says `Workflows`, which is what step 1 of the *save your own*
   walkthrough below already called it.
2. Under **Saved Workflows**, open *Chinook Assistant*.
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
fan-out, a deep agent's `task` call, or a mounted workflow starting —
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
  measured (once, 2026-08-10, and by nothing since) at roughly 15 seconds for an early stop and up to ~75 seconds in the
  middle of a fan-out. The stream ends immediately; the process quietens after.
- **Stopping a run paused at an approval discards only the local prompt.** The
  thread is checkpointed, so it is still resumable.

### The Chat panel is a conversation, not a series of questions

A follow-up continues the last question. "How did you get that?" gets the join
explained; "remind me what the top genre was" answers from what was already
found rather than querying again. That is a real LangGraph thread underneath —
the graph's `messages` channel accumulates in it — not a transcript the panel
re-sends.

A conversation lasts until one of three things ends it, and **New** in the
panel header is the one you press on purpose:

- **New** — the next question starts fresh. The transcript stays where it is,
  with a `New conversation` rule drawn across the thread, because a run's trace
  is evidence: starting over should not also delete what the last conversation
  showed you.
- **Opening a different workflow** starts one for you. LangGraph's checkpointer
  is keyed by thread id alone, so carrying one across documents would replay the
  previous workflow's history into a different graph.
- **Reloading the editor** starts one. The panel deliberately does *not* persist
  its thread, and this is where it differs from `/chat`, which does. The
  transcript is not persisted either — so restoring the id alone would leave you
  in a conversation whose earlier turns exist on the server and nowhere on
  screen, which is an answer with an invisible antecedent. In an editor a reload
  usually follows an *edit*, and the checkpointed history belongs to the graph as
  it was. `/chat` runs a published workflow nobody is editing, so persisting is
  right there and would be wrong here.

**History** in the Chat panel header shows what those checkpoints hold: past
runs of this workflow, newest first, each expanding to the run superstep by
superstep — the question, the answer, and how the state looked at every step in
between. It reads only. Opening a past run calls no model and spends nothing;
a run still parked at an approval is marked and points back at the chat, which
stays the single way to continue one. Runs appear here whenever the backend has
a checkpointer, which the dev stack configures by default.

## 4b. Or don’t draw one — copy a worked example

**23** finished packages ship inside OpenStateGraph, one per pattern the
canvas can express. They are the fastest way to see a working flow that is not
the Chinook Assistant, and the journey to them is three verbs:

> **Browse → copy → it is yours.**

They are **not in your project** until you copy one. They live in the installed
package, outside your workflows root, which is why they never appear in
`GET /api/workflows`, in the `/chat` picker, or in the generated project
knowledge. Taking one is a *copy*, and the copy is **severed**: it is a draft in
your own `workflows/` from that moment, and upgrading OpenStateGraph never
reaches back into it. There is no "load an example" and no `eject` — nothing is
ever borrowed from the gallery.

### In the editor

1. Open **Workflows** in the top bar (or `Mod+Shift+F`).
2. Scroll to the **Examples** section and press
   **"23 examples — copy one to make it yours"**. The shelf is collapsed until
   you ask for it, and it remembers the answer — before you have any workflow of
   your own, an open gallery would make this panel someone else’s finished work
   above your nothing.
3. Press **Copy** on one. `Copy +2` means it mounts other packages and the copy
   brings them; the button's tooltip names them before it writes anything.
4. It appears under **Saved Workflows** as a draft. Press **Open**, then **Run**.

On a fresh install a one-time hint on the **Workflows** button points at all of
this. It appears once, counts dismissal as an answer, and does not come back.

### On the command line

Same three verbs, no editor and no server:

```bash
openstategraph examples list                     # slug, pattern, one-line purpose
openstategraph examples copy evaluator-optimizer # …with every package it mounts
openstategraph run ./workflows/evaluator-optimizer "Write a two-sentence release note."
```

`examples list` prints them in reading order and marks the ones that mount
others (`[+1 mounted]`). `copy` writes into your workflows root — `--root` to
put it elsewhere, `--all` to take the lot after it prints the size. It refuses
the whole set before writing a byte if a directory would be overwritten (exit
`1`, nothing written); an unknown slug exits `2` and lists the real ones.

Which example, and how an example differs from a template and from a mount, is
[On the canvas §6](on-the-canvas.md#6-an-example-is-a-whole-package-and-you-take-a-copy-of-it).

## 5. Ask it something — `/chat`

<http://localhost:8000/chat> is the customer-facing side: no canvas, just a
conversation. A concierge workflow routes your question to whichever published
workflow can answer it, and streams the run back token by token.

It is the **same process** as the editor, reading the **same** workflows
directory — `/chat` is a path, not a second server. What makes a workflow
appear there is one human action: **Publish**. Saving writes a draft, and
drafts are invisible in `/chat`.

Try:

> Which genre earned the most revenue, and which country bought the most?

Every figure in the answer is checkable: there is exactly **one** sample
database in this repository —
`workflows/chinook-assistant/data/Chinook_Sqlite.sqlite`, the standard Chinook
music store — and the example evaluates against it. One database, one source
of truth, no invented numbers.

## 5b. Ask it something without the stack — the CLI

Neither the editor nor the server is needed to run a workflow. Install the
backend once and the `openstategraph` command is on your `PATH`:

```bash
pip install -e "backend[ollama]"

openstategraph run ./workflows/chinook-assistant "How many invoices are there?"
openstategraph validate ./workflows/chinook-assistant   # exit 1 if it will not compile
openstategraph graph ./workflows/chinook-assistant      # Mermaid text, no network
openstategraph new my-flow                              # scaffold ./workflows/my-flow
openstategraph new --list-templates                     # what you can start from
openstategraph examples list                            # the worked examples in the wheel
openstategraph examples copy evaluator-optimizer        # take one; the copy is yours
```

The templates ship inside the package, so they are there on a machine that
never cloned this repository — and the editor's **New Workflow → Start from**
picker offers the same set, in the same order, from the same
`templates/index.json`. Cheapest first:

| `--template` | What you get | When |
| --- | --- | --- |
| `minimal` *(default)* | input → agent → output | a first run: one model call, and nothing in it that can reject the answer |
| `loop` | an agent drafts, a grader reviews, weak answers go back | you want the revision loop and nothing else — the smallest thing that shows a cycle |
| `routed-qa` | input → router → agent → grader → output, plus a second branch that skips the grader | the shape most assistants end up with, and the one that teaches branches and the revision loop |
| `team` | supervisor → worker → join → grader | the work splits into parallel subtasks. Mount the result anywhere with the `Workflow` card — "team" is a package shape, not a node type |

Beside the templates sit the **examples**: finished packages, one per pattern
the canvas can express, shipped in the same wheel and listed by
`openstategraph examples list` (or the editor's **Workflows → Examples**
shelf). The difference is what you get: a template is rendered into an
empty-ish package for you to fill; an example is copied whole — tests,
knowledge store, eval fixture and all — because it is the package that was
actually built and run. They are not in your project until you copy one, and
the copy is severed: upgrading OpenStateGraph never reaches back into it.
See [On the canvas §6](on-the-canvas.md#6-an-example-is-a-whole-package-and-you-take-a-copy-of-it).

An unknown name exits `2` and lists the valid ones. `--team` still works as a
deprecated alias for `--template team`. Each scaffolded package gets an
`AGENTS.md` describing what was created and the obvious next step.

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

A workflow is a package under `workflows/<slug>/`: **`workflow.json` is the
only required file** — a directory holding nothing else validates and runs.
`AGENTS.md` is a strong convention rather than a requirement, and every
scaffold and every shipped example writes one, because it is where a package
records what it actually answered. `tools/`, `functions/`, `middlewares/`,
`skills/`, `knowledge/`, `evals/`, `tests/` and `data/` are discovered by
convention. `openstategraph new <slug> [--template
NAME]` scaffolds one (as do `scripts/new_workflow.py` and
`scripts/new_team.py`, which call the same code).

**Each one has a URL you can send.** The editor's address bar carries the open
workflow's slug — <http://localhost:5273/?w=chinook-assistant> — so a
workflow can be bookmarked, linked to a colleague, and reopened by reload. The
slug is minted once, by the backend, when the workflow is first saved: the
first "My Workflow" gets `my-workflow`, and a second one of the same name gets
its own `my-workflow-<six characters>` rather than overwriting the first. It
never changes afterwards, so renaming a workflow keeps every link, mount and
line of git history pointing at it.

Two things the URL deliberately leaves out. **A chat thread** — the Chat
panel's transcript is not persisted, so restoring a thread id alone would drop
you into a conversation whose earlier turns exist on the server and nowhere on
screen. And **your unsaved edits**: reloading a link to the workflow you
already have open restores this browser's autosave rather than refetching the
file, so a reload never discards work. Opening a link in a second tab gives
that tab its own autosaved copy and leaves the first alone.

That rule has one clause worth stating, because getting it wrong cost a
workflow: *restore* only ever means restoring something. When there is no
autosave to restore — cleared site data, an eviction, a browser that has never
seen this workflow — the editor fetches the file, and it does so whether or not
the URL carries the slug. **A missing autosave is never an empty canvas**
(`production-ready` 49 and 71). An empty canvas that still believed it was a
saved workflow is what let a blank document be written over a real one.

The other half of the same rule is what **New** does: a new workflow gets an
identity of its own from the moment it exists, so nothing you draw in it is
filed as unsaved edits to the workflow you were just looking at. Your edits to
that one stay exactly where they were, waiting for you to come back to it
(`production-ready` 77).

That is the value: your flow is **a file in git** — reviewable in a pull
request, diffable — and the compiled output is an ordinary Python
`StateGraph`. Import it from a script, exercise it with pytest, deploy it
wherever Python runs. Delete this editor and your workflow still runs.
