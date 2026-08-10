# Changelog

## 0.3.0 — unreleased

Packaging OpenStateGraph as a framework somebody else can install: an honest
install footprint, a declared public surface, and a document version that is
finally read by code. Wayfinder tickets 02–04;
`docs/decisions/framework-packaging.md` is the reasoning.

### Changed — breaking

- **`load_workflow(checkpointer=…, store=…)` now declare the types they always
  required.** `checkpointer` is `BaseCheckpointSaver[Any] | None` and `store`
  is `BaseStore | None` instead of `Any`; `CompiledWorkflow.as_tool()` returns
  `BaseTool` instead of `Any`. No runtime behaviour changed — the same objects
  were always the only ones that worked — but a caller who was passing
  something else now hears about it from their own type checker rather than
  from a stack trace inside LangGraph. Both names are imported under
  `TYPE_CHECKING`, so `import openstategraph` stays free of langgraph.
  `model` stays `Any` on purpose: a provider string and a built model object
  are both correct.
- **A paused approval now survives a restart, and persists by default.** The
  human-in-the-loop checkpointer was one module-level `InMemorySaver` in
  `api/main.py`; a `human.approval` pause therefore died with the process, and
  the dev stack restarts on every file save. It is now
  `WorkflowServices.checkpointer` — the same assembly point that already owns
  the store and the registries, so HTTP, MCP and `load_workflow` share one
  saver instead of three wirings — defaulting to a SQLite database at
  `<workflows root>/.openstategraph/checkpoints.sqlite`. Startup states which
  one it got, in one line: `approvals persist at …`, or `approvals are
  in-memory and will NOT survive a restart`. Set
  `OPENSTATEGRAPH_CHECKPOINT_PATH` to move the file, or to `memory` to opt out
  of durability deliberately. `load_workflow(checkpointer=…)` still outranks
  everything, and a package's own `settings.checkpointer: "sqlite"` still takes
  its per-workflow file. Listed as breaking because threads are now persistent
  identities: a client reusing a fixed literal `thread_id` resumes the old
  conversation rather than starting a new one.
- **`langgraph-checkpoint-sqlite` is part of the `[server]` extra.** The
  server's default is now sqlite, and a default that needs an undeclared extra
  is a default that degrades for everybody. It did *not* move into the core
  four — it drags `aiosqlite` and the `sqlite-vec` binary wheel, which a
  `load_workflow` consumer who never pauses a run should not pay for. An
  install missing it still degrades **loudly**, naming the install line.
- **The MCP `run_workflow` tool compiles with that checkpointer too.** A
  document containing `human.approval` used to raise at compile time and return
  a stack-trace-shaped error; it now pauses properly and the tool reports the
  pause with the durable `thread_id` to resume through `/api/runs/resume`. A
  resume *tool* over MCP is still not built.
- **The worker ceiling is still one — for a different, smaller reason.**
  Checked against the package rather than assumed: `SqliteSaver` documents
  itself as *"meant for lightweight, synchronous use cases (demos and small
  projects) and does not scale to multiple threads"*, and its only write
  serialisation is a `threading.Lock` held per instance, which two OS processes
  do not share. So a second worker can now *see* the first's threads but would
  race its writes with no coordination. `Dockerfile`, `scripts/dev.sh`,
  `README.md`, `docs/adoption.md`, `docs/decisions/memory-architecture.md` and
  `docs/decisions/mcp-layer.md` all said "in-process state"; all now say this.
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

### Changed

- **Pointing OpenStateGraph at a directory no longer writes into it**
  (scale-and-adopt ticket 03). READ location and WRITE location are now
  separate questions with separate answers: `openstategraph.workflows_root`
  and the new `openstategraph.state_dir`. Inside this checkout **nothing
  moves** — state is still `<workflows root>/.openstategraph`, which is where a
  developer expects it and where `.gitignore` already covers it. Installed and
  pointed at somebody else's folder, state goes to the platform's per-user
  state directory instead (XDG `$XDG_STATE_HOME`/`~/.local/state` on Linux,
  `~/Library/Application Support` on macOS, `%LOCALAPPDATA%` on Windows),
  keyed per project so two projects never share a thread namespace.
  `OPENSTATEGRAPH_STATE_DIR` names it outright;
  `OPENSTATEGRAPH_CHECKPOINT_PATH` stays authoritative above both. A read-only
  workflows root now lists, compiles and runs, and when a write genuinely
  cannot be made durability degrades loudly rather than the process failing.
  Two writes moved with it: the email tool's dry-run outbox
  (`<workflows root>/_outbox` → `<state dir>/outbox` — a `.eml` is diagnostic
  output, not content the user authored, and it was not gitignored), and a
  package's own `settings.checkpointer: "sqlite"` file, which was `./.dev/`
  **relative to the working directory** and so created `~/.dev/` for anyone who
  ran a workflow from their home directory.

### Added

- **Named templates, shipped inside the wheel** (scale-and-adopt ticket 04). A
  `pip install` user started in an empty folder with nothing to imitate: the
  two example workflows live in this repository and were never in the package.
  Three starting points now ship as ordinary package data under
  `openstategraph/templates/`, and `openstategraph new --list-templates` prints
  them:
  - **`minimal`** — input → agent → output. **Still the default**, deliberately:
    a stranger's first run must cost one model call and contain nothing that
    can reject the answer.
  - **`routed-qa`** — input → router → agent → grader → output, with a second
    branch that skips the grader. The shape most assistants end up with, and
    the one that teaches branches, the revise loop and typed feedback ports.
  - **`team`** — the existing supervisor + worker + grader package, now reached
    as `--template team`.

  They are **data files, not Python builders**: a template is a `workflow.json`,
  and the person about to own one should be able to read it first.
  `openstategraph new my-flow --template routed-qa` works from an empty
  directory on a machine that never cloned this repository — the wheel-contents
  check in `scripts/clean_install_proof.sh` asserts the files are in the
  artifact, and the proof scaffolds, validates and compiles **every** template
  from the installed wheel. Each scaffolded package now gets an `AGENTS.md`
  written for its own shape: what was created, and the obvious next step.

  A template is a **scaffold input** — it produces a document and stops
  existing. It is not a node type beside Team and Workflow, and no saved
  document records which template made it.

  **`openstategraph new --team` is deprecated but still works**, as an alias
  for `--template team`; it prints one line naming its replacement. The command
  line follows the Tier 1 policy, so it is not being removed in this release.
  An unknown `--template` exits **2** with the valid names — a typo in a flag
  is a usage error, and CI must be able to tell it from a failed run.
- **`GET /api/templates`, and the editor's New Workflow picker uses it.**
  "Start from" in the Workflows panel offers `Blank canvas` plus the same three
  templates, rendered by the backend from the same catalogue `openstategraph
  new` reads — one list, not two. Blank stays the editor's default, because a
  canvas may legitimately be empty while a scaffolded *package* must run.
- **`Workflows` — a catalogue, so a directory is named once** (scale-and-adopt
  ticket 02). `load_workflow(path)` is the right shape for one package and the
  wrong shape for twenty: the root is restated at every call site, and there is
  no way to ask what is in a directory without compiling it.
  `Workflows(root, **defaults)` has exactly four members — `.root`, `.list()`,
  `.published()` and `.load(slug)` — and `.load()` returns the same
  `CompiledWorkflow` through the same `load_workflow`, so there is no second
  wiring path. **Listing never compiles**: it reads one `workflow.json` per
  package through the store's existing traversal, imports neither LangGraph nor
  LangChain, and needs no API key. A package whose `workflow.json` will not
  parse comes back as a **row carrying `error`** rather than an omission or an
  exception — the HTTP listing still omits it, because a customer surface must
  not show rubble, but "what have I got" is exactly the question you ask when
  something is broken. `.published()` mirrors `?surface=chat`.
  `load_workflow(path)` is unchanged.
- **`workflows_dir:` in `openstategraph.yaml`.** The workflows root now
  resolves through all four layers of the project-wide precedence rule —
  convention `./workflows` < config file < `OPENSTATEGRAPH_WORKFLOWS_ROOT` <
  the explicit argument — with each adjacent pair pinned by its own test. A
  relative value is resolved against the **config file**, never the working
  directory, so one committed line cannot mean a different directory per
  developer. There is deliberately no module-level setter.

- **The wheel carries the canvas** (scale-and-adopt ticket 01). We called this
  a *visual* workflow builder and shipped 276 KiB of Python with no UI: the
  canvas existed only for someone who cloned the repository or ran Docker.
  `npm run build`'s output now ships as package data through a hatchling build
  hook (`backend/hatch_build.py`), so `pip install "openstategraph[server]" &&
  openstategraph serve` opens the real product on a machine that has never seen
  the repository — editor at `/`, customer chat at `/chat`, API under `/api`,
  one process, one origin, one workflows directory. Sourcemaps are excluded;
  the measured cost is 2.7 MB of a 2.9 MB wheel (1,553 KiB editor + 952 KiB of
  Mermaid for the `/chat` flow view) against the ~72 MB a `[server]` install
  already puts in `site-packages`, which is why it rides in the main wheel
  rather than a separate `openstategraph-editor` distribution. A build with no
  editor anywhere now **fails** instead of quietly producing a canvas-less
  "visual builder"; editable installs stay exempt, so the contributor path
  needs no Node.js.
- **`openstategraph serve` grew the port behaviour a first five minutes needs.**
  No flag takes 8000, or the **next free port** if 8000 is busy — running two
  copies is a normal thing to want and `Address already in use` is not an
  answer to it. `--port N` means exactly N and fails with the way out (`try
  --port 0`). `--port 0` lets the OS choose. In every case the URLs it actually
  landed on — editor, chat, health — are the last thing printed before the
  server's own log, flushed, so a script or a supervisor can read them.
  `--host` defaults to `127.0.0.1` and the help text says why it is not
  `0.0.0.0`; `--open` launches a browser and is off by default.
- **A source checkout that never ran `npm run build` gets a sentence, not a
  404.** `serve` there serves a page at `/` (503) naming the two ways out. A
  bare 404 is indistinguishable from a broken install, which is the failure
  this replaces.
- **The clean-install proof now proves the product, not just the compiler.**
  After installing the wheel in an empty venv outside the checkout, it starts
  `openstategraph serve --port 0`, waits for readiness and asserts `/` is the
  editor SPA, `/chat` is the chat page, `/api/workflows` is JSON and
  `/chat/mermaid.js` is served from the wheel. Without it the canvas could
  silently stop shipping and everything else would stay green.

- **`openstategraph.extensions.reset_entry_point_cache()`**, and with it a
  process-lifetime cache covering **all three** entry-point groups rather than
  one. Entry-point discovery re-walks every installed distribution's metadata
  on every call — about 12 ms per group on a development checkout. That cost
  was previously memoised for tools only, at a call site in `api/registries.py`,
  leaving `entry_point_knowledge_builders` (11.99 ms → 0.0005 ms) and
  `entry_point_providers` (11.84 ms → 0.0005 ms) paying it in full;
  `providers.load_provider_catalogue()` went 12.07 ms → 0.004 ms end to end.
  The cache now lives in `extensions`, which owns the mechanism, and importing
  that module is still free of any `sys.path` scan. Only a `pip install` can
  change the answer, and that means a restart — except in a test suite, which
  is what the new public reset is for. `api.registries.reset_process_tool_layer`
  keeps working and now clears every group.
- **CI runs the Python versions the package advertises.** The classifiers claim
  3.11, 3.12 and 3.13; CI ran 3.12 and only 3.12, so two thirds of the promise
  on the PyPI page had never executed a line of this code. The backend job is
  now a matrix over the floor and the ceiling of that claim (3.11 and 3.13),
  each leg running the full suite and the coverage ratchet, with ruff and mypy
  on the floor leg — where `target-version` and `python_version` are both pinned
  anyway. `backend/tests/test_python_support.py` parses both `pyproject.toml`
  and the workflow file and fails if the claim and the matrix disagree in either
  direction, so widening one without the other cannot merge.
- **A tool an installed distribution ships now appears in the editor palette**
  (register PK-06). `pip install`-ing a plugin has made a tool *bindable* since
  0.3.0's entry-point work, but nothing put it in the palette, so nobody could
  wire the thing they had just installed — "extend without forking" was half a
  promise. `GET /api/workflows/{slug}/capabilities` now also reports
  `plugin_tools` (name, node type, description, argument schema, the
  distribution that shipped it, and the card fields the tool declares) sourced
  from the same cached registry layer `build_tool_registry` binds, so the
  palette can never offer a tool the runtime lacks. A plugin's card is
  app-scoped — available in every workflow, distinct from the "This workflow"
  section — and a plugin that replaces a built-in says so on the card and in a
  warning.
- **`openstategraph.abc.ToolField`** — the declaration a plugin author writes to
  get controls on their tool's card (`node_fields` on `BaseTool`), read by
  `configure()` at runtime. One declaration, two consumers, no hand-mirrored
  type across the boundary. A third party cannot add a TypeScript file to this
  repository, so this is how they get a configurable card.
- **`warnings` on the capabilities response** — the half-authored error. A tool
  that exists in Python but has no editor card (no node definition, no plugin
  declaration) is bindable and invisible, and used to produce no message
  anywhere; it is now named, with both ways to fix it, and surfaced in the
  palette. `extensions.Discovered` gained a `sources` field
  (`node_type -> distribution`) so a capability can name who shipped it; the
  loader already computed it.
- **A type gate for the backend: `mypy`, configured in `backend/pyproject.toml`
  and run in CI beside `ruff`.** Chosen over pyright because the backend CI job
  is Python-only and pyright needs Node.js in it. Nine strictness flags are on
  and clean — including `disallow_untyped_defs`, `disallow_any_generics` and
  `warn_return_any` — which is what makes the checks reach inside function
  bodies at all. It caught 35 real typing defects on the first run, among them
  a `list[str]` parameter on `Router` that narrowed its base's
  `list[str | dict | Branch]` (a Liskov violation an adopter passing `Branch`
  objects would have hit), and a table of four ABCs whose only inferred
  supertype was `ABCMeta`, so reading `.PREAMBLE` off it was unchecked.
  `warn_unused_ignores` is deliberately off: one ignore's necessity depends on
  whether the `[mcp]` extra is installed, and a gate that passes in CI and
  fails in a lean checkout is worse than the ignore it polices.
- **`load_workflow` and `CompiledWorkflow` are context managers**, and
  `CompiledWorkflow.close()` releases the sqlite handles the load opened. A
  script that loads one workflow and exits never needed it; a service that
  loads them on demand did.
- **The provider set is open: `openstategraph.providers` + the
  `openstategraph.providers` entry point group.** Adding a vendor was three
  literal lists that had to be edited together and never were — an
  `if os.getenv(...)` chain in `resolve_model` (so a fourth vendor could never
  be the default), a four-name `ACCEPTED_CREDENTIAL_KEYS` frozenset (so its key
  was *silently dropped* from a run request), and a five-prefix
  `PROVIDER_EXTRAS` dict (so its missing package produced no install hint).
  All three now derive from one `ProviderCatalogue`. A third party registers a
  `ProviderSpec` with a `pyproject.toml` stanza and no fork; the bundled three
  go through the identical `register()` with no privileged field, so anything a
  built-in can do a plugin can do. Precedence is
  built-in < installed plugin < config file.
- **`openstategraph.yaml` — a versioned config file, secrets excluded by
  construction.** Declares which providers exist, their models and the default;
  schema-validated with pydantic, `extra="forbid"` so a typo is refused rather
  than ignored, and errors that name the file and the field or line. It can
  never hold a credential: a key-shaped *field name* and a key-shaped *value*
  are both rejected, each with a message pointing at `.env`. It may name the
  environment variable holding a key, which is the useful half without the
  secret. YAML because PyYAML already ships transitively with `langchain-core`
  — so it costs no distribution — and because a file meant to be edited by a
  human or a coding agent needs comments; `openstategraph.json` also works.
  Precedence, documented and tested pair by pair:
  `config file < environment < workflow settings.model < node's own model <
  caller's model= argument`.
- **`errors.MissingProviderKey`** — naming a provider whose key is unset now
  fails at resolution with the exact fix (`set ANTHROPIC_API_KEY in .env — see
  .env.example`) instead of the vendor SDK's own error, which names its own
  variable and knows nothing about this project's `.env.example`.
- **`openstategraph providers` and `openstategraph env-example` CLI
  commands** — what is registered and whether it is configured (names only,
  never values), and the generated provider block of `.env.example`. That block
  is produced from the registry, and a test asserts the committed file matches
  it exactly, so a newly registered vendor documents itself.
- **`load_workflow(..., store=, tools=, functions=, middleware=)`** — the
  remaining collaborators are now the caller's to supply, closing the
  asymmetry where `checkpointer` was injectable but its sibling the long-term
  memory `Store` was built internally from the environment. `store` is the
  object the prebuilt memory tools read and write; `tools`/`functions`/
  `middleware` are explicit mappings keyed exactly as a document names them
  (`{"tool.my-thing": instance}`, `{"function.my_fn": callable}`,
  `{"summarization": middleware}`). **Precedence: built-in < installed plugin
  < the package's own files < these arguments** — an explicit mapping is the
  most specific source, and a collision with a discovered capability is a
  deliberate substitution, so it is never reported on `.warnings`. All four
  are keyword-only with `None` defaults, and `None` means exactly what it
  meant before the parameter existed. `docs/adoption.md` has the table.
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

- **The editor bundle called `http://localhost:8000` absolutely**
  (`src/core/runtime/RuntimeClient.ts`, `WorkflowFileClient.ts`, two view
  components). True of exactly one deployment — Docker published on port 8000
  — and false of the one that now matters: served from the wheel on any other
  port, the editor loaded perfectly and every API call inside it went to a port
  with nothing on it. The base URL is resolved once
  (`src/core/runtime/runtimeBaseUrl.ts`) and is **same-origin relative** in a
  production bundle, so it follows the page to whatever host and port it was
  opened on. The dev stack keeps its absolute URL, because Vite on :5273 and
  uvicorn on :8000 are genuinely different origins and CORS still names exactly
  those two; `VITE_RUNTIME_BASE_URL` overrides either mode. Both modes are
  pinned by tests. Consequence: `docker-compose.yml`'s host port is no longer
  required to be 8000.
- **The static mount had no answer for an installed distribution.** It read a
  relative `dist` from the process's working directory, so it worked in the
  container and nowhere else. Resolution now has an order —
  `OPENSTATEGRAPH_STATIC_DIR`, then the wheel's own copy, then a checkout's
  `dist/` — in one module (`api/editor_assets.py`) that both the container and
  `openstategraph serve` go through. No second serving path was forked.

- **The editor's browser autosave could lose work three ways, all silently**
  (register UX-04). (1) A failed write was invisible: `saveWorkflow` returned an
  outcome and the autosave call site *discarded* it, so an exhausted ~5MB quota
  — or Safari's private mode, where every `setItem` throws — left the user
  editing a document nothing was recording. Failures now carry a typed kind
  (`quota`, `too-large`, `conflict`, `error`) and a sentence the editor shows,
  once per distinct failure rather than once per keystroke; an oversized
  document is refused *before* the write so the message names the document
  instead of blaming the disk. (2) A corrupt entry read back as `null`, which is
  indistinguishable from "nothing saved" — the user silently got the seeded demo
  instead of their graph. The reader now returns `ok`/`missing`/`corrupt`, says
  so, and *quarantines* the unreadable bytes under a separate key rather than
  deleting them (they are that user's only copy) or leaving them to fail every
  subsequent load. (3) Two tabs shared one autosave key and the last write won,
  so the losing tab displayed work it was overwriting. A claim record with a
  10-second heartbeat stops a second live tab adopting the id at all — it starts
  a blank workflow and says why — and a compare-and-set on every write catches
  the race the claim cannot. The compare is against *the version this tab last
  saw*, not the writer's identity, because an owner-based check would lock a
  workflow forever the first time its author closed the tab. Browser storage is
  still browser storage; the Workflows panel now says so out loud, and the
  server-side design is written up in the register.
- **`pip install 'openstategraph[mcp]'` was broken by an unpinned dependency.**
  `mcp` 2.0.0 removed `mcp.server.fastmcp`, which `openstategraph.mcp_server`
  imports, so a fresh install of the MCP extra failed at the transport's one
  entry point. Pinned to `mcp>=1.25,<2`, matching the LangChain pins' policy
  that majors are where these projects put breaking changes. Found by installing
  into a clean Python 3.11 environment while adding the CI version matrix — a
  developer machine with a cached 1.25 could not see it.
- **SQLite connections were never closed.** `with sqlite3.connect(...) as conn:`
  is a *transaction* manager, not a close — it commits and leaves the file
  descriptor open. Both read-only SQL surfaces used it: the `tool.sql-*`
  explorer tools an agent calls on every turn, and the knowledge builder's
  schema introspection, which opens a nested connection per table. A long
  agent loop leaked one descriptor per tool call. Both now use
  `contextlib.closing`, pinned by a test that asserts the connection actually
  refuses a query afterwards.
- **Nothing released the checkpointer or the memory store either.** langgraph's
  `SqliteSaver` and `SqliteStore` define neither `close()` nor `__exit__`, so
  every `load_workflow` call left two sqlite handles open for the life of the
  process, and a document with `settings.checkpointer: "sqlite"` opened a
  *fresh* connection to the same file on every run, stream and resume.
  `WorkflowServices` and `CompiledWorkflow` are now context managers with an
  idempotent `close()`, and the per-workflow saver is opened once per workflow
  and owned by the services object. What the caller injected is never closed —
  it is still theirs.
- **The installed-plugin scan ran on every request.**
  `importlib.metadata.entry_points()` re-walks every installed distribution's
  metadata, and `build_tool_registry` called it per run, per stream, and again
  per subgraph child. Measured on this checkout: `runtime_for` cost 14.8 ms
  steady-state, 12.2 ms of it in that one scan. The built-in and plugin layers
  are now resolved once per process (they cannot change without a restart);
  `runtime_for` is **1.05 ms**.
- **The knowledge curation panel read every document twice** — once for the
  index hint, once for the marker and claim hashes — and saving a topic wrote
  the file and then read the same bytes back to extract one line. One read per
  document now; a 60-topic listing went from 120 reads / 16.2 ms to 60 / 8.8 ms.

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
