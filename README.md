# OpenStateGraph — AI Workflow Builder

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.3.0%20unreleased-informational.svg)](CHANGELOG.md)

A visual AI-agent workflow editor built on the **open-source** JointJS core
(`@joint/core`, MPL-2.0), reproducing the JointJS+ *AI Workflow Builder* demo
without any commercial packages.

### We compile; we do not interpret

The closest-looking tools — Langflow, Flowise, n8n, Dify — own their execution
engine: a flow runs inside their platform, through their runtime, or it does not
run at all. OpenStateGraph is a **compiler with a single target**. A canvas is
`workflow.json`, and `workflow.json` compiles to a plain LangGraph `StateGraph`.

Two consequences follow, and they are the whole point:

- **A flow is a file in git.** `workflow.json`, plus the package's own `tools/`,
  `functions/` and `tests/` — reviewable in a pull request, diffable, not a blob
  in someone's database.
- **The output runs without the editor.** The compiled graph is an ordinary
  Python object: import it from a script, exercise it with `pytest`, deploy it
  wherever Python runs. Delete this repository and your workflow still runs.

We also inherit rather than reimplement: checkpointing, time travel,
`interrupt()` for human-in-the-loop, `Send` fan-out, reducer merging and token
streaming are LangGraph's, not ours. **The compiler is not portable; the output
is.**

### Two ways in, and the checkout is only one of them

This repository is the editor **and** the framework, and you do not need the
first to use the second. From 0.3.0 the backend is a proper distribution — one
wheel, a four-package core, seven named extras, `py.typed`, and an
`openstategraph` console script:

```bash
pip install "openstategraph[ollama]"          # ← after the first PyPI release
openstategraph run ./my-workflow "How many invoices are there?"
```

**That upload has not happened yet**, and this file will not print a command
that silently fails, so until it does you install the identical artifact from a
checkout: `pip install -e "backend[ollama]"`, or build the wheel with `python3
-m build backend`. CI's `clean-install` job installs that wheel into an empty
virtualenv **outside** this repository and runs a workflow there, so the path is
verified rather than assumed. Measured footprint: **36 distributions** for the
core, 38 with a provider.

New here and deciding? [**What this is**](docs/what-is-this.md) states plainly
what the framework owns, what it deliberately does not, and when not to use it.

Phase 1 (this repo) is the editor: canvas, design system, MVC engine, and a
pluggable provider layer that already runs workflows end to end. Phase 2 —
now live alongside phase 1 — is the Python LangGraph/LangChain backend that
actually compiles and runs a canvas-authored workflow, persists it to real
files, and streams a run back to the chat panel.

### Prerequisites

- Node 20+ (developed against Node 22)
- Python 3.11+ (developed against 3.12/3.13)
- No local model runtime needed — the backend defaults to **Ollama cloud**
  (an Ollama account, not a local `ollama serve`; see the "Ollama means
  Ollama cloud" rule in `CLAUDE.md`). A local Ollama daemon only matters if
  you pick the **Ollama** provider from the editor's canvas preview.

Two processes, two languages, run separately (ticket 12: no single unified
dev command exists — a `Vite` process and a `uvicorn` process have little in
common to unify, and a Makefile wrapping "run these two things" would be one
more thing to keep in sync with the two `npm`/`pip` scripts below):

```bash
npm install
scripts/dev.sh     # supervised backend + editor; scripts/dev.sh stop; scripts/status.sh

# — or by hand —
# Terminal 1 — the editor
npm run dev        # http://localhost:5273

# Terminal 2 — the runtime (optional: the editor works read-only without it,
# but Chat and saving workflows both need it)
cd backend
pip install -e .
PYTHONPATH=backend:workflows/chinook-nl-to-sql uvicorn openstategraph.api.main:app --port 8000 --app-dir backend

npm run build      # tsc -b && vite build
npm run typecheck
```

### Or skip the editor entirely — the CLI

A workflow package is a folder. Running one needs neither the canvas nor the
server:

```bash
pip install -e "backend[ollama]"      # or the built wheel, from anywhere

openstategraph run ./workflows/chinook-nl-to-sql "How many invoices are there?"
openstategraph validate ./workflows/chinook-nl-to-sql   # exit 1 if it will not compile
openstategraph graph ./workflows/chinook-nl-to-sql      # Mermaid text, no network call
openstategraph new my-flow                              # scaffold ./workflows/my-flow
```

Also `knowledge build|list`, `serve` and `mcp`. `--json` on `run` prints the
whole result rather than the answer alone, and the exit codes are fixed (`0`
ok, `1` failure, `2` usage, `3` a missing extra) so `validate` works as a CI
gate. The same thing from Python is `load_workflow("./workflows/my-thing")` —
see [Using OpenStateGraph in your project](docs/adoption.md).

Opens on a seeded demo that **runs with no credentials** on the canvas
preview — the default model there is `Mock · Offline`, a deterministic
simulator. The real backend, once running, defaults to **Ollama cloud** with
zero configuration (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY` override it if set —
see `resolve_model` in `backend/openstategraph/api/main.py`).

### Example workflows

The repository ships exactly **two** visible examples, both evaluated against
**one** sample database — `workflows/chinook-nl-to-sql/data/Chinook_Sqlite.sqlite`,
the standard Chinook music store. One database is the single source of truth:
every figure any example produces can be checked against the same file.

- **`chinook-nl-to-sql`** — the focused example. Natural language in, one
  SQL answer out: an agent bound to three Chinook-specific tools
  (list tables → schema → read-only query).
- **`page-analytics`** ("Store Analytics") — the comprehensive example. It
  exercises every generic node type at once: intent routing with a
  conversation fallback, a supervisor with three worker archetypes on the
  generic SQL Explorer bus (one also holding web search), report formatting,
  a grader revise loop, human approval, an email dispatcher (dry-run without
  SMTP), a quick-metric agent, a conversational branch for follow-ups, a
  mounted Team (`chinook-metrics-team`) on the `database_deep_dive` branch,
  and the focused example itself mounted as a subgraph on `sql_specialist`.

Two hidden infrastructure workflows (`concierge`, `workflow-architect`) power
the chat gateway and the build-me-a-workflow flow; `openstategraph new <slug>`
(or `scripts/new_workflow.py` / `scripts/new_team.py`, which call the same
code) scaffolds your own packages.

### Environment variables

None are required. Copy [`.env.example`](.env.example) to `.env` to set any
of these for the backend process:

| Variable | Effect |
| --- | --- |
| `ANTHROPIC_API_KEY` | backend model resolution prefers Anthropic when set |
| `OPENAI_API_KEY` | checked next, if Anthropic's key is absent |
| `OPENSTATEGRAPH_OLLAMA_MODEL` | overrides the Ollama cloud model id (default `ollama:gpt-oss:120b-cloud`) |
| `OPENSTATEGRAPH_LOG_LEVEL` | backend log verbosity — `DEBUG`/`INFO`/`WARNING`/`ERROR` (default `INFO`) |

The canvas-preview providers (Anthropic/OpenAI/Ollama keys entered in the
credentials dialog) are separate — see **Providers** below. The canonical
explanation of the *two* model paths and which credential reaches which is
[docs/getting-started.md §3](docs/getting-started.md#3-models-and-credentials);
this table is the quick reference.

### Tests

```bash
npm test                                  # Vitest — frontend unit tests
npx tsc -b --noEmit                       # typecheck only, no build output
cd backend && pip install -e . && pytest  # backend unit tests
```

Architecture is documented in depth in [`CLAUDE.md`](CLAUDE.md); this README
covers running the app, not the design rules.

---

## Docker

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
editor, `/chat` and the API from a single origin on port 8000 — the frontend
calls `http://localhost:8000` absolutely, so map that port as-is.
`./workflows` is bind-mounted, so workflows saved in the container land in the
repo.

**One worker, deliberately.** The human-in-the-loop checkpointer in
`api/main.py` is an in-process `InMemorySaver`, so a second worker gets a
second, empty copy and a `/api/runs/resume` routed to it cannot find its run.
Scaling out needs a persisted checkpointer (SQLite for one host, Postgres
beyond) wired into `main.py` first. `uvicorn --reload` is single-process for
its own reasons too — it and `--workers N` are mutually exclusive.

Rationale for each choice is commented inline in `Dockerfile`,
`docker-compose.yml`, `start` and `scripts/dev.sh`.

---

## What had to be rebuilt

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

---

## Architecture

Strict MVC with a framework-agnostic core. **`core/` imports neither React nor
JointJS** — it is plain TypeScript that could run in Node or a worker.

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

---

## Providers

| Provider | Credentials | Notes |
| --- | --- | --- |
| **Mock · Offline** | none | Default. Deterministic two-phase agent loop (requests a tool, then answers from its result) so the real execution path is exercised. |
| **Ollama** | none | Discovers locally pulled models from `/api/tags`. Start Ollama with `OLLAMA_ORIGINS="*"` so the browser can reach it. |
| **Anthropic** | API key | Official SDK, lazy-loaded. Adaptive thinking; drops to `thinking: disabled` below a 4096-token budget (`max_tokens` caps thinking *and* answer together) with the documented no-thinking guardrails applied. |
| **OpenAI** | API key | Official SDK, lazy-loaded. Model list refreshed from the account. |

Both vendor SDKs are dynamic imports, so they are separate chunks and cost
nothing for users who stay on Mock or Ollama.

> **Key storage:** keys are kept in this browser's `localStorage` and sent
> directly from the page to the provider. That is an acceptable trade for a
> local-first editor and it is stated plainly in the credentials dialog. Use a
> scoped, revocable key. Phase 2 removes browser-side keys entirely.

---

## Accessibility

The **Check accessibility** button runs a live DOM audit — accessible names on
every control, labelled node cards, keyboard reachability of canvas content,
reduced-motion support, and a measured WCAG contrast ratio for body text. It
inspects what is actually rendered, so it can genuinely fail.

Every canvas action has a keyboard equivalent; the bindings table drives both
the dispatcher and the shortcuts drawer, so the documentation cannot drift.

---

## Known limits

- **PNG export** rasterises the SVG through a canvas. Chromium does this with
  `foreignObject` content; WebKit historically refuses. The failure is reported
  with a message pointing at SVG export, which always works.
- **SVG export** inlines the app's stylesheets and resolved theme variables but
  drops `@font-face` rules, so an external viewer falls back to a system font.
- **Reddit tool** tries the live endpoint first and falls back to labelled
  sample data — Reddit rejects browser-origin requests. The fallback is marked
  in both the payload and the run log rather than passed off as live.
- **Containers do not auto-fit** their children, by design: an auto-growing
  frame changes geometry behind the user's back, and geometry belongs to the
  model. Frames are resized by hand via the corner grip.
- **Execution is sequential**, so a run is legible on the canvas. Parallelising
  independent branches is a change to `ExecutionEngine.run` alone.

---

## The compile seam

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

**Docs note:** LangGraph and LangChain facts in this repo come from the
`docs-langchain` MCP server (<https://docs.langchain.com/mcp>), never from
memory.

---

## Contributing

Issues and pull requests are welcome. The house style is TDD, and `core/` is
pure TypeScript with no excuse for untested logic.

- [**docs/**](docs/README.md) — the documentation set, indexed by intent:
  [what this is](docs/what-is-this.md) (deciding), [getting
  started](docs/getting-started.md) (first run), [using it in your
  project](docs/adoption.md) (the three consumption modes, the CLI,
  `load_workflow`), [the stability contract](docs/stability.md) (what can be
  taken away), [the MCP layer](docs/mcp.md) (your own LLM composes the graph),
  the seven [patterns](docs/patterns.md), [building an
  atom](docs/building-an-atom.md) (a node, both halves, end to end) and the
  [ports and edges](docs/ports-and-edges.md) reference
- [**CONTRIBUTING.md**](CONTRIBUTING.md) — setup, the test gate, and how to add
  a node type, tool, provider or workflow package
- [**CLAUDE.md**](CLAUDE.md) — the architecture contract. Read
  "Non-negotiables" before designing anything; most rejected proposals are
  rejected by a rule already written there
- [**CODE_OF_CONDUCT.md**](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1
- [**SECURITY.md**](SECURITY.md) — a local-first tool with no authentication;
  read the documented trade-offs before exposing it to anything
- [**CHANGELOG.md**](CHANGELOG.md) — what changed, per release
- [**THIRD_PARTY_NOTICES.md**](THIRD_PARTY_NOTICES.md) — MPL-2.0, OFL-1.1 and
  redistributed-data attributions

Every pull request runs the same two commands CI does:

```bash
npm run verify      # tsc + eslint + prettier + vitest
python -m pytest    # backend + workflow tests (live-API tests are opt-in: -m live)
```

## License

MIT — see [`LICENSE`](LICENSE). Third-party components keep their own licences;
the ones with live obligations (JointJS under MPL-2.0, the Inter typeface under
OFL-1.1, and the redistributed Chinook sample database under MIT) are recorded
in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
