# What OpenStateGraph is

**OpenStateGraph is a framework built on top of LangGraph and LangChain.** It
adds three things they do not have — a document format (`workflow.json`), a
compiler from that document to a plain LangGraph `StateGraph`, and the node
semantics the compiler emits. Everything else — the canvas editor, the HTTP
API, the MCP layer — is an optional surface over those three. You write a
document; we compile it; from that moment LangGraph owns execution, and the
graph is a standard Python object that runs in your service, in pytest or in a
Lambda with none of our surfaces present.

---

## How it is organised: atomic design

The palette is tiered, and the tier is the thing you are actually choosing
between. The tiers are declared once, in
[`src/nodes/vocabulary.ts`](../src/nodes/vocabulary.ts), and a test asserts the
ordering:

| Tier | Sections | What qualifies |
| --- | --- | --- |
| **Atoms** | `Inputs`, `Tools`, `Output` | one thing, made of nothing else. Sources with no logic; one capability bound to an agent; sinks with one input and no decision. |
| **Molecules** | `Reasoning & control`, `Memory` | one decision step — `agent.llm`, `route.classifier`, `route.grader`, `guard.policy`, `human.approval`, `orchestrate.supervisor`, `orchestrate.worker`, `function.format_report`, and `memory.segment`. **Memory is its own section deliberately**: a segment decides what is remembered rather than what happens next, and filing it under `Reasoning & control` would have made that heading false. |
| **Organisms** | `Composition` | `workflow.subgraph`, and only this: an entire compiled workflow — its own nodes, state and loop — mounted as one step. (`team.workflow` was listed here until schema v3 collapsed it into `workflow.subgraph`; it compiled through the same builder with no branch.) |
| **No tier** | `Annotate` | `group` and `note`. Never compiled, never executed, so they are not made of anything and nothing is made of them. |

Two boundaries are load-bearing, because getting them wrong is how a palette
teaches the wrong mental model:

- **A supervisor is a molecule, not an organism.** Alone it is one model call
  emitting a plan and a `Send` fan-out — a single reasoning step, exactly like
  a router. The organism is supervisor + workers + join, and that is a shape
  you *draw*, not an item you drag.
- **`function.format_report` is a molecule, not an output atom.** It joins many
  worker results, so it composes. `output.formatted` — one input, no logic — is
  the atom.

**The same ladder runs through the code.** Each family declares
Interface → Abstract/Base → Concrete and consumers import the interface:
`ITool → BaseTool → your tool`, `IRouter → BaseRouter → Router`,
`IGrader → BaseGrader → Grader`, `IOrchestrator → BaseOrchestrator →
Orchestrator`, and for agents the full four rungs —
`IAgent → AbstractAgentNode → BaseAgentNode → ReactAgentNode | DeepAgentNode`,
with `CustomGraphNode` a sibling directly under the abstract because it has no
prompt to compose. Composition is a *collaborator*, never a shared superclass:
routers, graders and agents each compose a `SystemPrompt` and a middleware slot
table rather than inheriting one, because they compile to different graph
constructs. Above all of that, the composition unit is the **workflow
package** — a directory of `workflow.json`, `tools/`, `functions/`,
`middlewares/`, `skills/`, `knowledge/` and `tests/` that mounts inside another
workflow as one organism.

## Familiar shape, different core

If you have adopted a packaged Lang\*-layered framework before, the surface
here should need no explanation. That is deliberate: the adoption interface is
the shape practitioners already expect, with a compiler underneath instead of
an engine.

**The same:**

| | Here |
| --- | --- |
| `pip install` + provider extras | four-package core; `[anthropic]` `[openai]` `[ollama]` `[deep]` `[sqlite]` `[server]` `[mcp]` `[postgres]` `[bastion]` `[all]` |
| one entry object | `from openstategraph import load_workflow` |
| a CLI | `openstategraph init · new · run · eval · validate · graph · examples · threads · knowledge · providers · env-example · serve · mcp` |
| a rich result object, not a string | `RunResult` — `.answer`, `.decisions`, `.outputs`, `.warnings`, `.attempts` |
| markdown domain knowledge as a first-class input | `knowledge/*.md` in the package, `--knowledge-dir` to point elsewhere |
| an optional drop-in for a team already on `create_agent` | `workflow.as_tool(...)` |

**The difference, and it is the load-bearing one:** those frameworks own their
agent loop — they drive the model themselves and a framework-agnostic core is
the selling point. We do the opposite on purpose. We compile to a LangGraph
`StateGraph` and never write an execution engine, so `langgraph` and
`langchain` sit in the **core** rather than behind an extra, and the artifact
you get back runs without us. Framework-agnosticism is not available to us, and
claiming it would be the dishonesty this project exists to avoid.

---

## The four layers, and who owns each

| Layer | Owner |
| --- | --- |
| **The document format** — `workflow.json`: vendor-neutral, versioned, diffable in a pull request | **us**, entirely |
| **The compiler** — document → `StateGraph`: ports, typed cycles, `Send` fan-out, reducer selection, subgraph mounting | **us** |
| **Node and runtime semantics** — the `abc/` ladders, slot-table middleware order, the composed prompt (preamble / context / *your rules* / output contract), the state schema and its named reducers | **us** |
| **Package conventions** — discovery of `tools/`, `functions/`, `middlewares/`, `skills/`, `knowledge/`, and the memory/checkpointer wiring | **us**, as the *default* only: convention is what you get for free, and every collaborator it discovers or builds can be replaced by an argument to `load_workflow` — see [It is an SDK](adoption.md#it-is-an-sdk-what-you-can-substitute) |
| **Optional surfaces** — the canvas editor, the HTTP API, `/chat`, the MCP layer | **us**, and all optional |
| Graph execution, checkpointing, time travel, `interrupt()`, streaming, `Send`, reducer merging | **LangGraph** |
| The agent loop, models, tools, messages, middleware | **LangChain** / `create_agent` |
| The batteries-included harness | **deepagents**, and only when a node asks for it |
| Provider SDKs, tracing backends, deployment | **not ours, ever** |

## What needs us at run time, precisely

Adopters test this first, so: three parts, not one slogan.

- **`workflow.json` needs us.** It is our format. Nothing else reads it.
- **The compiled graph does not.** It is a plain LangGraph object.
  `CompiledWorkflow.graph` hands it over, and every LangGraph capability works
  on it with nothing of ours in the call stack.
- **A *package* needs us**, because `tools/`, `functions/`, `middlewares/`,
  `skills/` and `knowledge/` are wired by *our* discovery conventions. Compile
  the document by hand and the agent is drawn with three tools, bound to none,
  and confidently answers from parametric memory. `load_workflow` exists
  because of that failure, and reports what it could not resolve on
  `.warnings` rather than raising.

---

## What it adds over raw LangGraph

Not "an easier `StateGraph`". LangGraph's API is already good. What you get is
a different *artifact*.

**The graph becomes a reviewable diff.** A branch added to a router is four
lines of JSON in a pull request, not a diff inside a thousand-line Python
module where the topology is implied by call order. Non-authors can read it.

**A visual editor, if you want one** — and an MCP layer if you would rather
have your own LLM compose the document. Both are optional; neither is in the
consumer's dependency path.

**Semantics that are already right where they are easy to get wrong:**

| | |
| --- | --- |
| `answer` carries a **named reducer**, not a bare field | a real fan-out scheduled two `answer`-writing nodes in one superstep and raised `InvalidUpdateError`; every single-writer test had passed |
| **the output contract is locked and goes last** | a router whose editable prompt was pre-filled with the contract broke the moment anyone cleared it to write their own rules — so your rules shape the decision, ours keep the shape of the answer |
| middleware is an ordered, **name-keyed slot table** | list position means three different things at once in LangChain (`before_*` forward, `after_*` reverse, `wrap_*` nested), so a single "priority" number expresses something that does not exist |
| `draw_mermaid()`, never `draw_mermaid_png()` | the default posts your graph to a third-party API |
| cycles are gated by **port type** | an accidental cycle stays inexpressible; the evaluator-optimizer loop is two clicks |
| a missing tool is a **warning on the result**, never silence | the loudest failure mode in this domain is a workflow that answers well without the data it was drawn with |

**A stability contract.** Three tiers, a signature-snapshot test, a versioned
document schema with a migration chain, and a document newer than your build
refused rather than best-effort compiled. See [stability.md](stability.md).

## What it deliberately does not own

- **An execution engine.** We compile to LangGraph and inherit checkpointing,
  time travel, `interrupt()`, `Send`, reducer merging and streaming. Writing
  our own would mean reimplementing all of it, and it is what makes the four
  closed-system competitors closed systems.
- **A second runtime target.** No `IOrchestrator` abstraction: no competing
  framework accepts a serialisable graph, so the interface would be unbindable
  rather than merely leaky. Portability is preserved in the *document* instead
  — expressions are a JSON AST, reducers are a named enum, the compile seam is
  one-directional, and no LangGraph type name leaks into `workflow.json`.
- **Hosting.** The framework ships; deployment stays yours.
- **Authentication for the MCP layer.** A stated gap, not a plan.
- **Model and vector-store integrations.** Provider packages are extras and
  `init_chat_model` resolves the one your `model` string names.
- **A routing policy for teams already on `create_agent`.** The answer there is
  `workflow.as_tool(...)`, not a middleware — middleware would have to decide
  *when* to consult the workflow, which is a router, and a router is something
  we already express as a document.

---

## The dependency picture, measured

Not estimated. These are `pip list` counts from real clean virtualenvs built
from the shipped wheel — *measured once, on one machine, 2026-08-10. Nothing in
the repository regenerates them, and several extras have gained dependencies
since, so read them as the shape of the argument rather than a number you can
check today.*

| Install | Distributions besides ours |
| --- | --- |
| `pip install openstategraph` | **36** |
| `pip install "openstategraph[ollama]"` | **38** |
| the same tree before 0.3.0 | **79** (the figure `backend/pyproject.toml`'s own dependency comment records; this page said 78 until 2026-08-16) |

The core is exactly four declared dependencies — `langgraph`, `langchain`,
`langchain-core`, `pydantic`. Everything else is behind an extra you ask for by
name:

```
[anthropic] [openai] [ollama]   one provider — you need exactly one
[deep]                          only a document with an agent.deep node
[sqlite]                        durable threads (settings.checkpointer)
[server]                        the editor's HTTP API — never on your path,
                                and no provider: pair it, [server,ollama]
[mcp]                           the MCP transport
[postgres]                      a shared checkpoint/memory store for more
                                than one process
[bastion]                       prompt-injection screening. AGPL-3.0-or-later,
                                so it is opt-in by name and NOT in [all]
[all]                           everything except [bastion], for a checkout
```

Read the list the way a sceptic does: of those 36, essentially all are
LangChain's and LangGraph's own closure — which you would have installed anyway,
because the alternative to using us is writing the `StateGraph` by hand.

**Our own wheel is 2.9 MB, and 2.7 MB of that is the editor.** *(Measured once on one machine, 2026-08-10; nothing in the repository regenerates it, so read it as an order of magnitude rather than a fact you can check.)* The Python is
276 KiB compressed; the built canvas is 1,553 KiB and the `/chat` flow view's
Mermaid is 952 KiB. That weight rides in the main wheel rather than a separate
`openstategraph-editor` distribution, deliberately: against the ~72 MB a
`[server]` install puts in `site-packages`, 2.7 MB does not justify a second
package name, a second version to keep in lockstep and a second clean-install
proof — and a `pip install openstategraph && openstategraph serve` that opens
the real product is the whole reason anyone tries this in the first place.
Sourcemaps (another 18 MB) are excluded; they are a debugging aid for people
working on *this* repository.

**A test keeps this honest.** `backend/tests/test_distribution_metadata.py`
asserts the unconditional requirements are exactly those four and that every
other package appears only under an `extra ==` marker; a subprocess test asserts
`load_workflow` leaves `fastapi`, `uvicorn`, `deepagents` and `mcp` out of
`sys.modules`; and CI's `clean-install` job installs the built wheel into an
empty venv outside the checkout, runs a workflow there, and then starts
`openstategraph serve --port 0` and asserts that `/` is the editor, `/chat` is
the chat page and `/api/workflows` is JSON — because a canvas that quietly
stopped shipping would look exactly like a 404.

---

## The escape hatches

The point of listing these is that you should be able to leave.

```python
from openstategraph import load_workflow

workflow = load_workflow("workflows/my-thing")
graph = workflow.graph      # a plain compiled LangGraph StateGraph
```

- **`.graph` is complete.** No proprietary object stands between you and
  LangGraph: `.stream()`, `.astream_events()`, `.get_state()`, `.invoke()`,
  interrupt and resume, your own checkpointer. Nothing is wrapped, because
  wrapping it would be the beginning of the execution engine we refuse to
  write.
- **`workflow.json` is documented, versioned and migrated**, and it is yours —
  it lives in your repository, not in a database we control.
- **`.warnings` tells you what did not wire**, so a degraded workflow is a
  visible fact rather than a subtly worse answer.
- **`as_tool()`** hands the whole workflow to an agent you already have, as one
  LangChain `StructuredTool`.
- **MIT**, and `requires_dist` is short enough to read in full.

---

## The honest trade

**What you buy.** A graph that is a JSON diff rather than a module. An editor,
if you want one. The semantics table above — every row of it is a bug someone
hits in week three of hand-writing LangGraph.

**What you pay.** A pre-1.0 dependency from a small project, on your production
path. Our conventions: package layout, slugs, discovery rules, schema version,
release cadence. And a real ceiling — anything our node vocabulary cannot
express you write as a `CustomGraphNode` or drop to `.graph`, and at that point
you are hand-writing LangGraph with extra steps.

**When not to use us.** One agent and three tools: use `create_agent`
directly. A graph whose shape is genuinely bespoke: use LangGraph directly. We
are worth it when there are *several* workflows, when people who did not write
them need to read them, or when the graph changes more often than the code
around it.

Saying that first is roughly the difference between a framework and a wrapper.

---

## Where to go next

| | |
| --- | --- |
| [Using it in your project](adoption.md) | the three consumption modes, with exact commands |
| [The stability contract](stability.md) | what is public, what can be taken away, and the deprecation policy |
| [Patterns](patterns.md) | the seven arrangements, mapped to our node vocabulary |
| [Building an atom](building-an-atom.md) | add a tool — including publishing one as your own distribution |
