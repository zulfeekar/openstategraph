# Dyflow — architecture principles

Visual AI workflow builder. TypeScript editor (JointJS core) + Python LangGraph runtime.

**Before planning anything, read `.scratch/fullstack-langgraph/map.md`** — the multi-session plan. Resolve one ticket per session (research excepted).

**Before reading source, query the code graph.** `graphify explain "X"`, `graphify path "A" "B"`. Rebuild with `graphify update .` after structural changes. The codebase is ~17k lines; reading files to orient is a waste of context.

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
- Pydantic is the **single source of truth**; TypeScript types are **generated**. Never hand-mirror a type across the boundary.
- One binding table drives both the keyboard dispatcher and the shortcuts drawer.

### Cardinality belongs to the port, not the node

A node has ports with different cardinalities at the same time — an agent's `prompt` takes exactly one link, its `tools` bus takes many, its `result` fans out to many. So there is no node-level "multiple edges" flag. Cardinality is `maxConnections` on the **port descriptor** (default: in = 1, out = unlimited), enforced by `capacityRule`.

Two distinct mechanisms, kept distinct:
- **A port that accepts many links** (a bus) → `maxConnections` on that port.
- **A node whose *number* of ports varies with config** → `ports: (data) => IPortDescriptor[]`.

Prefer varying the number of ports over toggling one port's cardinality. If a port sometimes carries a scalar and sometimes a list, its *type* changes at runtime and the executor must branch — which is what typed ports exist to prevent.

### Never put a non-finite number in a serialisable field

`Infinity` and `NaN` are not representable in JSON, and Pydantic/JSON Schema cannot express them. Use `int | None` with `None` meaning unbounded. (`maxConnections` currently violates this — see ticket 08.)

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
