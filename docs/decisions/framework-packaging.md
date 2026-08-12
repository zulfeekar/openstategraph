# Packaging OpenStateGraph as an installable framework

**Status: proposed (research + design, 2026-08-10). Resolves wayfinder ticket 01.**
**Verdict: one distribution named `openstategraph`, a lean core of four
dependencies, seven named extras, a two-tier public API enforced by a snapshot
test, an executed `document.version` migration chain, `entry_points` extension,
and a console script — because the adoption interface, not the compiler, is
what is missing.**

Every external claim below was fetched today. Anything I could not verify is
labelled **unverified**. Everything about *our* state was measured, not
recalled — the dependency counts come from real `pip install --dry-run
--report` runs and a real wheel build.

---

## 1. What the comparables actually do

### 1.1 The reference the owner supplied

`Text2SqlAgent/text2sql-framework` — 151 stars, 17 forks, 51 commits, MIT,
`Development Status :: 3 - Alpha`, two releases on PyPI (0.3.0 on 2026-06-04,
0.4.0 on 2026-07-17), `requires_python >=3.10`, hatchling.

| | |
| --- | --- |
| Core deps | **4**: `click>=8.0`, `pydantic>=2.0`, `rich>=13.0`, `sqlalchemy>=2.0` |
| Extras | `anthropic`, `openai`, `langchain`, `dashboard`, `dev`, `all` |
| Public API | one class — `from text2sql import TextSQL` |
| Two lines to value | `TextSQL("sqlite:///company.db").ask("Top 5 products by revenue")` |
| Returns | a **result object** — `result.sql`, `result.data` — not a string |
| Domain knowledge | a **parameter**: `examples="scenarios.md"`, `## heading` sections |
| Tracing | a **parameter**: `trace_file="traces.jsonl"` |
| CLI | yes — `text2sql ask …`, `text2sql query <url> "<question>"` |
| Positioning vs Lang* | framework-**agnostic** core, own agent loop on the raw SDKs; LangChain is `agent_backend="langchain"` and an *extra* |
| Optional integration | `Text2SqlMiddleware` — drops into a team's existing `create_agent` |
| Refuses to own | RAG, a semantic layer, schema descriptions, the database |

The shape that matters here is not the SQL. It is that **the entire LangChain
ecosystem — `langchain`, `langgraph`, `deepagents`, three provider packages —
lives behind one extra**, and the core is four unremarkable libraries. A
sceptical adopter reads `requires_dist` before the README, and that list says
"this will not colonise my virtualenv."

### 1.2 Packaged LangGraph layers, for contrast

| | `langgraph` | `deepagents` | `langgraph-supervisor` |
| --- | --- | --- | --- |
| Latest / date | 1.2.10, 2026-07-28 | 0.7.5, 2026-08-06 | 0.0.31, **2025-11-19** |
| Releases | 275 (since 2024-01) | 117 in ~12 months | 30 |
| Status classifier | 5 - Production/Stable | 4 - Beta | **none declared** |
| `requires_python` | >=3.10 | >=3.11,<4.0 | >=3.10 |
| Core deps | 6 | 7 | 2 |
| Extras | **zero** | `aws`, `quickjs`, `video` | **zero** |
| Optionality expressed as | **separate distributions** (`langgraph-checkpoint`, `-sqlite`, `-postgres`, `-prebuilt`, `-sdk`, `-cli`) | small extras | n/a |
| Public API | per-submodule `__all__` (`langgraph.graph`); **no top-level `__init__.py` at all** (namespace package) | one `__all__` of 19 names in `deepagents/__init__.py` | `__all__` of 3 functions |
| Internal boundary | `langgraph/_internal/`, docstring: "not part of the public API… stability is not guaranteed" | `_`-prefixed modules (`_api/`, `_tools.py`) | n/a |
| Extension | subclass `BaseCheckpointSaver`/`BaseStore`, publish your own dist; shared `checkpoint-conformance` suite | `register_provider_profile()` / `register_harness_profile()` (both marked beta, additive-merge) + middleware composition + a backend protocol | pass your own `create_handoff_tool(...)` output |
| `[project.entry-points]` | **none** | **none** | **none** |
| Stability policy | real and published: semver, 6–12 months between majors, "APIs prefixed with `_` … may change without notice", deprecations live ≥1 minor, removal only on major, LTS windows | pre-1.0; **breaking changes ship in minor bumps** (release-please `bump-minor-pre-major`); `AGENTS.md`: "Always attempt to preserve function signatures… for exported/public methods" | **none whatsoever** |
| Refuses to own | the agent harness, model integrations, persistence backends, deployment | security enforcement ("enforce boundaries at the tool/sandbox level, not by expecting the model to self-police"), the loop shape | itself — README now recommends the manual supervisor pattern instead |

Three lessons a maintainer should take:

1. **`langgraph-supervisor` is the cautionary tale.** Two dependencies, three
   exported functions, no classifiers, no policy, nine months stale, and a
   README that tells you not to use it. A thin layer over someone else's
   framework earns its keep only if it owns something the layer beneath cannot
   express. Ours does — a document format and a compiler — but that has to be
   *said*, because "wrapper" is the default reading.
2. **`deepagents` shows what a hot pre-1.0 layer looks like when it is honest:**
   `__all__`, `_`-prefixed internals, a published pre-1.0 policy, and a
   registry-based extension surface explicitly marked beta. It also shows the
   failure to avoid: it ships `langchain-anthropic` *and*
   `langchain-google-genai` as **hard core dependencies** while claiming model
   agnosticism. Its dependency closure is 52 distributions.
3. **Nobody in this stack uses `entry_points`.** Extension is imperative
   everywhere — subclass an ABC, call a register function, pass a factory
   result. That is a gap, not a norm to copy: all three of them are published
   *by the same organisation that owns the layer beneath*, so "fork or send a
   PR upstream" is a real option for them. It is not for our adopters.

---

## 2. Our current state, audited as an adopter would

Measured, 2026-08-10, against `backend/pyproject.toml` at `a38df15`.

### 2.1 What `pip install -e backend` actually pulls

A real `pip install --dry-run --report` of the built wheel resolves to
**79 distributions**.

A lean core of `langgraph>=1.0`, `langchain>=1.0`, `langchain-core>=1.0`,
`pydantic>=2.9` resolves to **36**. So **43 distributions — 54% of the
closure — are things a consumer of `load_workflow` may never touch**:

| Declared core dependency | Its own closure | Who actually needs it |
| --- | --- | --- |
| `deepagents>=0.7` | **52** dists, including `anthropic`, `google-genai`, `google-auth`, `cryptography`, `langchain-google-genai`, `wcmatch` | only a document containing an `agent.deep` node |
| `fastapi>=0.115` + `uvicorn>=0.30` | 13 | only the editor's HTTP server (`api/main.py` — the **single** file importing fastapi) |
| `mcp>=1.25` | 28, including `PyJWT`, `cryptography`, `jsonschema`, `sse-starlette`, `python-multipart`, `truststore` | only `mcp_server.py`, which already imports `FastMCP` lazily |
| `langchain-anthropic` + `langchain-openai` + `langchain-ollama` | 34 / 36 / 32 | exactly **one** of the three, whichever the adopter's `model` string names |

`deepagents` is the sharpest one: because it hard-depends on
`langchain-google-genai`, **every adopter today installs the Google GenAI SDK
and `cryptography` to run a workflow that may contain no agent at all.** That
is a footprint claim we cannot defend in a README.

The good news, and it is genuinely good: the *code* is already lazy. Every one
of `deepagents`, `fastapi`, `mcp`, `langchain.chat_models` is imported inside
a function, and `backend/tests/test_load_workflow.py` already pins in a
subprocess that `import openstategraph` touches neither LangChain nor
LangGraph, and that `load_workflow` touches neither `fastapi` nor `uvicorn`.
**The lean core is a metadata change, not a refactor.** That is the single
most important finding in this audit.

### 2.2 What the wheel looks like

I built it (`pip wheel --no-deps`) and opened it.

| Check | Result |
| --- | --- |
| Builds? | yes, 168 KB, 43 files, top-level `openstategraph` only (`tests/` correctly excluded) |
| `[build-system]` table | **absent** — the backend is implicit setuptools legacy fallback. Not reproducible; a setuptools change can alter the wheel silently |
| `LICENSE` in `dist-info` | **no** — `LICENSE` lives at the repo root, `backend/` has none, and the metadata carries only free-text `License: MIT`. A distribution with no license file is one a legal review rejects |
| `py.typed` | **no** — the package is thoroughly annotated and PEP 561 says none of it is visible. Every adopter on mypy or pyright sees `Any` |
| `README` / long description | **no** — the PyPI page would be blank |
| `classifiers` | **none** — no `Development Status`, no Python versions, no topics |
| `project.urls`, `authors` | **none** |
| Distribution name | `openstategraph-backend`, import package `openstategraph`. The name says "the backend of something else", which is exactly the framing this work is trying to change |

### 2.3 Public-by-accident

`openstategraph/__init__.py` declares `__all__ = ["CompiledWorkflow",
"load_workflow"]` — good, and the only `__all__` that is a real contract. But:

- **23 modules declare `__all__`**, including `api/main.py`,
  `compile/workflow_compiler.py` and `api/workflow_store.py`. In Python
  `__all__` reads as "this is the public surface". Right now it means "these
  are the names I export to my own siblings". A third party will read the
  former.
- **`abc/__init__.py` is empty.** The Interface → Abstract → Base → Concrete
  ladder that CLAUDE.md calls a non-negotiable — `ITool`/`BaseTool`,
  `IRouter`/`BaseRouter`, `IGrader`/`BaseGrader`, `SystemPrompt`,
  `MiddlewareSlotTable` — is the *most* public thing we have (every workflow
  package's `tools/*.py` subclasses `BaseTool`), and it is reachable only via
  deep module paths like `openstategraph.abc.tool`. Adopters will pin those
  paths and we will not be able to move a file.
- **The documented public path depends on a private name.** `loader.py:144`
  does `from openstategraph.api.registries import _document_of`. The one
  supported entry point in the package reaches into an underscore-prefixed
  function in the module tree we most want to call internal.
- **No test guards any of it.** Nothing fails when a public signature changes.
- Nothing prevents `from openstategraph.api.main import app` — and someone
  will, because it is the only way to mount the server today.

### 2.4 The schema version is decorative

There are **two** version numbers in play and **neither is read by any code**:

```
workflows/*/workflow.json
  { "version": 1,                 ← the store envelope's version
    "document": { "version": 2,   ← the document schema's version
                  "nodes": [...] } }
```

`grep` across `backend/openstategraph` finds no comparison, no branch, no
migration, no rejection on either number. `_document_of` unwraps the envelope
by looking for a `document` key and ignores both integers. `mcp_server.py`
*writes* `"version": 2` and `"version": 1` as literals in two places, and
`prebuilt_architect.py` teaches the model to emit `{"version": 2, ...}` in a
prompt string — so the number is propagated as folklore.

Consequence for an adopter: a document written by a future OpenStateGraph
loads silently into an older one, and any field whose *meaning* changed
compiles into a graph that runs and answers differently. That is the exact
failure class this codebase already names as the worst kind — a workflow that
looks like it works.

### 2.5 Three more things that would break a third party

- **`langgraph-checkpoint-sqlite` is imported but never declared.**
  `memory.py:202` does `from langgraph.checkpoint.sqlite import SqliteSaver`
  inside a `try`, and `memory.py:166` the same for `langgraph.store.sqlite`.
  Neither package is in `pyproject.toml`, and neither is a transitive of
  `langgraph` (verified — the lean-core closure of 36 does not contain it).
  So **`settings.checkpointer: "sqlite"` silently degrades to in-memory in
  every install that exists today.** A user asked for durability, got a log
  line, and will discover it when a restart eats a conversation.
- **`chinook_tool_registry()` reaches into `workflows/chinook-assistant/tools`,
  which only exists inside this checkout.** It is already wrapped in a
  `try/except` with a debug log (a good fix), but the *default* tool registry
  outside the repo is therefore quietly different from the one inside it. Any
  adopter whose document binds a `chinook.*` node type inherits a warning
  instead of a tool.
- **`EXTENSION_NAMESPACE = "org.openstategraph"` in `plugin_interop.py` is
  labelled "Placeholder-grade… pin this before publishing anything public."**
  Publishing is what this map is about. It is now due.

---

## 3. Recommendations

### 3.1 Distribution shape — one wheel, lean core, seven extras

**One distribution, renamed `openstategraph`** (import package unchanged).
Not the `langgraph` multi-dist split: that split exists because
`langgraph-checkpoint-postgres` genuinely versions on a different clock from
the graph engine. Nothing of ours does. One wheel with extras is what
`text2sql-framework` does at our maturity, and it keeps the install story a
single line.

**Core dependency floor — exactly four:**

```toml
dependencies = [
    "langgraph>=1.0,<2",
    "langchain>=1.0,<2",
    "langchain-core>=1.0,<2",
    "pydantic>=2.9,<3",
]
```

36 distributions, down from 79. Upper bounds are deliberate: LangChain's own
published policy reserves breaking changes for majors, so `<2` is a promise we
can rely on rather than a guess.

`langgraph`, `langchain` and `langchain-core` stay in the **core** and not
behind an extra, unlike `text2sql-framework`'s `[langchain]`. Their model is
"framework-agnostic core, LangChain optional" — ours cannot be, and pretending
otherwise would be the dishonesty this project exists to avoid. `pydantic` is
core because CLAUDE.md makes it the single source of truth for tool schemas.

**The extras:**

| Extra | Contents | Adds | Needed for |
| --- | --- | --- | --- |
| `[anthropic]` | `langchain-anthropic>=1.0,<2` | ~9 | a `model` string starting `anthropic:` |
| `[openai]` | `langchain-openai>=1.0,<2` | ~11 | `openai:` |
| `[ollama]` | `langchain-ollama>=1.0,<2` | ~7 | `ollama:` — the default, so the quickstart names it |
| `[deep]` | `deepagents>=0.7,<1` | ~26 | a document containing an `agent.deep` node |
| `[sqlite]` | `langgraph-checkpoint-sqlite>=3.1` | ~2 | `settings.checkpointer: "sqlite"` and `OPENSTATEGRAPH_MEMORY_PATH` |
| `[server]` | `fastapi>=0.115`, `uvicorn>=0.30`, `python-multipart` | ~13 | the editor's HTTP API and `/chat` |
| `[mcp]` | `mcp>=1.25` | ~24 | the MCP transport |
| `[all]` | every extra above | — | the current behaviour, for anyone upgrading |
| `[dev]` | `pytest>=8`, `pytest-cov>=5`, `ruff>=0.6` | — | contributors |

Note `[sqlite]` is a **bug fix wearing an extra's clothes** — it makes a
silently-degrading feature declarable. Ship it in the same change.

**Proving fastapi/uvicorn/deepagents/mcp stay out.** Three tests, all of which
extend a pattern `test_load_workflow.py` already uses:

1. *Metadata test* (fast, no network): read
   `importlib.metadata.requires("openstategraph")`, assert the set of
   unconditional requirements is **exactly** the four core names, and that
   `fastapi`, `uvicorn`, `deepagents`, `mcp` and every `langchain-<provider>`
   appear only with an `extra == "…"` marker. This is the one that fails the
   moment someone adds a dependency in the wrong place.
2. *Import test* (extend the existing subprocess pin): after
   `load_workflow(...)` on a document with no deep-agent node, assert none of
   `fastapi`, `uvicorn`, `deepagents`, `mcp` is in `sys.modules`.
3. *Clean-venv test* (CI only, §3.6): install the built wheel with **no
   extras** into an empty venv outside the repo, and run a workflow package.

**Backward compatibility.** `openstategraph-backend` is not on PyPI, so there
is no published name to break. Anyone with `pip install -e backend` in a
script keeps working if the rename ships alongside a note in `CHANGELOG.md`;
the *editor's* own install (`Dockerfile`, `scripts/dev.sh`, `pytest.ini`)
becomes `pip install -e backend[all]` — one grep, and the existing gates cover
it. Optionally publish `openstategraph-backend` once as a metadata-only
shim depending on `openstategraph[all]`; cheap insurance, no ongoing cost.

**Also settle in the same change:** `[build-system] requires = ["hatchling"]`
(what both text2sql-framework and deepagents use, and it needs no
`find_packages` incantation), `backend/LICENSE` as a copy or symlink of the
root file plus `license = "MIT"` + `license-files = ["LICENSE"]` (SPDX form,
as `langgraph` and `langgraph-supervisor` already use), `backend/README.md`
as `readme`, `openstategraph/py.typed`, `requires-python = ">=3.11"`,
`authors`, `project.urls` (Homepage, Repository, Changelog, Documentation),
and classifiers — `Development Status :: 4 - Beta` (the honest one; `3 -
Alpha` understates a codebase with 50 test modules, `5` overstates one with no
released version).

### 3.2 The adoption interface — what the reference has that we do not

The compiler is not our gap. The gap is everything between `pip install` and
a running workflow. Four lifts, in order of how much adoption each unblocks.

#### (a) A console script — the biggest single gap

We have **no CLI at all**. `text2sql` has one; so does `langgraph` (via
`langgraph-cli`). Every command below wraps a seam that already exists — the
rule for ticket 08 is **no new logic in the CLI layer**, and a reviewer should
reject any command whose body is longer than argument parsing plus a call.

```toml
[project.scripts]
openstategraph = "openstategraph.cli:main"
```

| Command | Wraps | Notes |
| --- | --- | --- |
| `openstategraph run <package> "<question>"` | `load_workflow(pkg).ask(q)` | `--model`, `--thread-id`, `--recursion-limit`, `--json` (emits the whole `RunResult`) |
| `openstategraph validate <package\|file.json>` | `prebuilt_architect.ValidateWorkflowTool` — the *same* seam `mcp_server._validate` uses; no second validator | prints findings as `- ` bullets |
| `openstategraph new <slug> [name]` | `scripts/new_workflow.py`; `--team` routes to `scripts/new_team.py` | **move** the two scripts into `openstategraph.scaffold` so they ship in the wheel; keep `scripts/*.py` as three-line shims so the checkout workflow is untouched |
| `openstategraph graph <package>` | `load_workflow(pkg).mermaid()` | text only, never `draw_mermaid_png()` |
| `openstategraph serve [--host --port --workflows-root]` | `uvicorn.run(openstategraph.api.main:app)` | requires `[server]`; a missing import prints `pip install "openstategraph[server]"` and exits 3 |
| `openstategraph mcp [--transport stdio\|streamable-http]` | `mcp_server.main()` | requires `[mcp]`; flags replace `OPENSTATEGRAPH_MCP_TRANSPORT` / `OPENSTATEGRAPH_MCP_ALLOW_RUNS`, which keep working |
| `openstategraph knowledge build <package> [--source X] [--instruction …]` | `api.knowledge_build.run_build` | prints `written / skipped / collisions / warnings` |

Exit codes, fixed and documented:

| | |
| --- | --- |
| `0` | success |
| `1` | usage error (bad arguments, unknown command) |
| `2` | the target is not a workflow package, or validation found blocking findings |
| `3` | a required extra is not installed (message names the exact `pip install` line) |
| `4` | the run completed but `.warnings` is non-empty and `--strict` was passed |
| `5` | runtime failure (model error, `GraphRecursionError`, unhandled exception) |

`4` is the one worth arguing for: it is how CI catches a workflow whose tools
stopped resolving, which is precisely the silent-degradation failure
`load_workflow` was built to surface. Off by default, because degrading loud
but not fatally is the established rule.

Dependency cost: **zero.** Use `argparse`. `click` and `rich` are what
`text2sql-framework` spends two of its four core dependencies on; a framework
arguing for a four-package floor cannot then add two for colour.

#### (b) A rich result object

`.ask()` returns a bare `str`. The graph's state carries far more —
`decisions`, `outputs`, `worker_results`, `attempts`, `feedback` — and every
one of those is what a developer needs when the answer is wrong. Today the
only way to see them is `.graph.invoke()` with hand-seeded initial state,
which is the six-line snippet `load_workflow` exists to replace.

**Recommendation: `.ask()` returns a `RunResult` that subclasses `str`.**

```python
class RunResult(str):
    """The answer, which *is* a string — plus everything the run also produced."""
    answer: str          # == self
    decisions: dict[str, str]      # node id -> branch label
    outputs: dict[str, str]        # node id -> that node's text
    worker_results: dict[str, str]
    attempts: int
    warnings: list[str]            # carried from CompiledWorkflow
    trace: list[dict] | None       # None unless trace_file/trace=True
    thread_id: str                 # so a follow-up call can continue
```

I considered the alternative — a plain dataclass with `__str__` — and reject
it, for one reason with evidence behind it. `load_workflow` **just shipped**
and `docs/adoption.md` publishes `print(workflow.ask("How many invoices are
there?"))`. `__str__` covers `print()` and f-strings, but silently breaks
`.ask(q).strip()`, `.upper()`, `x + result`, `json.dumps({"a": result})`,
`re.search(p, result)` and `isinstance(result, str)` — a set of breakages that
appear at runtime in someone else's service, not at import. A `str` subclass
breaks none of them: it *is* the answer, with attributes attached. The costs
are real but small and bounded — it is immutable (fine; the run is over),
`type(x) is str` is False (nobody writes that), and `copy`/`pickle` need
`__reduce__` (one method, one test).

The trade-off worth naming: `RunResult` inherits `str`'s ~40 methods, so
`result.<TAB>` shows `.title()` next to `.decisions`. That is the price of not
breaking a published API in its first month. Revisit at 1.0, where a real
major bump makes a clean dataclass affordable — and record that intent in the
docstring so it is a plan rather than a regret.

`.ask()` also stops swallowing state: it should seed `subtasks`,
`worker_results` and `feedback` alongside the three it seeds today, for the
same reason the docstring already gives for `attempts`/`decisions`/`outputs`.

#### (c) Explicit `knowledge_dir=` and `trace_file=` overrides

`text2sql-framework` passes domain knowledge as `examples="scenarios.md"` and
tracing as `trace_file="traces.jsonl"`. Ours are directory conventions
(`knowledge/`, and no tracing at all). Convention is the better default —
discovery-by-convention is why `load_workflow` takes one argument — but it
becomes a wall the moment knowledge is shared between two packages, or lives
outside the repo, or a test needs a fixture directory.

```python
load_workflow(
    package_dir,
    *,
    model=None,
    checkpointer=None,
    knowledge_dir: str | Path | None = None,   # default: <package>/knowledge
    trace_file: str | Path | None = None,      # default: no trace
)
```

Both keyword-only and both defaulting to today's behaviour, so this is purely
additive. `trace_file` writes JSONL from a LangChain callback handler — not a
new tracing system, and explicitly not a competitor to LangSmith; one line per
node entry/exit with timings, which is what makes `RunResult.trace` populated
and what a support ticket needs attached.

#### (d) Middleware / tool integration — **build a tool, skip the middleware**

`Text2SqlMiddleware` exists so a team already on `create_agent` can adopt
without restructuring. The equivalent question for us: should a team's
existing LangChain agent be able to call an OpenStateGraph workflow?

**Yes, and it is three lines, because LangGraph already did the work.**
`CompiledWorkflow.graph` is a compiled `StateGraph`, which is already
invocable; wrapping it as a `BaseTool` with a `question: str` argument is a
thin adapter:

```python
workflow.as_tool(name="billing_analyst", description="…")   # -> a LangChain tool
```

This is genuinely valuable and CLAUDE.md-consistent: subagents are invoked as
tools and return a `ToolMessage`, and they do not inherit the parent's state —
which is exactly the isolation a compiled workflow already has.

**A `Middleware` equivalent: skip.** Middleware would have to decide *when* to
consult the workflow, which means inventing a routing policy that our own
`RouterNode` already expresses as a document. Building it would put a second,
worse router in the framework and duplicate knowledge — the DRY defect
CLAUDE.md names. The honest answer to "we're already on `create_agent`" is
`as_tool()`, and one paragraph in the docs saying so.

### 3.3 Public API and stability contract

**Three tiers, and the tier is stated in the module docstring of every
module.**

**Tier 1 — semver-public.** Importable from the top-level package or
`openstategraph.abc`, nothing deeper:

```python
# openstategraph/__init__.py
__all__ = [
    "load_workflow", "CompiledWorkflow", "RunResult",
    "DEFAULT_RECURSION_LIMIT", "__version__",
    "WorkflowError", "PackageNotFound", "SchemaVersionError", "UnknownNodeType",
]
# openstategraph/abc/__init__.py  — currently empty; this is the fix
__all__ = [
    "ITool", "BaseTool", "ToolResult", "NoArgs", "Field",
    "IRouter", "BaseRouter", "Router", "Classification",
    "IGrader", "BaseGrader", "Grader", "Verdict",
    "IAgent", "AbstractAgentNode",         # names per abc/agent.py
    "IOrchestrator", "AbstractOrchestrator",
    "SystemPrompt", "MiddlewareSlotTable",
]
```

Plus the **entry-point group names** of §3.5 and the `workflow.json` schema
itself — a document written against version *N* must load on every framework
release that claims to support *N*. The schema is more public than any Python
symbol we ship.

Two things that need creating rather than exporting: `openstategraph.errors`
(today `load_workflow` raises bare `FileNotFoundError` and `ValueError`, which
an adopter cannot catch selectively) and `__version__`, which nothing exposes.

**Tier 2 — provisional.** Importable, documented, may change in a minor
release with a note: `openstategraph.compile` (`WorkflowCompiler`,
`NodeRuntime`, `RunState`), `openstategraph.knowledge`,
`openstategraph.plugin_interop`, `openstategraph.prebuilt_*`. Mark it exactly
as `deepagents` marks its registries — a visible "provisional" line in the
docstring, not a footnote in a changelog.

**Tier 3 — internal, no guarantee.** `openstategraph.api.*` and
`openstategraph.mcp_server`. These are *surfaces we operate*, not libraries
others build on. Follow `langgraph`'s own convention verbatim: a module
docstring saying "not part of the public API… stability is not guaranteed",
and rename toward `_`-prefixes over time. **Do not enumerate the registries as
public** — ticket 03 asks whether they should be, and the answer is no: §3.5
makes `entry_points` the supported extension seam precisely so the registry
objects can keep changing shape.

Two consequences to act on immediately:

- **Delete `__all__` from Tier 3 modules** (`api/main.py`,
  `api/workflow_store.py`, `api/capability_discovery.py`,
  `compile/workflow_compiler.py`, …) or accept that they read as promises.
  Deleting is right: `__all__` in a private module buys nothing.
- **`_document_of` must become public-internal.** Move it (or a thin wrapper)
  to `openstategraph/schema.py` as `normalize_document()` alongside the
  migration chain of §3.4, so the public `load_workflow` path no longer
  reaches into an underscore name in a Tier 3 package. `mcp_server.py` already
  has a `normalize_document` — collapse the two.

**Enforcement — a snapshot test, which is the whole point of ticket 03.**
`backend/tests/test_public_api.py`:

1. Import `openstategraph` and `openstategraph.abc`; for every name in
   `__all__`, capture `f"{qualname}{inspect.signature(obj)}"` for callables,
   and the field names + defaults for dataclasses.
2. Sort, join, compare against a checked-in `backend/tests/public_api.txt`.
3. On mismatch, fail with a unified diff and this message: *"The public API
   changed. If intended: update `public_api.txt`, add a `CHANGELOG.md` entry
   under the right heading, and — for a removal or a signature change — add a
   deprecation shim per `docs/decisions/framework-packaging.md` §3.3."*

The snapshot file is the artefact that makes a reviewer notice. A test that
merely asserts `"load_workflow" in dir(m)` would never have caught the
`_document_of` leak; a signature snapshot catches a changed default, a
parameter made positional, a dataclass field renamed.

Add a second, cheaper guard while you are there: assert that no Tier 1 module
imports from `openstategraph.api` **at module scope** (function-scope imports
stay legal — that is the lazy-import contract).

**Deprecation policy**, borrowed from LangGraph's published one and adjusted
for pre-1.0, exactly as `deepagents` does it:

- **Pre-1.0** (where we are): a breaking change bumps the **minor**, never the
  patch. Say so in the README the way deepagents' release notes do, so nobody
  reads `0.x` as semver-stable.
- A Tier 1 name is never removed without first shipping ≥1 minor release where
  it still works and emits `DeprecationWarning` naming the replacement.
- New parameters on Tier 1 functions are **keyword-only**, always. (The
  `load_workflow` signature already does this; keep it a rule, not a habit.)
- Post-1.0: removals only in majors, deprecations live ≥1 minor, and Python
  floor moves only in a major.
- `CHANGELOG.md` gains `### Added / Changed / Deprecated / Removed` under each
  version, and the public-API test's failure message points at it.

### 3.4 Schema versioning and migration

**`document.version` is the schema version. The envelope's `version` is the
store's own file format and is a separate, private number.** Nothing else in
the tree may carry a third.

Create `backend/openstategraph/schema.py` — Tier 1, no runtime imports:

```python
SCHEMA_VERSION = 2                     # what this build writes
MIN_SUPPORTED_VERSION = 1              # oldest we will migrate from

Migration = Callable[[dict], dict]
MIGRATIONS: dict[int, Migration] = {}  # from-version -> upgrade to from+1

def normalize_document(payload: dict) -> dict:   # replaces api.registries._document_of
    """Peel the store envelope, then migrate the document to SCHEMA_VERSION."""

def migrate_document(document: dict) -> dict: ...
def document_version(document: dict) -> int: ...
```

Policy, and it should be stated in the docs rather than only in code:

| Situation | Behaviour |
| --- | --- |
| `version` absent | assume `2` (**every document in the tree today is 2**), log one INFO line, stamp it |
| `version < SCHEMA_VERSION` | run the chain `MIGRATIONS[v]` … `MIGRATIONS[SCHEMA_VERSION-1]`; log which migrations ran |
| `version == SCHEMA_VERSION` | pass through |
| `version > SCHEMA_VERSION` | **raise `SchemaVersionError`** — "this document is schema v4; this build of openstategraph 0.3.1 understands up to v2. Upgrade with `pip install -U openstategraph`." Never a best-effort compile |
| `version < MIN_SUPPORTED_VERSION` | raise `SchemaVersionError` naming the last release that could read it |

**What bumps the version, and what does not** — this is the part that keeps
the number from becoming folklore again:

- **Bump:** removing a field, renaming a field, changing a field's *meaning* or
  its default's effect, changing a port id or a node type's id, changing the
  semantics of an edge.
- **Do not bump:** adding an optional field with a safe default, adding a new
  node type, adding a new port to a new node type, anything additive that an
  older build ignores harmlessly. (Additive-only is why we are still on 2.)
- Every bump ships with its `MIGRATIONS[n]` function **in the same commit**,
  plus a fixture document at version *n* in `backend/tests/fixtures/` that the
  test suite loads and compiles. The migration chain is only trustworthy if
  old fixtures keep running.

**Support window:** migrate from any version ≥ `MIN_SUPPORTED_VERSION`, and
raise `MIN_SUPPORTED_VERSION` only in a major release. Cheap to honour —
migrations are pure dict transforms — and it is the single loudest signal that
a customer's committed `workflow.json` is safe.

**Stamp the compiler.** On save and on MCP compile, write
`document.compiledBy = "openstategraph==<__version__>"` (the map's "not yet
specified" item — sharpen it here). It costs one line and turns "it worked
last month" into a diffable fact. It is metadata, not semantics, so it does
not bump the schema.

**Call it in exactly one place.** `load_workflow`, the store's `load`, the MCP
`compile`/`validate` and the HTTP run endpoints all currently call
`_document_of`; they all become callers of `normalize_document`. One seam, or
the guard has a hole.

### 3.5 Extension without forking — `entry_points`

None of the three comparables use entry points, and we should anyway. Their
users can send a PR to the org that owns the layer beneath; ours cannot, and
`docs/adoption.md` currently tells adopters the honest truth — "any edit you
make to `src/`, `backend/` or `scripts/` is a merge you own forever."

The registries already exist (`build_tool_registry`,
`discover_tool_registry`, `discover_function_callables`). Entry points are a
**third discovery source layered under the existing two**, not a new
mechanism:

```toml
# in the THIRD PARTY's pyproject.toml
[project.entry-points."openstategraph.tools"]
acme = "acme_osg_tools:TOOLS"
```

| Group | Object it must resolve to | Merged into |
| --- | --- | --- |
| `openstategraph.tools` | an iterable of `BaseTool` subclasses (or instances) | `build_tool_registry`, keyed by each tool's own `node_type` |
| `openstategraph.functions` | a mapping `name -> callable` | the `function.*` registry |
| `openstategraph.middlewares` | a mapping `slot name -> middleware factory` | the `MiddlewareSlotTable` — **by slot name, never by list position** |
| `openstategraph.knowledge_builders` | builder classes | the knowledge builder registry |
| `openstategraph.providers` | model-resolution contributions | `api.model_resolution` |

Four rules, all of which mirror behaviour the codebase already gets right:

1. **Precedence: workflow-local > entry point > built-in default.** Same
   local-shadows-global rule `build_tool_registry` documents for tools today.
   A plugin can never silently override a package's own tool.
2. **Jailed.** Each entry point loads in its own `try/except Exception`. A
   failure logs one WARNING naming the distribution and the group, and lands
   on `CompiledWorkflow.warnings`. One broken plugin must not take down the
   loader — that is the same "degrade loud, never silent" rule
   `load_workflow` already follows.
3. **Honest.** `RunResult.warnings` and `openstategraph validate` both list
   discovered plugins and their failures. A capability that appeared from an
   installed package must be attributable to it.
4. **Opt-out.** `OPENSTATEGRAPH_DISABLE_PLUGINS=1` and a
   `load_workflow(..., plugins=False)` keyword. A reproducible test run must
   be able to exclude whatever else is in the venv.

Naming convention for third parties, documented: `openstategraph-<x>` as the
distribution name, `openstategraph_<x>` or any importable name as the module.
We deliberately do **not** reserve the `openstategraph.` import namespace —
namespace packages are what `langgraph` uses, and it costs them a top-level
`__init__.py` and any possibility of a top-level `__all__`. Not worth it.

The TypeScript counterpart stays fog, as the ticket says.

### 3.6 Release pipeline

**Build.** `hatchling`. `backend/` keeps its own `LICENSE`, `README.md` and
`openstategraph/py.typed`. Version single-sourced from
`openstategraph/__init__.py:__version__` via
`[tool.hatch.version] path = "openstategraph/__init__.py"` so the wheel and
`import openstategraph; openstategraph.__version__` can never disagree.

**Prove the install in a clean venv — the gate that matters.** A CI job, and
the same script runnable locally:

```bash
python -m build backend                       # sdist + wheel
python -m venv /tmp/osg-clean && cd /tmp      # OUTSIDE the repo
/tmp/osg-clean/bin/pip install <wheel>[ollama]        # no extras beyond one provider
/tmp/osg-clean/bin/python -c "import openstategraph, sys;
  assert 'fastapi' not in sys.modules and 'deepagents' not in sys.modules"
cp -r <repo>/workflows/chinook-assistant /tmp/pkg && cd /tmp
/tmp/osg-clean/bin/openstategraph validate /tmp/pkg      # exit 0
/tmp/osg-clean/bin/openstategraph graph /tmp/pkg         # mermaid, no network
```

Run it with `PYTHONPATH` empty and `cwd` outside the checkout. Both are
essential: `pytest.ini` puts `workflows/chinook-assistant/tools` on the path
inside the repo, so a test that passes in-tree proves nothing about a wheel.
Pick a package with **no** chinook binding for the proof, then add a second
case that *does* bind one and assert the warning is present and legible —
that is the honest half.

**Publish.**

- Tags: `v0.3.0rc1` → **TestPyPI**; `v0.3.0` → **PyPI**. Both through
  **PyPI Trusted Publishing (OIDC)**, so no long-lived API token exists in
  repository secrets.
- The PyPI job depends on the clean-venv job. A wheel that has not been
  installed from scratch does not get published.
- After TestPyPI, a job installs *from TestPyPI* into a fresh venv (with
  `--extra-index-url` for the real dependencies) and reruns the smoke test.
  This is what catches a missing `py.typed`, a missing data file, or an
  `__init__` that imports something not in the wheel.
- `release-please` with `bump-minor-pre-major`, matching `deepagents`, so the
  pre-1.0 "breaking → minor" rule is mechanical rather than remembered.
- CI also runs the §3.3 public-API snapshot test and the §3.1 metadata test on
  every PR, not only on tags. Both are second-long tests and both fail on
  exactly the changes a reviewer would otherwise wave through.

Before the first publish: pin `EXTENSION_NAMESPACE` in `plugin_interop.py` to
a domain we actually control, and check the name `openstategraph` is free on
PyPI (**unverified** — I did not query PyPI for the name).

---

## 4. The positioning question, answered

**Is OpenStateGraph a framework wrapped around Lang\*? Yes — and the framing
is right, with one correction: "wrapped around" undersells it, because the
thing an adopter depends on is not a wrapper but a format and a compiler.**

The owner's sentence — "if anyone builds a workflow, OpenStateGraph must be
installed for it to work" — is **true today and true by design for the
package**, but not for the graph. Be precise about which, because adopters
will test the claim:

- **`workflow.json` needs us.** It is our format. Nothing else reads it.
- **The compiled graph does not.** It is a plain LangGraph object. `.graph`
  hands it over and every LangGraph capability works on it without us.
- **A *package* needs us**, because `tools/`, `functions/`, `middlewares/`,
  `skills/` and `knowledge/` are wired by *our* discovery conventions. That
  wiring is the difference between a workflow that answers and a workflow that
  looks like it answers — the `unresolved_tools` failure `loader.py` documents
  at length.

### What we own

| Layer | Who owns it |
| --- | --- |
| **The document format** — `workflow.json`, vendor-neutral, versioned, diffable in a PR | **us**, entirely |
| **The compiler** — document → `StateGraph`, ports, typed cycles, `Send` fan-out, reducer selection, subgraph mounting | **us** |
| **Node and runtime semantics** — the `abc/` ladders, slot-table middleware order, the composed-prompt rule (preamble / context / *your rules* / output contract), the state schema and its named reducers | **us** |
| **Package conventions** — discovery of `tools/`, `functions/`, `middlewares/`, `skills/`, `knowledge/`, and the memory/checkpointer wiring | **us** |
| **Optional surfaces** — the canvas editor, the HTTP API, `/chat`, the MCP layer | **us**, and all optional |
| Graph execution, checkpointing, time travel, `interrupt()`, streaming, `Send`, reducer merging | **LangGraph** |
| Agent loop, models, tools, messages, middleware | **LangChain** / `create_agent` |
| The batteries-included harness | **deepagents**, and only when a node asks for it |
| Provider SDKs, tracing backends, deployment | **not ours, ever** |

### What we refuse to own

An execution engine (CLAUDE.md forbids it, and the four closed-system
competitors are why); a second runtime target; hosting; authentication for
the MCP layer (a stated gap, not a plan); model or vector-store integrations;
and a routing policy for teams already on `create_agent` — `as_tool()`
instead of a middleware, per §3.2(d).

### The dependency picture an adopting team really gets

With §3.1 shipped, a team running a workflow in their own Python service
installs `openstategraph[anthropic]`: **~45 distributions, of which ~44 are
LangChain's, LangGraph's and Anthropic's.** Ours is one wheel of ~170 KB.
They already had, or would have had, essentially all of the rest — because the
alternative is writing the `StateGraph` by hand, which means installing
`langgraph` and `langchain` and a provider anyway.

Today, before §3.1, that same team installs **79 distributions** including a
web server, an MCP SDK, three provider packages and the Google GenAI SDK. That
gap *is* the adoption problem, and it is a metadata fix.

### The honest trade

**You take a dependency on us to get the format and the compiler. The
alternative is hand-writing LangGraph.** Stated plainly, both sides:

*What you buy.* A graph that is a reviewable JSON diff rather than a
thousand-line Python module. A visual editor, if you want one. Node semantics
that are already correct on the things that bite — a `keep_latest_nonempty`
reducer on `answer` because a real fan-out raised `InvalidUpdateError` on a
plain field; a locked output contract that a developer's own rules cannot
countermand; middleware ordered by slot name rather than by a list position
that means three different things; `draw_mermaid()` instead of the default
that posts your graph to a third-party API. Every one of those is a bug
someone hits in week three of hand-writing LangGraph.

*What you pay.* A pre-1.0 dependency from a small project, on your production
path. Our conventions — package layout, slugs, discovery rules. Our schema
version. Our release cadence. And a real ceiling: anything our node vocabulary
cannot express, you write as a `CustomGraphNode` or drop to `.graph`, and at
that point you are hand-writing LangGraph with extra steps.

*When not to use us.* One agent and three tools — `create_agent` directly.
A graph whose shape is genuinely bespoke — LangGraph directly. We are worth it
when there are *several* workflows, when non-authors need to read them, or
when the graph needs to change more often than the code around it. That is the
same reasoning `langgraph-supervisor`'s README eventually reached about
itself, and saying it first is what separates a framework from a wrapper.

*What derisks the trade, concretely:* `.graph` is a full escape hatch with no
proprietary object in the way; `workflow.json` is documented, versioned and
migrated; the compiled output is standard Python that runs, tests and deploys
without this editor; MIT; and the wheel's `requires_dist` is short enough to
read. Those five are the entire argument, and §3 is what makes each one true.

---

## 5. Ticket scoping notes

- **Ticket 02** names the extras as `[server]`, `[mcp]`, `[dev]`. That set
  omits the two that dominate the footprint: **provider extras** (three
  packages, ~30 distributions, only one ever needed) and **`[deep]`**
  (deepagents, 52 distributions on its own, including the Google GenAI SDK).
  It also does not cover `[sqlite]`, which is an undeclared dependency
  causing a live silent degradation (§2.5). Re-scope to §3.1's seven extras.
- **Ticket 03** asks whether "the registries" are public. **No** — ticket 05's
  entry points are the supported extension seam precisely so the registry
  objects stay free to change. Ticket 03 should also cover three things it
  does not name: populating the empty `abc/__init__.py`, creating
  `openstategraph.errors` and `__version__`, and removing `__all__` from
  Tier 3 modules.
- **Ticket 04** says "`version: 2` is in every document but nothing enforces
  or migrates it." Confirmed exactly, and there are **two** unread numbers,
  not one — the envelope's `version: 1` as well. The ticket should also fold
  in the `_document_of` → `schema.normalize_document` move, since the guard
  needs a single seam and that seam is currently a private name imported by
  the public loader.
- **Ticket 06** should treat the clean-venv proof as running with `cwd`
  outside the repo and `PYTHONPATH` empty, against a package that binds **no**
  chinook tool. `pytest.ini` puts the chinook tools on the path in-tree, so
  an in-tree pass proves nothing (§2.5).
- **Missing ticket — 08, and it is the one that changes adoption most.** The
  console script, `RunResult`, `knowledge_dir=`/`trace_file=`, and
  `CompiledWorkflow.as_tool()` (§3.2). Nothing in 02–07 covers the adoption
  interface, which is the entire lesson of the reference repo: their compiler
  equivalent is smaller than ours and their adoption surface is far larger.
  It blocks on 02 (the CLI needs the extras to give its exit-code-3 advice)
  and on 03 (`RunResult` is Tier 1 from birth).

## 6. Recommended order

1. **02** — pyproject: rename, lean core, seven extras, hatchling, LICENSE,
   README, py.typed, classifiers, urls, `__version__`. Plus the three
   footprint tests. Everything else assumes this landed.
2. **03** — tiers, `abc/__init__.py`, `errors`, the snapshot test. Do it
   before the CLI, so the CLI is written against a declared surface.
3. **04** — `schema.py`, the migration chain, the single `normalize_document`
   seam, `compiledBy`. Independent of 05; do it early because every day
   without it is another document written against an unenforced number.
4. **08** (new) — CLI, `RunResult`, `as_tool()`, the two overrides.
5. **05** — entry points.
6. **06** — clean-venv proof, TestPyPI, tag-triggered release.
7. **07** — rewrite `docs/adoption.md` and the site against §4. It goes last
   because it must describe what shipped, and `docs/adoption.md` currently
   contains a "there is no PyPI package yet" section that 06 deletes.
