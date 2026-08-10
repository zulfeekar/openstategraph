# Changelog

## 0.3.0 — unreleased

Packaging OpenStateGraph as a framework somebody else can install: an honest
install footprint, a declared public surface, and a document version that is
finally read by code. Wayfinder tickets 02–04;
`docs/decisions/framework-packaging.md` is the reasoning.

### Changed — breaking

- **The distribution is now `openstategraph`** (was `openstategraph-backend`).
  The import package is unchanged, and the old name was never on PyPI. A
  checkout installs with `pip install -e "backend[all,dev]"` — see below for
  why the extras are now required.
- **The core is four dependencies.** `langgraph`, `langchain`,
  `langchain-core`, `pydantic`. Everything else moved behind an extra:
  `[anthropic] [openai] [ollama] [deep] [sqlite] [server] [mcp]`, plus `[all]`
  and `[dev]`. Measured: **78 → 36 distributions**, 40 with one provider. A
  consumer of `load_workflow` no longer installs a web server, an MCP SDK,
  three provider SDKs and the Google GenAI SDK to run a graph in their own
  process. Anyone wanting today's behaviour installs `openstategraph[all]`.
- **A document whose schema version is newer than the build is refused**
  (`SchemaVersionError`, naming both versions) instead of being compiled
  best-effort. Nothing in this repository is affected — every committed
  document is version 2 — but a future document previously loaded silently
  into an older build and compiled into a graph that ran and answered
  differently.

### Added

- **`openstategraph.errors`** — `OpenStateGraphError` and the failures the
  loader raises. Every class also inherits the builtin it used to be
  (`PackageNotFound` is a `FileNotFoundError`, `InvalidPackageName` is a
  `ValueError`), so existing `except` clauses keep working.
- **`openstategraph.abc` exports the ladders** — `ITool`/`BaseTool`,
  `IRouter`/`BaseRouter`, `IGrader`/`BaseGrader`, the agent nodes, the
  orchestrator, `SystemPrompt`, `MiddlewareSlotTable`. The package's
  `__init__.py` was empty; the deep module paths still work.
- **`openstategraph.schema`** — `normalize_document`, `migrate_document`,
  `document_version`, `SCHEMA_VERSION`, `MIN_SUPPORTED_VERSION`, `MIGRATIONS`.
  One seam for envelope-peeling and the version policy, replacing the private
  `api.registries._document_of` that the public loader imported and the
  second, subtly different normalizer in `mcp_server`.
- **`openstategraph.__version__`**, from the installed distribution's metadata.
- **The `openstategraph` console script** (ticket 08) — `run`, `validate`,
  `graph`, `new`, `knowledge build|list`, `serve`, `mcp`. argparse only, so it
  adds nothing to the four-package core, and every command wraps a seam that
  already existed. Exit codes are fixed: `0` success, `1` run or validation
  failure, `2` usage error, `3` a required extra is missing (the message names
  the `pip install` line). `openstategraph run ./workflows/my-thing "…"` is now
  the shortest path from a package to an answer.
- **`RunResult`** — what `CompiledWorkflow.ask()` returns. It **subclasses
  `str`**, so it *is* the answer and every existing consumer is untouched
  (`.strip()`, `+`, `json.dumps`, `re.search`, `isinstance(x, str)`), while
  `.answer`, `.decisions`, `.outputs`, `.warnings` and `.attempts` remove the
  need to drop to `.graph.invoke()` with hand-seeded state to find out why an
  answer was wrong. The trade-off, and the plan to revisit it at 1.0, are
  recorded in the module docstring and `framework-packaging.md` §3.2(b).
- **`CompiledWorkflow.as_tool(name=…, description=…)`** — a whole workflow as
  one LangChain `StructuredTool`, so a team already on `create_agent` adopts
  without restructuring. Adapted at the seam, never subclassed. The workflow
  runs as its own graph and sees only the question: the same subagent
  isolation this codebase already states. There is deliberately **no**
  middleware equivalent — it would need a routing policy, and a router is
  something we already express as a document.
- **`load_workflow(..., knowledge_dir=…, trace_file=…)`** — both keyword-only,
  both defaulting to today's behaviour. `knowledge_dir` overrides the
  `<package>/knowledge` convention for knowledge shared between packages or
  living outside the repository; `trace_file` appends one JSON line per run
  (question, slug, decisions, attempts, warnings, duration, and the answer's
  **length** — never its text). An unwritable trace path warns and never fails
  the run.
- **`openstategraph.scaffold`** — the workflow/team scaffold, moved out of
  `scripts/` so it ships in the wheel. `scripts/new_workflow.py` and
  `scripts/new_team.py` keep their exact command lines and now call it, which
  is what stops `openstategraph new` from becoming a second copy that drifts.
- **`openstategraph.extensions`** — extension without forking (ticket 05). A
  third party ships their own distribution with
  `[project.entry-points."openstategraph.tools"]` (or
  `"openstategraph.knowledge_builders"`) and their tools register on install,
  with no edit to this repository. Layered as a third discovery source under
  the two that existed: **built-in < third-party < workflow-local**, so a
  plugin may replace a bundled default and a package's own `tools/` still wins
  over anything in the venv. Every entry point loads in its own jail — a
  failure logs one WARNING **naming the distribution**, lands on
  `CompiledWorkflow.warnings`, and never stops the other plugins. Nothing is
  enumerated at import time, and `OPENSTATEGRAPH_DISABLE_PLUGINS=1` switches
  the whole mechanism off for a reproducible run. There is deliberately **no**
  `openstategraph.functions` group — see `docs/building-an-atom.md`.
- **`docs/what-is-this.md`** — the positioning page. What OpenStateGraph is
  (a document format, a compiler for it, and the node semantics it emits —
  with the canvas, HTTP API and MCP layer as *optional surfaces*), what it adds
  over raw LangGraph, what it deliberately does not own, the dependency picture
  measured rather than estimated, the escape hatches, and when not to use it at
  all. The site, the README and `docs/adoption.md` no longer imply the checkout
  is the only path.
- **`docs/stability.md`** — the three tiers, what is deliberately not public,
  and the deprecation policy. Pre-1.0, a breaking change bumps the **minor**,
  never the patch.
- **A release pipeline with a gate that cannot be waved through.**
  `scripts/clean_install_proof.sh` builds the wheel and sdist, runs `twine
  check`, installs into an **empty venv outside the checkout**, and drives the
  CLI and `load_workflow` with `cwd` outside the repository and `PYTHONPATH`
  empty. It runs on every pull request (`clean-install` in CI) and gates
  publication: `.github/workflows/release.yml` publishes on a `v*` tag —
  pre-release tags to TestPyPI, final tags to PyPI — and `publish` **needs**
  the proof. Required repository secrets: `PYPI_API_TOKEN`, and
  `TEST_PYPI_API_TOKEN` for pre-releases.
- **`py.typed`** (PEP 561), `backend/LICENSE`, `backend/README.md`,
  classifiers, project URLs and a `[build-system]` table — the wheel had none
  of these.

### Fixed

- **Four modules resolved the workflows root inside the virtualenv once
  installed.** Each computed `Path(__file__).resolve().parents[N] /
  "workflows"`, which is the repository only while the file sits in a
  checkout; from a wheel it is `<venv>/lib/python3.13/workflows`. The symptom
  was not a crash — `platform_list_workflows` answered **"No workflows exist
  yet."** with the adopter's packages in their project directory, every
  `tool.sql-*` database path was refused, and an un-configured
  `tool.email-send` dry run wrote the user's report into their virtualenv. New
  `openstategraph.workflows_root` answers the question once, **per call**:
  `OPENSTATEGRAPH_WORKFLOWS_ROOT`, else the checkout (so every in-tree
  behaviour is byte-identical), else `./workflows` — which is where
  `openstategraph new` already writes. Found by the clean-venv proof, which no
  amount of green test suite could have replaced.
- **`WorkflowStore(root="…")` with a string root** raised `TypeError:
  unsupported operand type(s) for /: 'str' and 'str'` one call later, in
  another module. The root is coerced to a `Path`.
- **`settings.checkpointer: "sqlite"` degraded silently to in-memory** in every
  install that existed, because `langgraph-checkpoint-sqlite` was imported but
  never declared and is not a transitive of `langgraph`. A user who asked for
  durable threads got a log line and would have found out when a restart ate a
  conversation. The dependency is now `[sqlite]` and the fallback says so, in
  as many words, naming the install command. Same fix for
  `OPENSTATEGRAPH_MEMORY_PATH`.
- **A missing optional dependency now names its extra.** `deepagents is
  required for tier='deep' agent nodes — pip install 'openstategraph[deep]'`,
  rather than a bare `ModuleNotFoundError` an adopter has to map back to one of
  seven extras themselves.

### Internal

- `__all__` removed from every module under `openstategraph/api/`, which is
  Tier 3: in Python `__all__` reads as "this is the public surface", and those
  lists were the names each module hands its own siblings.
- New guards, run on every PR: a distribution-metadata test (the core is
  exactly four, each extracted name is in the extra that claims it), a
  signature snapshot of the public API, and a check that no Tier 1 module
  imports a private name out of `openstategraph.api`.

## 0.2.0 — 2026-08-09

The first release under the project's own name, plus the work that made the
conversational surface actually usable across workflow boundaries.

### Changed — breaking

- **Renamed Dyflow → OpenStateGraph.** The Python package is now
  `openstategraph` (import paths, `uvicorn openstategraph.api.main:app`), and
  the backend environment variables are `OPENSTATEGRAPH_OLLAMA_MODEL` and
  `OPENSTATEGRAPH_LOG_LEVEL`. Any existing
  `.env` or shell profile carrying the old names must be updated — the old
  spellings are not read as fallbacks. `workflow.json` is unaffected: the
  serialized format did not change.

### Added

- **Memory.** Conversation memory generalised beyond a single workflow, plus
  three-scope long-term memory (user / workflow / thread) over the LangGraph
  Store, with prebuilt save and search tools.
- **The conversation crosses the subgraph boundary.** A routed child subgraph
  now receives the parent thread's dialogue instead of starting amnesiac, and a
  `PackageAssets` loader gives a child its *full* package rather than a bare
  `workflow.json`.
- **Live flow view in `/chat`.** The compiled graph renders beside the
  conversation with active nodes lit during a run; the layout is a fixed
  420px chat column that stacks under 900px.
- **OpenWiki.** 13 generated concept pages as a single source of truth the
  concierge can read, refreshed by a weekly PR-on-change workflow.
- **Playwright smoke suite** driving real gestures against the canvas, wired
  into CI alongside the unit suites.

### Improved

- **Concierge and Workflow Architect** routing sharpened: build requests and
  how-does-it-work questions no longer collide, and tool-call chatter is never
  presented as the answer.
- **`api/main.py` split** (973 → 570 lines) into `schemas`, `model_resolution`,
  `registries` and `streaming`; runtime collaborators are passed as a
  `RuntimeServices` parameter object rather than threaded individually.
- **Coverage ratchets in CI.** Frontend statements 58% → 73.5% (367 tests);
  backend measured at 91%. Both floors are enforced, so a PR cannot lower them
  to go green.
- Palette level labels, and `scripts/dev.sh stop` now escalates past a
  graceful-shutdown hang instead of waiting forever.

### Removed

- `.scratch/` and `HANDOVER.md` are no longer tracked — internal planning stays
  local and out of the published repository.

## 0.1.0 — 2026-08-08

First coherent release: a visual workflow builder that compiles to LangGraph.

- **Editor**: JointJS-core canvas (registry-driven palette, undo/redo,
  snaplines, minimap, auto-arrange in both flow directions), schema-driven
  inspector with locked prompt sections, compiled-graph Mermaid overlay,
  execution trace tree with JSON export.
- **Runtime**: `workflow.json` → LangGraph `StateGraph` compiler (routers,
  graders with rubric rows, supervisor fan-out with worker archetypes, HITL
  approval, subgraph + Team nodes, per-node retry/timeout), agent tiers
  (ReAct / deep / custom) over a middleware slot table.
- **Memory**: long-term Store namespaced per user with prebuilt save/search
  tools, durable sqlite checkpointing opt-in, procedural skills per package.
- **Customer surface**: `/chat` with workflow selector, an Auto concierge
  gateway (read-only platform introspection + keyless web search), and a
  Workflow Architect that composes compile-validated workflows from a
  description — saving stays a human click.
- **Workflows shipped**: Chinook NL-to-SQL, video-game analytics, open-API
  explorer, code workshop (+review), research team, data-analyst team.
- **Quality**: 505 pytest + 339 Vitest, strict tsc, ruff + ESLint + Prettier,
  CI, supervised dev stack (`scripts/dev.sh`).
