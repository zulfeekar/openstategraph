# Contributing to OpenStateGraph

> **Who this page is for:** you cloned this repository and intend to change
> OpenStateGraph itself.

Two stacks, one repo: a TypeScript editor (`src/`) and a Python LangGraph
runtime (`backend/`). Architecture rules live in `CLAUDE.md` — read the
"Non-negotiables" section before designing anything.

## Setup

```bash
npm install && npm run dev                 # editor → http://localhost:5273
pip install -e "backend[all,dev]"          # runtime deps — see below
PYTHONPATH=backend:workflows/chinook-assistant \
  uvicorn openstategraph.api.main:app --port 8000 --app-dir backend
```

The editor runs on a deterministic Mock provider and needs no key. The backend
defaults to Ollama cloud, which needs `OLLAMA_API_KEY` in `.env` — or
`OLLAMA_HOST`, if you point it at a daemon you run; `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` is used ahead of it. The test suite needs none of them.

> This said "No API keys required." That was true only because Ollama's
> `ProviderSpec` declared no environment variables and so was always treated as
> configured — an *ambient* credential (a local daemon signing with
> `~/.ollama/id_ed25519`), not the absence of one
> (providers-and-credentials ticket 02).

`[all]` is a *contributor's* install. A consumer installs the lean core —
`langgraph`, `langchain`, `langchain-core`, `pydantic` — plus whichever extras
their workflow actually uses (`[anthropic]`, `[openai]`, `[ollama]`, `[deep]`,
`[sqlite]`, `[server]`, `[mcp]`). Adding a dependency to the core table
without the accompanying case for it fails
`backend/tests/test_distribution_metadata.py`, which is the point.

## Running the stack on a checkout

**You cloned this repository.** This is the contributor's path — a reader who
installed the wheel needs none of it and should follow
[`README.md`](README.md) instead.

You need Node 20+ (developed against Node 22) and Python 3.11+ (developed
against 3.12/3.13). Node is needed **only** here: an install from the wheel
carries the built editor. No local model runtime is needed either — the backend
defaults to **Ollama cloud** (an Ollama account, not a local `ollama serve`),
and a credential is required at the moment a model is *used*, not when one is
built (`UnconfiguredProvider` in
[`backend/openstategraph/chat_model.py`](backend/openstategraph/chat_model.py)).

Two processes, two languages, run separately. There is deliberately no single
unified dev command: a Vite process and a uvicorn process have little in common
to unify, and a Makefile wrapping "run these two things" would be one more
thing to keep in sync with the two scripts below.

```bash
npm install
scripts/dev.sh     # supervised backend + editor; scripts/dev.sh stop; scripts/status.sh

# — or by hand —
# Terminal 1 — the editor
npm run dev        # http://localhost:5273

# Terminal 2 — the runtime (optional: the editor works read-only without it,
# but Chat and saving workflows both need it).
#
# Both lines run from the REPO ROOT. `pip install -e .` inside backend/ gives
# you the lean core, which has no fastapi and no uvicorn; and after a
# `cd backend` both PYTHONPATH entries below resolve to nothing — silently,
# not with an error, so the workflow's tools/ and functions/ just never import.
pip install -e "backend[all,dev]"   # fastapi + uvicorn are in the [server] extra
PYTHONPATH=backend:workflows/chinook-assistant \
  uvicorn openstategraph.api.main:app --port 8000 --app-dir backend

npm run build      # tsc -b && vite build
npm run typecheck
```

This backend serves `/chat`, `/docs`, `/openapi.json` and everything under
`/api`. **`GET /` is a 404 here, on purpose**: in the two-process dev setup
Vite owns the editor, on :5273. Only the single-origin modes —
`openstategraph serve` (which `openstategraph .` calls) and the Docker image,
which set `OPENSTATEGRAPH_SERVE_STATIC=1` — mount the built editor at `/`, and
there a checkout with no `npm run build` gets a page explaining that rather
than a bare 404.

### What the canvas opens on

Opens on a **blank canvas**: an address that names no workflow opens no
workflow, whoever last used this browser (`install-experience` 23). Blank is
not the same as silent, though — the canvas **offers the workflows this project
holds**, most recently opened or edited first, in a dialog you can dismiss
(`install-experience` 28). Dismissing selects nothing, and the canvas behind it
carries the same list under **Start** and **Recent**. `?w=<slug>` still wins:
it opens that workflow and shows no dialog, so a link a colleague sends lands
where it says.

The one exception is the **first** visit in a browser that has never held any
work, which is handed a starter — Input → Agent → Output, wired, with a note
saying what it is (`install-experience` 24), and is not also asked to pick.
It is unsaved and called `Untitled`, nobody else's document, and deleting it is
permanent: it is offered once. Otherwise open one from the arrival list or from
**Workflows**, start from a template, or copy an example.

### Docker

One command, either way:

```bash
./start        # production stack in Docker — build + run, then http://localhost:8000/
./start dev    # local dev with hot reload — Vite :5273 + uvicorn --reload :8000
./start stop   # stop whichever is running
./start logs   # follow the container logs
```

`./start` builds a multi-stage image (Node compiles the editor, a throwaway
stage builds the Python wheels) whose final layer is Python slim plus runtime
deps, the built `dist/`, `backend/` and `workflows/`. The backend serves the
editor, `/chat` and the API from a single origin on port 8000. Map it to any
host port you like: the editor's API calls are **same-origin relative**, so
they follow the page wherever it is published (`src/core/runtime/runtimeBaseUrl.ts`
— an absolute `http://localhost:8000` used to make port 8000 mandatory).
`./workflows` is bind-mounted, so workflows saved in the container land in the
repo.

**Approvals persist by default.** The human-in-the-loop checkpointer is a
SQLite saver on `<workflows root>/.openstategraph/checkpoints.sqlite`, so a
`human.approval` pause survives a restart — including the restart `--reload`
performs every time you save a file. The server logs which one it got at
startup: `approvals persist at …`, or `approvals are in-memory and will NOT
survive a restart`. Set `OPENSTATEGRAPH_CHECKPOINT_PATH` to move the file, or
to `memory` to opt out of durability on purpose.

**One worker, and a second one is refused.** Durability is fixed; concurrency
is not. `SqliteSaver` and the long-term memory `SqliteStore` serialise writes
with a `threading.Lock` held per instance, which two OS processes do not share;
the live catalogue-event fan-out behind `GET /api/events` is an in-process
queue. So `--workers 2`, `WEB_CONCURRENCY` and friends are refused before a
socket is bound, and an exclusive lock on the state directory refuses
`uvicorn --workers 4` and `gunicorn -w 4` too, which leave no environment
trace. `[postgres]` + `OPENSTATEGRAPH_POSTGRES_URL` puts checkpoints and
memories in a real database — worth doing, and deliberately **not** a lift on
the ceiling, because the event fan-out still has no cross-process transport.
[`docs/deploying.md`](docs/deploying.md) has the whole story, plus the threat
model and a committed reverse proxy.

Rationale for each choice is commented inline in `Dockerfile`,
`docker-compose.yml`, `start` and `scripts/dev.sh`.

### The example workflows in this checkout

`chinook-assistant` is the checkout's worked example, evaluated against
`workflows/chinook-assistant/data/Chinook_Sqlite.sqlite`, the standard Chinook
music store. One database per package is the single source of truth: every
figure the example produces can be checked against the same file. (The wheel's
`sql-qa` example ships its own copy of the same database, for the same reason
an example is copied whole rather than mounted where it lies.) The rest of
`workflows/` in this checkout is the app spine — the concierge and the
architect — plus whatever is being drafted; `openstategraph examples list` is
the gallery.

- **`chinook-assistant`** ("Chinook Assistant") — a router with five intents
  in front of three destinations. A **data question** goes to a SQL analyst;
  a **greeting**, an **off-topic** request or a **general-knowledge**
  question is answered directly by a tool-less Front Desk agent; a **web
  lookup** goes to an agent holding web search and web fetch. Thirteen
  nodes, one document, nothing mounted.

The analyst is the `data_query` branch, not a separate package: an agent
bound to three Chinook tools (list tables → schema → read-only query), taking
its rules from a wired Markdown skill file, behind a grader that sends a bad
answer back for another attempt, up to three times. It is inline rather than a
mount because **there was a second Chinook document and it was the one the
editor opened** — so a reader met a graph with no router in it. Nothing is
mounted here either, and the reason is the *package* a mount would point at,
not the card: a supervisor-plus-workers package buys a planning call and a
fan-out, and there is exactly one worker role to plan for. The revision loop is
what the branch needs; the planner is what it would pay for and not use.
(`Team` and `Workflow` are the same builder — the card changes nothing about
what runs.)

The recorded cost: no *visible* example demonstrates composition any more.
The hidden `concierge` still mounts this workflow and `workflow-architect` as
subgraphs, and `docs/patterns.md` documents the atom, but nothing a first-time
reader opens does.

Two hidden infrastructure workflows (`concierge`, `workflow-architect`) power
the chat gateway and the build-me-a-workflow flow — **in this checkout.**
Both live under this repository's `workflows/`, outside `backend/`, so
neither one is in the wheel: a `pip install` gives you no in-app "describe
what you want" surface. The same capability for a wheel install is
[`docs/mcp.md`](docs/mcp.md) §2 — `openstategraph mcp` turns your own MCP
client's model into the composer, talking to this server as the ground truth
and the artifact factory. `openstategraph new <slug>
[--template loop|minimal|routed-qa|team]` (or `scripts/new_workflow.py` /
`scripts/new_team.py`, which call the same code) scaffolds your own packages
from templates that ship inside the wheel.

> Previously this section listed three examples. `page-analytics` ("Store
> Analytics") and `chinook-metrics-team` were deleted: a diagram nobody can
> read has failed regardless of what it does, and one example that is read is
> worth more than three that are skipped.

## The non-negotiables your pull request is judged against

These are the rules a maintainer will block on. They are argued in
[`CLAUDE.md`](CLAUDE.md); this table is the short form plus **the gate that
actually catches a violation** — and, where there is none, that fact stated
rather than implied. A principle with no gate is not a weaker principle; it is
one where review is the only thing between the rule and the tree, so the
argument in your pull-request description carries the weight the test would.

| Non-negotiable | What fails you |
| --- | --- |
| **Interface → Abstract → Base → Concrete.** Every entity family declares the ladder, and consumers import the `I*` interface, never the class. Inheritance must earn itself. | **Gate**, for the agent family: `backend/tests/test_agent_family.py` pins `IAgent → AbstractAgentNode → Base/React/Deep/Custom`, including that `DeepAgentNode` is a *sibling* of `ReactAgentNode`. `backend/tests/test_agent_node_wiring.py` refuses inline construction. Other families are held by the API snapshot and by review. |
| **No god classes** — ~10 public members, one reason to change. `WorkflowController` is at its ceiling; extend it with a collaborator, never a method. `WorkflowModel` is a *recorded exception*, not an open invitation. | **No gate.** Nothing counts members. `src/controller/WorkflowController.ts` states the rule in a comment and a reviewer enforces it; "this adds a public member to `WorkflowController`" is a blocking comment however good the code is. |
| **Extend by registering, never by editing the engine.** Every extension point is a `Registry<T>`; a new capability must not require touching `core/`. | **Partial.** The mechanism is tested (`src/core/kernel/kernel.coverage.test.ts`; `backend/tests/test_extensions.py`, `test_plugin_capabilities.py`) but nothing detects a capability added *by editing `core/`* instead of registering. Review catches that. |
| **`core/` imports neither React nor JointJS.** It is plain TypeScript that could run in Node or a worker. | **Gate**, as of ship-it ticket 02: `eslint.config.js` carries a `no-restricted-imports` block scoped to `src/core/**` that **errors** on `react`, `react-dom`, `@joint/*`, and relative escapes into `canvas/`, `view/`, `app/` or `controller/`. It fires in your editor, and in `npm run verify`. The tree was clean when the rule landed. |
| **Pydantic is the single source of truth for the run/stream seam**, published as the generated `docs/openapi.json`. | **No gate on the TypeScript side yet, and the rule has been narrowed to say so.** There is no pydantic → TypeScript generator and there will not be one — `src/core/runtime/RuntimeClient.ts` is a deliberate hand-written client, and the decision (plus the three reasons codegen was rejected, and the drift test that should replace it) is [`docs/decisions/typescript-runtime-types.md`](docs/decisions/typescript-runtime-types.md). Until that test lands, a hand-mirror is review-only: expect a reviewer to ask which schema it mirrors. The Python half of the seam *is* gated — see the `docs/openapi.json` row below. |
| **`port_specs.json` is generated from the TypeScript node catalogue** (the one place TypeScript is authoritative). | **Gate, both sides.** `src/nodes/portSpecs.test.ts` compares the committed bytes inside `npm run verify`; CI's `generated-port-specs` job regenerates and diffs. Fix with `npm run generate:ports`. |
| **`docs/openapi.json` is generated from the FastAPI app.** | **Gate, both sides.** `backend/tests/test_openapi_contract.py` plus CI's `generated-openapi` job. Fix with `python3 scripts/generate_openapi.py`. |
| **Expressions are a JSON AST, never host-language code.** A router predicate is serialisable data, never a Python or JavaScript lambda. | **No gate.** No schema rejects a code-shaped value in `workflow.json`. Review only. |
| **Reducers are a named enum**, and a state key more than one node type can write needs one. | **Gate, per channel**: `backend/tests/test_answer_channel_concurrency.py`, `test_attempts_channel_concurrency.py`, `test_feedback_channel_concurrency.py` assert the named reducer on `RunState.__annotations__`; `test_turn_reset.py` pins that every named reducer understands `RESET`; `test_architecture_audit_2026_08.py` fails the day a second node writes `question`. A **brand-new** channel with an inline lambda matches no test — add the assertion with the channel. |
| **The compile seam is one-directional**: `workflow.json` → runtime, never back. Nothing reads runtime objects into the model. | **No gate.** Stated in `backend/openstategraph/compile/workflow_compiler.py` and probed indirectly by `backend/tests/test_mount_overrides.py` (overrides apply to the child *document*). A new read-back that avoids those behaviours passes. |
| **Our own runtime vocabulary** — LangGraph type names never leak into `workflow.json` or `core/`. | **Weak.** `backend/tests/test_plugin_interop.py` checks a fixed token list on *plugin* import only. Nothing scans the shipped documents or `src/core/`. |
| **Middleware order is a named slot table**, never a list position or a priority integer. | **Gate.** `backend/tests/test_agent_family.py` — replacement by slot name, unknown slots appended in insertion order, removal empties a slot. |
| **The output contract is composed last and is not editable.** A developer supplies rules; the base keeps the shape of the answer. Never ship the contract as a pre-filled editable field. | **Gate — the strongest one here.** `backend/tests/test_skill_layer.py` drives the real `SystemPrompt` across agent, grader, router and orchestrator and asserts the contract is last whatever a skill says. Structurally, `backend/openstategraph/abc/prompt.py` gives the editable layer no reach into preamble or contract. |
| **Cardinality belongs to the port**, not the node: `maxConnections` on the port descriptor, enforced by `capacityRule`. No node-level "multiple edges" flag. | **Gate.** `src/core/model/contracts/ports.test.ts` pins the resolved defaults; `ConnectionValidator.test.ts` (`describe('capacity rule')`) pins replacement, fan-out and the tool bus. |
| **Never put a non-finite number in a serialisable field.** `int \| None`, with `None` meaning unbounded. | **Gate, three layers.** `src/core/model/contracts/ports.test.ts` sweeps every registered node's ports; `src/nodes/portSpecs.test.ts` requires a finite number or an explicit null; `backend/tests/test_node_catalogue.py` pins `None`-means-unbounded. |
| **The published Python surface does not change by accident.** | **Gate.** `backend/tests/test_public_api.py` diffs a *signature*-level snapshot (`backend/tests/public_api.txt`) — a renamed parameter or a flipped default fails it. Failing it is a decision to make deliberately, not a bug to paper over. |
| **We are a compiler, not a runtime.** Any proposal to interpret the graph ourselves is a proposal to reimplement checkpointing, `Send`, reducers and streaming. | **No gate, and none is possible.** Rejected in review, on the argument in `CLAUDE.md` § *We are a compiler, not a runtime*. |

Two more that are policy rather than architecture: **LangGraph and LangChain
facts come from the `docs-langchain` MCP server, never from memory**, and
**Ollama means Ollama cloud** — never benchmark, demo or debug against a local
model and report the result as representative. The cloud is reached by
`OLLAMA_API_KEY` and the `default_endpoint` on Ollama's `ProviderSpec`, not by
an ambient local daemon; a spec that reaches a vendor without naming a variable
someone can set, see and revoke is the defect ticket 02 closed.

## Tests — the gate for every PR

```bash
npm run verify              # tsc + eslint + prettier + vitest
python -m pytest -q         # FROM THE REPO ROOT. live-API tests: pytest -m live
python -m ruff check backend   # ALSO from the repo root — see below
cd backend && python -m mypy
```

**Typecheck with `npm run typecheck` (`tsc -b`), never with `npx tsc
--noEmit`.** The root `tsconfig.json` is a *solution* config — `files: []` and
nothing but `references` — so a bare `tsc --noEmit` resolves it, finds no input
files, checks nothing and exits 0. It is not a weaker gate, it is not a gate:
it reported success over 29 broken test files and one real production bug (a
dedup guard reading a field its type never declared, so it could never fire).
Only `tsc -b` follows the project references to `tsconfig.app.json` and
`tsconfig.node.json`, which is where the code actually is.

**pytest runs from the repo root, and only the root.** The root `pytest.ini`
is what declares `testpaths = backend workflows/chinook-assistant` and puts
the example workflow's `tools`/`functions` on `sys.path`. `cd backend &&
pytest` never reads it, so it silently runs **57** fewer tests — the curated
example package's own half, which CI does run. Not `workflows/` as a whole:
that is deliberately unswept, for the collection-collision reason `pytest.ini`
spends fifteen lines on. The gap is measured by
`backend/tests/test_the_documented_collection_gap_is_the_real_one.py`, so this
number cannot go quietly stale the way it did between 2026-08-30 and
2026-09-04. `mypy` is the opposite: it reads
`backend/pyproject.toml` and wants to be run from `backend/`.

**`ruff` is neither, and getting it wrong looks like success.** CI runs
`python -m ruff check backend` **from the repo root**, and that is the spelling
to match. Run it from `backend/` and the path does not exist, so you get
`backend:1:1: E902 No such file or directory` — one error, no files linted, and
nothing that reads like "your lint is broken". Scoping to the files you touched
has the same shape: two sessions reported "ruff clean on the files I touched"
on a tree carrying 22 violations (`organisms-first-class` 47). Ruff finds its
config by walking up from each file, so the root spelling configures itself
correctly; if you must run it from `backend/`, the equivalent is
`python -m ruff check openstategraph tests`.

**Ruff's version is pinned** — `ruff==0.14.10` in `backend[dev]`, and `ci.yml`
installs no second copy. Do not install a floating one beside it: an unpinned
linter is a gate that can go red with no commit in between. Raising the pin is a
deliberate commit.

`mypy` is the backend's counterpart to `tsc`: its settings live in
`backend/pyproject.toml`, and it is scoped to `openstategraph/` — `tests/` is
deliberately outside it.

It **is** clean today, so any error it reports is yours — but do not take that
from this paragraph, which has now been wrong in both directions. It said
"clean today" while four errors stood, and then said "3 errors" for the two
hours it took `organisms-first-class` 48 to close them. The claim is pinned in
`backend/tests/test_the_type_gate_actually_runs.py` instead, which is the only
version of it that can fail.

**Both gates now have the pin prose cannot give them.**
`backend/tests/test_the_lint_gate_actually_runs.py` runs `ruff check backend`
and `backend/tests/test_the_type_gate_actually_runs.py` runs
`cd backend && python -m mypy`, both inside `pytest`, so a violation costs one
test run to notice. They exist because CI last executed on 2026-08-16 and
roughly 180 commits landed behind it (`organisms-first-class` 49) — **do not
read a green CI badge as a statement about the current tree.**

The type gate's price, measured rather than guessed: **~46s on a fresh checkout**
(and a ~310M `.mypy_cache`), **~3.2s warm** against a ~147s suite. **mypy is
pinned exactly** — `mypy==1.19.1` — for the same reason ruff is.

Run mypy from `backend/`. From the repo root it finds no config, checks nothing
and exits 0 — the mirror image of ruff's trap, and just as quiet.

TDD is the house style: tests land with (ideally before) the change.

**Docs land with the code.** CI's `docs-freshness` job fails a PR that touches
`src/` or `backend/` without touching `README.md`, `docs/` or `openwiki/`. If
the change genuinely needs no documentation, put `docs: not-needed` in any
commit message in the PR and the job passes.

## Generated artifacts — regenerate, never hand-edit

`backend/openstategraph/compile/port_specs.json` is **generated** from the
TypeScript node catalogue and committed. Change a node type, a port, a port's
cardinality or a port type, and you must run:

```bash
npm run generate:ports
```

The TypeScript side is authoritative here (the opposite direction to
Pydantic → TypeScript, which is the rule for *runtime* types): `src/nodes/**`
is where a node type is declared and where `ports` is a function of node data;
Python only reads the shape. The artifact is committed because an installed
wheel has no Node.js — a consumer running `load_workflow` cannot regenerate it.

Two gates catch a stale copy: `src/nodes/portSpecs.test.ts` compares the built
catalogue to the committed bytes inside `npm run verify`, and CI's
`generated-port-specs` job regenerates and diffs the working tree. Both name
the command in the failure. Do not edit the JSON by hand.

`docs/openapi.json` is the same arrangement in the other language: it is
generated from the FastAPI app, committed because it is the *published*
contract (`docs/api.md` is written against it), and guarded by
`backend/tests/test_openapi_contract.py` plus CI's `generated-openapi` job.
Change a route, a response model or a docstring on an endpoint, and run:

```bash
python3 scripts/generate_openapi.py
```

The docstring matters as much as the signature — it becomes the endpoint's
`description` in the published document, so a docstring that has drifted from
the code ships as a wrong contract, not as a stale comment.

`openwiki/**` is generated too, by a scheduled GitHub Actions workflow. Do not
hand-edit it to *add* documentation — fix the source and let the refresh pick
it up. Correcting a page that names a file or a directory which no longer
exists is the one exception, because a dead link is the failure the page is
there to prevent.

Every generated page carries a `FRESHNESS` block naming the commit and date it
was generated from, so a reader can tell a current page from one written weeks
ago. The generator does not write that block and a refresh deletes it: run
`python3 scripts/stamp_wiki_freshness.py` after `openwiki code --update`, and
`backend/tests/test_a_generated_wiki_page_says_when_it_was_generated.py` will
name any page you missed.

## Adding things

Everything is a registry; extending never edits `core/` — the
[extension-point table](#extension-points) below says what to register for
each kind of capability. A new workflow is a package under
`workflows/<slug>/` — `workflow.json` + `AGENTS.md` required; `tools/`,
`functions/`, `middlewares/`, `skills/`, `knowledge/`, `evals/`, `tests/` and
`data/` discovered by convention. The full contract is
[`openwiki/workflows/package-contract.md`](openwiki/workflows/package-contract.md).

## The architecture

Strict MVC with a framework-agnostic core. **`core/` imports neither React nor
JointJS** — it is plain TypeScript that could run in Node or a worker. The
arguments behind all of it are in [`CLAUDE.md`](CLAUDE.md); this is the map.

```
src/
├── design/        Design system — tokens, themes, primitives. No app logic.
├── core/          MODEL + engine. No React. No JointJS.
│   ├── kernel/        IDisposable, typed EventBus, generic Registry<T>, Result, geometry
│   ├── model/         contracts/ (interfaces) · AbstractNodeModel · WorkflowModel · ModelRegistry
│   ├── commands/      ICommand · CommandStack · node/edge commands
│   ├── validation/    ConnectionValidator (rule chain) · WorkflowValidator (diagnostics)
│   ├── serialization/ Versioned JSON + migration chain
│   ├── execution/     INodeExecutor · ExecutionEngine (topological scheduler)
│   └── providers/     ILLMProvider + Mock / Anthropic / OpenAI / Ollama adapters
├── controller/    WorkflowController façade · SelectionModel · ClipboardService
├── canvas/        VIEW (JointJS) — adapter, viewport, installable features
├── nodes/         Self-contained node modules (model + schema + ports + executor)
├── view/          VIEW (React) — shell, panels, node cards
└── app/           Composition root (Workbench) + React context + demo seed
```

### The one rule that makes it work

**The canvas is a projection of the model, never a peer.**

```
gesture → WorkflowController → ICommand → WorkflowModel → event → JointGraphAdapter → paper
```

`JointGraphAdapter` is strictly one-way (model → graph). No user gesture writes
to the graph and hopes the model catches up. Consequences:

- **Undo is generic.** It replays commands; no feature implements its own undo.
- **The graph is disposable.** Rebuilding it from the model is always correct —
  which is exactly what import does.
- **They cannot disagree.** There is no code path that mutates one without the
  other.

Drags are the interesting case: JointJS moves the element continuously while the
pointer is down (the graph leads), then `DragCommitFeature` rewinds the graph and
writes **one** `MoveNodesCommand` on release. Smooth drag, single undo entry.

### Extension points

Everything is a `Registry<T>`. Adding a capability is a registration, never an
edit to the engine.

| To add… | Register a… | Engine changes |
| --- | --- | --- |
| A node type | `INodeDefinition` + `INodeExecutor` | none |
| A tool the agent can call | `IToolExecutor` | none |
| An LLM vendor | `ILLMProvider` | none |
| A connection rule | `IConnectionRule` | none |
| A validation check | `IWorkflowRule` | none |
| A canvas behaviour | `IPaperFeature` | none |
| A bespoke card body | `NodeBody` | none |

That table is the TypeScript half. On the Python side there is a further step
that needs **no edit to this repository at all**: publish your own distribution
declaring `[project.entry-points."openstategraph.tools"]`, and your tools
register in every workflow the moment someone `pip install`s it — layered
built-in < your plugin < the workflow's own `tools/`, jailed so a broken plugin
warns and is skipped rather than taking the registry down. The exact stanza is
in [Building an atom](docs/building-an-atom.md#publishing-an-atom-as-your-own-distribution).

A node module is one file: model class, field schema, ports, executor. See
[`nodes/tools/RedditSearchNode.ts`](src/nodes/tools/RedditSearchNode.ts) — a
complete tool in ~90 lines. `nodes/index.ts` is the only file that knows the
full catalogue.

### Content-driven cards

Node bodies are real HTML (React) inside a `foreignObject`, which is what makes
the typography, form controls and Markdown tables possible. Cards therefore
size *themselves*: after layout each card measures its height and the centre of
every port row and reports both to the adapter, which writes them onto the
JointJS cell so link endpoints land exactly on the dot the user sees.

That is a feedback loop, so it is made convergent deliberately — heights round to
whole model units and identical measurements are dropped before reaching the
model. See the comment block in
[`view/nodes/NodeCard.tsx`](src/view/nodes/NodeCard.tsx).

### The compile seam

The seam that keeps the two halves independent is `ILLMProvider` +
`INodeExecutor` on the editor side, and one directional compile step on the
runtime side. The serialized document
([`core/serialization`](src/core/serialization/WorkflowSerializer.ts)) is
versioned with a migration chain and is the wire format the Python side turns
into a LangGraph `StateGraph`.

It stays one-directional on purpose: `workflow.json` → runtime, never back.
Nothing reads runtime objects into the model, expressions are a serialisable
JSON AST rather than host-language lambdas, reducers are a named enum, and
LangGraph type names never leak into `workflow.json` or `core/`. That keeps
`workflow.json` the vendor-neutral layer without paying for an orchestration
abstraction nothing else could implement.

### What had to be rebuilt

`@joint/plus` ships the editor scaffolding; the open-source core ships only the
diagram primitives. Everything in the right column here is written from scratch
in this repo.

| JointJS+ feature | Open-source replacement |
| --- | --- |
| `ui.Stencil` | [`view/palette/Palette.tsx`](src/view/palette/Palette.tsx) — registry-driven, searchable, drag + click to add |
| `ui.PaperScroller` | [`canvas/Viewport.ts`](src/canvas/Viewport.ts) — transform-based infinite canvas, zoom about the pointer |
| `ui.Navigator` | [`view/minimap/Minimap.tsx`](src/view/minimap/Minimap.tsx) — draws model rects, not a second paper |
| `ui.Selection` | [`canvas/features/SelectionFeature.ts`](src/canvas/features/SelectionFeature.ts) — click, shift-click, rubber band |
| `ui.Snaplines` | [`canvas/features/SnaplinesFeature.ts`](src/canvas/features/SnaplinesFeature.ts) — 3×3 edge/centre alignment + snapping |
| `ui.Inspector` | [`view/inspector/Inspector.tsx`](src/view/inspector/Inspector.tsx) — rendered from field schemas |
| `ui.Toolbar` | [`view/topbar/TopBar.tsx`](src/view/topbar/TopBar.tsx) |
| `ui.Keyboard` | [`canvas/features/KeyboardFeature.ts`](src/canvas/features/KeyboardFeature.ts) — one binding table, shared with the help drawer |
| `dia.CommandManager` | [`core/commands/CommandStack.ts`](src/core/commands/CommandStack.ts) — undo/redo with coalescing + transactions |
| `format.*` (PNG/SVG/JSON) | [`view/export/exportWorkflow.ts`](src/view/export/exportWorkflow.ts) |
| `layout.DirectedGraph` | [`canvas/AutoLayout.ts`](src/canvas/AutoLayout.ts) — dagre via the MPL-2.0 `@joint/layout-directed-graph` |
| HTML-in-shape | [`canvas/shapes/HtmlNode.ts`](src/canvas/shapes/HtmlNode.ts) — `foreignObject` + React portals |

### Accessibility

The **Check accessibility** button runs a live DOM audit — accessible names on
every control, labelled node cards, keyboard reachability of canvas content,
reduced-motion support, and a measured WCAG contrast ratio for body text. It
inspects what is actually rendered, so it can genuinely fail.

Every canvas action has a keyboard equivalent; the bindings table drives both
the dispatcher and the shortcuts drawer, so the documentation cannot drift.

## What happens to your pull request

**Open it from a fork; nothing here needs your trust.** CI runs on the
`pull_request` trigger, which means a fork's build gets a read-only token and
**no repository secrets** — so every check runs on your branch exactly as it
would on ours, and no check can be "unblocked" by a maintainer's credentials.
The only workflow that holds a secret is the release train, and it never runs
on a pull request.

Seven checks run, and one aggregate:

| Check | What fails it |
| --- | --- |
| `frontend` | `npm run verify` — tsc, ESLint, Prettier, Vitest |
| `backend` | ruff, mypy, and pytest under a coverage floor |
| `generated-port-specs` | `port_specs.json` was not regenerated after a node or port change (`npm run generate:ports`) |
| `generated-openapi` | `docs/openapi.json` was not regenerated after an API change (`python3 scripts/generate_openapi.py`) |
| `clean-install` | the built wheel fails in an empty venv outside the checkout |
| `docs-freshness` | `src/` or `backend/` changed and no documentation did |
| `e2e` | the Playwright suite |
| `ci-success` | any of the above — this is the one branch protection requires |

A maintainer reviews against `CLAUDE.md`, not taste: the architecture checklist
in the pull-request template is drawn from it, and "this adds a public member to
`WorkflowController`" is a blocking comment no matter how good the code is.
`.github/CODEOWNERS` requests the reviewer automatically. Paths you touch also
add labels (`frontend`, `backend`, `workflows`, `docs`, `ci`, `e2e`) — for
sorting the queue, nothing more.

### `docs: not-needed`

The `docs-freshness` check exists because documentation written a week later is
documentation written by a stranger. It fails when a pull request touches
`src/` or `backend/` and touches none of `README.md`, `docs/`, `openwiki/`.

It is a prompt, not a wall. If the change genuinely has no user-visible or
architectural surface — an internal rename, a test-only change, a dependency
pin — say so and it passes:

```bash
git commit --allow-empty -m "docs: not-needed — internal refactor only"
```

Write the reason after the dash. The check only greps for the phrase, but the
reason is what a reviewer reads, and "docs: not-needed" with nothing after it
invites the question you were trying to skip.

### Commit messages

**No prefix convention. Write a subject that says what changed and why.** The
log reads like `RC-01: generate the port table from TypeScript; the hand copy
held 10 of 38 node types`, and that is the standard — a sentence, not a
category. Nothing is parsed out of your commits: the changelog is written by a
human and the version is bumped by a release pull request, so `feat:` and
`fix:` prefixes would buy nothing today. (The one exception is the literal
string `docs: not-needed`, above, which *is* parsed.)

If that ever changes — adopting Conventional Commits and `release-please` is a
1.0 item, argued in [`docs/releasing.md`](docs/releasing.md) and
[`docs/decisions/sdk-practice.md`](docs/decisions/sdk-practice.md) — it will be
announced, and it will apply going forward rather than retroactively.

### The changelog is part of the change

If your pull request changes anything a user can observe — behaviour, a CLI
flag, a public symbol, an install footprint — add an entry to the
`## Unreleased` section at the top of `CHANGELOG.md`, in the same pull
request. Create that section if there isn't one.

Write prose, not a commit subject. The existing entries are the format: what
changed, why it changed, and what an existing user has to do about it. That
file becomes the release notes verbatim — see
[`docs/releasing.md`](docs/releasing.md) for how, and for everything a
maintainer does from there.
