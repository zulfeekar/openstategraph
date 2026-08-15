# OpenStateGraph — architecture principles

Visual AI workflow builder. TypeScript editor (JointJS core) + Python LangGraph runtime.

**Before planning anything, read the maps under `.scratch/`** — each is a multi-session plan with its own tickets, and there are several live at once (`production-ready/` is the current one; `fullstack-langgraph/`, `ship-it/` and `memory-hardening/` are others). Resolve one ticket per session (research excepted).

**Before reading source, query the code graph.** `graphify explain "X"`, `graphify path "A" "B"`. Rebuild with `graphify update .` after structural changes. The codebase is large enough that reading files to orient is a waste of context — `compile/node_runtime.py` alone is over 2,000 lines.

---

## Non-negotiables

### No god classes

A class with many public members is a design failure, not a convenience. If it can be described only with "and", split it.

**Ceiling: ~10 public members, one reason to change.**

`WorkflowController` (ticket 17) is fixed: 10 public members, each a
collaborator (`controller.nodes`, `controller.edges`, `controller.history`,
...). Extend it by adding a collaborator, never a method.

`WorkflowModel` is a **deliberate, recorded exception**, not a violation
still awaiting decomposition. Its internals *are* split — `AdjacencyIndex`
and `GraphQueries` hold the real implementations, independently unit-tested
— but its own public method count (`addNode`, `edgesOf`,
`topologicalOrder`, ...) was kept flat on purpose. Ticket 17's own
analysis concluded that collapsing those onto `model.queries.xxx()` /
`model.adjacency.xxx()` (the same move that fixed `WorkflowController`) is
a 100+-call-site rename across canvas, execution, and validation code for
a smaller public surface rather than a clearer design, and recommended
against forcing it. Do not re-litigate this without new evidence; do not
add new *behavior* directly onto `WorkflowModel` either way — a new query
belongs on `GraphQueries`, a new index on `AdjacencyIndex`, surfaced
through a thin pass-through only if genuinely needed.

### Interface → Abstract → Base → Concrete

Every entity family declares this ladder, and every layer earns its place:

- **`I*` interface** — the contract consumers depend on. Consumers import the interface, never the class.
- **`Abstract*`** — shared behaviour with genuinely abstract members subclasses must supply.
- **`Base*`** — a usable default implementation.
- **Concrete** — one node type, one tool, one provider.

This applies to **every** concept — node, edge, tool, provider, workflow — not only agents. Mirrored in Python and TypeScript.

Inheritance must earn itself. Where a hierarchy exists only to share two fields, use composition and say so. Depth is not a virtue.

### Shared concerns live on the base — but inherit the *capability*, not the *composition*

Anything used by every member of a family — middleware, model resolution, token accounting, retry, error handling, logging — is declared **once** on the abstract base. Never re-declared per concrete type. That is the anti-duplication rule and it is not negotiable.

The precise form matters, because LangChain middleware is a **list whose order is significant**:

- **The base owns the schema and the resolution.** `AbstractAgentNode` declares the shared config fields once and implements `resolveMiddleware(config) -> list`, the single place config becomes middleware.
- **The base does not own a hardcoded middleware list.** A base that instantiates middleware directly is a fragile base class: adding one silently changes every subclass, and a subclass has no clean way to insert its own middleware anywhere but the end.

So: **inherit the capability to compose; do not inherit the composition.**

### A prompt is composed, and the machinery is not editable

Applies to **every** node that drives a model, not just agents. Split the system prompt in two and keep them apart:

| Part | Owner | Editable? |
| --- | --- | --- |
| **Preamble** — what this node *is* | the base | **no** |
| **Context** — branch list, table schema, rubric | generated | no |
| **Rules** — the domain logic | the developer | **yes, and only this** |
| **Output contract** — the shape of the answer | the base | **no** |

`resolvePrompt()` on the base is the single place config becomes a prompt, exactly as `resolveMiddleware()` is for middleware. A developer supplies a sentence of rules and inherits a working node; a new kind of router is *configuration*, never a new class.

**Order is the substance: the output contract goes last.** Prompts are order-sensitive the way middleware is — later instructions win ties. If developer text came last, a rule like "explain your reasoning" would countermand the output format and every parse would fail. Their rules shape the *decision*; the base keeps the *shape of the answer*.

**Never ship the contract as a pre-filled editable field.** That was the original `RouterNode` bug: one `instruction` textarea pre-filled with the output contract, so clearing it — the first thing anyone does when writing their own rules — produced a router whose answer could not be parsed. Surface the locked sections **read-only** beside the editable one, so a developer can see what the machinery already says instead of duplicating or contradicting it.

**But prompt composition is a collaborator, not a base class.** Router, Grader and Agent compile to *different graph constructs*, so they are different families, and the boundary rule below applies: a shared `AbstractPromptedNode` would begin the god base class, and would force a prompt onto `CustomGraphNode`, which has none. Each family *composes* a `SystemPrompt`; nothing inherits it.

### The boundary — where inheritance stops

Sharing has two axes, and only one of them is inheritance:

| Shared… | Mechanism |
| --- | --- |
| **within** a family (all agents need summarization config) | abstract base class |
| **across** families (an agent *and* a tool node both want retry) | composition — a shared middleware/registry, a mixin, a decorator |

Pushing cross-family concerns up into a common ancestor is how "OOP everywhere" becomes a **god base class** — which violates the no-god-classes rule above and forces members to carry capabilities they do not use (an Interface Segregation failure). When a concern is needed by two *different* families, it is a collaborator, not a superclass.

### SOLID, applied concretely here

- **S** — one reason to change. See the god-class table.
- **O** — extend by **registering**, never by editing the engine. Every extension point is a `Registry<T>`: node types, executors, providers, connection rules, validation rules, canvas features, card bodies. A new capability must not require touching `core/`.
- **L** — a subclass must be substitutable for its base. If an override throws or no-ops, the hierarchy is wrong.
- **I** — narrow interfaces. `INodeExecutor` and `IToolExecutor` are separate so a node opts into being a tool without carrying unused methods. Keep doing that.
- **D** — depend on abstractions. `core/` imports **neither React nor JointJS**. Never break that.

### DRY — but not by accident

Duplication of *knowledge* is the defect; duplication of *shape* is often fine. Two things that look alike but change for different reasons should stay apart.

Hard rules:
- Node configuration is declared **once** as a field schema; card, inspector, defaults and validation all derive from it.
- Pydantic is the **single source of truth** for the run/stream seam, and `docs/openapi.json` is its generated, committed publication. TypeScript is **not** generated from it: `src/core/runtime/RuntimeClient.ts` is a hand-written client, to be pinned to the published contract by a drift test rather than by codegen — the argument, and why a generator was rejected, is `docs/decisions/typescript-runtime-types.md`. A new hand-mirror **without** that pin is what this rule forbids. (Until 2026-08-12 this line claimed the types were generated. No generator has ever existed and `RuntimeClient.ts` mirrors twelve types by hand, so the claim was unciteable in review; it was narrowed to what is true rather than left aspirational.)
- One binding table drives both the keyboard dispatcher and the shortcuts drawer.

### Cardinality belongs to the port, not the node

A node has ports with different cardinalities at the same time — an agent's `prompt` takes exactly one link, its `tools` bus takes many, its `result` fans out to many. So there is no node-level "multiple edges" flag. Cardinality is `maxConnections` on the **port descriptor** (default: in = 1, out = unlimited), enforced by `capacityRule`.

Two distinct mechanisms, kept distinct:
- **A port that accepts many links** (a bus) → `maxConnections` on that port.
- **A node whose *number* of ports varies with config** → `ports: (data) => IPortDescriptor[]`.

Prefer varying the number of ports over toggling one port's cardinality. If a port sometimes carries a scalar and sometimes a list, its *type* changes at runtime and the executor must branch — which is what typed ports exist to prevent.

### Never put a non-finite number in a serialisable field

`Infinity` and `NaN` are not representable in JSON, and Pydantic/JSON Schema cannot express them. Use `int | None` with `None` meaning unbounded.

`maxConnections` is the worked example, and it is **fixed** — `number | null`, with the reasoning recorded at the field itself (`core/model/contracts/ports.ts`): `JSON.stringify(Infinity)` is `"null"`, so the value would not survive its own round trip and nothing would report the loss. (Until 2026-08-13 this line said `maxConnections` "currently violates this"; it had been corrected and the rule document had not caught up — the same stale-claim defect this file warns about two sections down.)

### Small, named packages

Directory = bounded context, with an explicit public surface. No `utils/` dumping grounds. If a module has no one-sentence description, it has no reason to exist.

---

## Layering — the rule that holds it together

```
gesture → Controller → ICommand → Model → event → Adapter → canvas
```

The canvas is a **one-way projection** of the model. No gesture writes to the graph and hopes the model catches up. Consequences: undo is generic, the graph is disposable, and the two cannot drift.

`core/` is framework-free TypeScript. `canvas/` owns JointJS. `view/` owns React. `design/` owns tokens and primitives and contains no app logic.

**PureMVC the framework is rejected** — layering kept, framework not adopted. Reasoning: `.scratch/fullstack-langgraph/decisions/puremvc.md`. Do not reintroduce it.

---

## LangGraph

All LangGraph and LangChain facts come from the **`docs-langchain` MCP server**. Never from memory, never invented.

Settled vocabulary:
- **Graph** = `StateGraph` — nodes, conditional edges, shared state, `Send` fan-out, subgraphs.
- **Loop** = `create_agent` (ReAct). It returns a compiled LangGraph, so it drops into a `StateGraph` as a node.
- Therefore **canvas = StateGraph, Agent node = the loop, workflow composition = subgraphs.**

#### "Loop" means two things, and only one of them may reach a user

The vocabulary above is **internal**. `Loop` there is the ReAct tool-calling
loop *inside one agent*. A user arriving from the "loop engineering vs graph
engineering" discourse means something else entirely: the **feedback cycle
across nodes** — run a step, check it, run it again with the errors included.

Both are real and both exist here. The collision lands exactly where a user
reads, so the user-facing words are fixed:

| User-facing word | Means | Must never mean |
| --- | --- | --- |
| **Revision loop** | grader `revise` → agent `feedback`; ends when the grader passes or the step budget runs out | the agent's internal tool-calling |
| **Step budget** | `recursion_limit` — **supersteps** | "iterations" or "max turns"; one lap with fan-out costs several supersteps |
| **Workflow node** | another workflow run as one isolated step — task in, answer out | inline expansion, shared state |
| **Template** | a starting document; it produces a workflow and stops existing | a node type; a reusable definition |
| **Package** | the reusable definition — `workflows/<slug>/`, the thing a mount points at | a PyPI distribution, in user-facing copy |
| **Instance** | one mount of a package, carrying its own `data.overrides` | a copy of the package |
| **Eval** | grading a workflow **offline** against a committed dataset of questions whose answers are known — `openstategraph eval`, `<package>/evals/*.eval.json` | the grader node's in-run judgement, which routes rather than scores |
| *(internal only)* the loop | `create_agent` / ReAct | anything in UI copy |

#### "Template" also meant two things, and this settles it

The same collision as *loop*, found the same way — a reader used "template" for
the **reusable definition** a mount points at, while `templates/index.json` uses
it for the **scaffold**. Both senses were live in this repository's own
documents, so this was a naming decision rather than a tidy-up.

**Settled: "template" is the scaffold sense only.** It is already the CLI flag
(`--template`) and the editor's *Start from* picker, so the word is spent. The
reusable-definition sense is **package**, which is what the filesystem, the
docs and `mount-overrides.md` already call it.

That gives three words and three jobs, with no overlap:

> **A package is a definition. A template creates one. A mount instantiates one.**

The test that separates them, and the one a user actually cares about — *if I
change the original later, does this change too?*

| | Mechanism | Change the original later |
| --- | --- | --- |
| Mount a package | by **reference** | every instance changes |
| Start from a template | by **copy** | nothing changes; the link was severed |

`docs/on-the-canvas.md` is written to this lexicon and is where a user meets it.

**A loop is a cycle in the graph, not a wrapper around one.** That is the
substantive difference from the popular framing, which treats loop and graph as
two techniques you compose. Here they are one substrate — which is why the
answer to "how do I add a feedback loop" is two edges rather than a different
tool. The genuine *outer* loop of that framing — retry and stopping policy
around the whole thing — is `retry_policy` / `timeout` / `set_node_defaults`,
graph-assembly parameters that live on the workflow (see below), never a node.

**Eval is not a third axis.** Graph and loop are two shapes of one substrate —
both are drawn, and both compile into the `StateGraph`. An eval is neither
drawn nor compiled: it is the same judgement machinery pointed at a dataset
instead of at a run. A grader's verdict is an **edge** (`pass`/`revise`,
consumed by the graph); an eval's verdict is a **destination** (a scorecard,
consumed by a human or a CI gate). Same judge, different consumer, different
clock. So there is no eval node, and there should not be one — the dataset is a
package file, and if the editor ever surfaces an eval it is a panel, not a node.
`docs/evaluation.md` §"Grading during a run vs grading a dataset" carries the
long version, including the third thing that is neither: a package's `tests/`,
which asserts the *document* and calls no model at all.

### Agent type is a developer choice, and it mirrors the library's own layering

LangChain publishes three tiers — *framework, runtime, harness*. A developer picks which one an Agent node is:

| Tier | Construct | Node type |
| --- | --- | --- |
| LangGraph (runtime) | hand-written `StateGraph` node | `CustomGraphNode` |
| LangChain (framework) | `create_agent` — minimal configurable harness | `ReactAgentNode` |
| Deep Agents (harness) | `create_deep_agent` — batteries-included | `DeepAgentNode` |

`create_deep_agent` **pre-assembles a middleware stack on top of `create_agent`** — but read that precisely: it is `create_agent` **plus a fixed slot assembly, not plus subclassing**. The library expresses the relationship as *data*, so `DeepAgentNode` is a **sibling** of `ReactAgentNode` under `AbstractAgentNode`, differing only by which middleware preset it declares. (An earlier draft here said `DeepAgentNode extends ReactAgentNode`; that was wrong and is superseded — it broke leaf semantics for no gain once the stack is data.)

### Middleware order is a slot table, never a list position

Because list position means **three different things at once**:

| Hook | Order |
| --- | --- |
| `before_*` | first to last |
| `after_*` | **last to first (reverse)** |
| `wrap_*` | nested — the first middleware wraps all others |

So `super().resolveMiddleware() + [mine]` does *not* mean "mine runs last". It means: my `before_*` runs last, my `after_*` runs **first**, and I am the innermost wrapper. **Any scheme expressing position as one number — append, prepend, or a priority integer — is expressing something that does not exist.**

Therefore `resolveMiddleware()` returns an **ordered, name-keyed slot table**; the base owns the canonical slot order, a subclass or plugin contributes by *naming a slot*, and replacement is by slot name. The compiler flattens to a list last. This mirrors `create_deep_agent`, whose 12-slot order encodes documented semantic constraints (Skills before Filesystem so skill metadata precedes file tools; Memory after prompt caching so injected memory does not invalidate the cache prefix). Never expose a raw ordering number to a user — it would let them express an invalid order silently.

### Retry, timeout and caching are graph-assembly parameters, not node concerns

`retry_policy`, `timeout`, `error_handler` and `cache_policy` are parameters of **`StateGraph.add_node`**, available to every node of every family, and `StateGraph.set_node_defaults(...)` applies them graph-wide with per-node override. So they live on the **workflow** and compile to graph assembly — never on an agent base, a tool base, or a shared ancestor.

This is the cross-family boundary rule confirmed by the runtime: putting `retry` on an agent base would force a duplicate onto the tool base and then two spellings of one feature. Token accounting and logging stay deliberately **not** unified — middleware for agents, callbacks/tracing elsewhere — because unifying them would invent an abstraction LangGraph does not have.

### Ollama means Ollama **cloud**, never a local model

Standing instruction, with direct evidence. `llama3.1:8b` running locally could not
hold `response_format` at all, took minutes per run, and answered a Chinook database
question from parametric knowledge — confidently, about global music revenue, having
queried nothing. The same workflow on `gpt-oss:120b-cloud` wrote a correct two-join
`GROUP BY` and answered in 23 seconds.

So: a bare `ollama:` fallback resolves to `OLLAMA_CLOUD_MODEL`, the model picker sorts
`-cloud` models first and labels local ones as local, and a local model must be named
explicitly to be used. Never benchmark, demo or debug against a local model and treat
the result as representative — a weak model turns a wiring bug and a capability gap
into the same symptom.

**The cloud is reached by `OLLAMA_API_KEY` plus an endpoint default, not by an
ambient daemon.** Until providers-and-credentials ticket 02 this rule was stated
and not enforced: Ollama's `ProviderSpec` declared `env_vars=()` — presented as
"keyless" — while nothing passed an endpoint at all, so `ollama.Client` dialled
`127.0.0.1:11434` and the cloud was reached, when it was reached, through a local
daemon signing with `~/.ollama/id_ed25519`. That credential never passes through
the environment and cannot be seen, moved or revoked from one, and on a machine
with no daemon running `/api/health` still reported `model_configured: true`. The
rule was being broken by omission rather than by decision.

It now declares `env_vars=("OLLAMA_API_KEY", "OLLAMA_HOST")` and
`endpoint_env=("OLLAMA_HOST", "OLLAMA_ENDPOINT")` with `default_endpoint =
"https://ollama.com"`. Because `is_configured` takes **any** of `env_vars`, two
setups coexist and both are supported: the key alone is the cloud; `OLLAMA_HOST`
alone is a daemon you run, which needs no key of ours because it owns its own
auth. Endpoint precedence is tuple order — your host, else `OLLAMA_ENDPOINT`,
else the cloud. Never restore a spec that reaches a vendor without naming a
variable someone can set, see and revoke.

### Never send a user's graph to a third party

`draw_mermaid_png()` defaults to posting the graph to the **Mermaid.Ink API**. Use **`draw_mermaid()`**, which returns Mermaid text with no network call and no extra dependency, and render it in the frontend. Compiled-graph previews come from `compiled.get_graph(xray=True).draw_mermaid()` — `xray=True` expands subgraph internals, so a preview shows what the compiler actually produced rather than a hand-drawn approximation that can drift.

### Cycles are gated by port *type*, and the step budget is not an iteration count

A loop is drawable only where a node declares a typed feedback input (`GraderNode.revise: feedback` → `AgentNode.feedback`). The type system stays the gate, so an *accidental* cycle remains inexpressible while the evaluator-optimizer pattern is two clicks. A cycle must contain at least one conditional edge — an all-static cycle can never terminate.

`recursion_limit` is a **standalone `config` key, not inside `configurable`** (default 1000 in Python since 1.0.6, 25 in JS; raises `GraphRecursionError`). It counts **supersteps, not iterations** — with fan-out, one lap of a loop can cost several supersteps — so never label it "max iterations" in the UI. Prefer generating a `RemainingSteps` guard so a runaway loop routes to `END` instead of crashing.

### State flows down; subagents do not receive it

Two distinct mechanisms, easy to conflate and important not to:

- **Graph state** flows to *nodes* through the shared state schema and reducers.
- **Subagents are isolated.** A subagent is invoked as a *tool*; its result comes back as a `ToolMessage` (JSON when `response_format` is set, otherwise its last message text). It never sees the parent's message history or graph state — it receives a task and reports a result.

Never build UI or state plumbing that implies a subagent shares the parent's context.

### A state key more than one node type can write needs a named reducer

A bare scalar field (`answer: str`) is only safe for state exactly one node
type ever produces. The moment two node kinds can legitimately write the same
key, use `Annotated[T, reducer]` — never a plain `LastValue` field. This was
found live, not hypothetically: a real graph combining a router, `Send`
fan-out, and multiple tool-using workers scheduled two `answer`-writing nodes
in the same superstep, and LangGraph raised `InvalidUpdateError` on a field
every scripted, single-writer-at-a-time test had exercised without incident.
`decisions`/`outputs`/`subtasks`/`worker_results` already followed this rule;
`answer` did not, and the gap was invisible until a real fan-out/join subgraph
ran. Applies to every future compiled workflow state schema.

### Portability guardrails

We go **deep on LangGraph** deliberately — no `IOrchestrator` abstraction, because no competing framework accepts a serialisable graph, so such an interface is unbindable rather than merely leaky. Portability is preserved instead by keeping `workflow.json` the vendor-neutral layer and obeying four rules that cost nothing now and are expensive to retrofit:

1. **Expressions are a JSON AST, never host-language code.** A router predicate is serialisable data — never a Python or JavaScript lambda. Storing a function kills portability *and* serialisability in one move.
2. **Reducers are a named enum**, not arbitrary functions.
3. **The compile seam is one-directional**: `workflow.json` → runtime. Nothing reads runtime objects back into the model.
4. **Our own runtime vocabulary.** Do not leak LangGraph type names into `workflow.json` or into `core/`.

Adding a second runtime later is roughly an engineer-quarter, and permanently multiplies the cost of every new node type. Do not pay it speculatively.

### We are a compiler, not a runtime

Three distinct approaches exist. Know which one this is:

| Approach | Who executes | Examples |
| --- | --- | --- |
| Own your executor | you write the engine | n8n, Dify, Langflow, Flowise |
| Multi-runtime compiler | abstract over several | Oracle Agent Spec (the only one) |
| **Single-target compiler** | someone else's | **this project → LangGraph** |

**Never write an execution engine.** We compile `workflow.json` to a LangGraph `StateGraph` and inherit its checkpointing, time-travel, `interrupt()`, `Send` fan-out, reducer merging and streaming. Any proposal to "just interpret the graph ourselves" is a proposal to reimplement all of that — reject it.

The consequence worth protecting: those four tools are closed systems, where a workflow runs inside their platform or not at all. Our output is a standard Python object that runs anywhere Python runs — importable from a script, testable with pytest, deployable without this editor. **The compiler is not portable; the output is.** That is what makes `functions/`, `tools/` and `tests/` real code rather than decoration.

---

## Tests

TDD. Tests before implementation. `core/` is pure TypeScript and directly unit-testable — there is no excuse for untested logic there.

Never refactor a god class without tests in place first.

## Worktree economy

A git worktree of this repo must NOT install its own dependencies — each
copy costs ~420M (`node_modules` 183M + a venv 235M) for nothing. Instead:

```bash
ln -s /Users/zulfeekar.cheriyampu/openstategraph/node_modules node_modules
```

and use the system `python3` (the backend's deps are installed user-level;
`python3 -m pytest` works with no venv). Never run `npm install` or create
a `.venv` inside a worktree unless a dependency actually changed — and if
one did, do it on the main checkout and re-link.

<!-- OPENWIKI:START -->

## OpenWiki

This repository uses OpenWiki for recurring code documentation. Start with `openwiki/quickstart.md`, then follow its links to architecture, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->

Everything between the OPENWIKI markers above is stamped verbatim by
`openwiki code --update` on every run — a hand-edit inside the markers does
not survive the next run, which is why this correction lives outside them.
The stamped claim that the scheduled workflow "refreshes the repository wiki"
describes intent, not observed behaviour:

> **It has never run.** This repository has six workflow files and **zero git
> remotes**, so nothing in `.github/` has ever executed — not this, not the type
> gate, not the drift gates, not `clean-install`. Until that changes (ship-it
> ticket 49), "let OpenWiki regenerate" means *a human runs it*, and a generated
> page you leave stale stays stale. Treat every sentence in this repository
> asserting that a gate "runs" or "is enforced" as describing intent, not
> observed behaviour.
