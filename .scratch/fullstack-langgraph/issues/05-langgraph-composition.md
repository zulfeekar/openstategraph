Type: research
Status: resolved
Blocked by: —

## Question

How does one workflow consume another workflow's synthesised output?

From primary sources:
- **Subgraphs**: how a compiled graph is added as a node; shared-state-key vs transform patterns; how input/output schemas are declared and read.
- **Checkpointer scoping** for subgraphs — per-invocation versus per-thread, and the consequence for resumability.
- The **orchestrator-worker** pattern (`Send` + a reducer key + a synthesiser node), which is the shape the user described.
- Whether a subgraph's schema can be *introspected* — needed so the editor can derive a Workflow node's ports from the child workflow automatically rather than by hand.

Answer decides whether a "Workflow node" on the canvas is a subgraph reference and how its ports are derived.

## Answer

All facts below come from the official LangChain/LangGraph docs (Python variants), via the docs MCP server. Links at the bottom.

### Headline verdict

Yes — a "Workflow node" on the canvas maps cleanly onto a **compiled subgraph**. LangGraph documents exactly two composition patterns (shared-state-key vs. input/output transform), and the orchestrator-worker shape the user described (`Send` + reducer key + synthesiser) is a first-class, documented pattern.

On port derivation: **input/output schemas are declared explicitly and ARE machine-readable — but the documented, guaranteed-JSON-Schema path is the Agent Server introspection API, not a documented OSS Python method.** See section 4; this is the one item that needs a decision rather than just a fact.

---

### 1. Subgraphs: how a compiled graph becomes a node

A subgraph is "a graph that is used as a node in another graph" ([Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)). Documented motivations include reusing nodes across graphs and — directly relevant to us — "distributing development: … as long as the **subgraph interface (the input and output schemas) is respected**, the parent graph can be built without knowing any details of the subgraph."

There are exactly **two** communication patterns, chosen by whether the schemas share keys:

| Pattern | When to use | What you write |
| --- | --- | --- |
| **Add a subgraph as a node** | Parent and subgraph **share state keys** — the subgraph reads/writes the same channels | Pass the compiled subgraph directly to `add_node` — **no wrapper function** |
| **Call a subgraph inside a node** | **Different state schemas** (no shared keys), or you need to transform between them | A wrapper function mapping parent state → subgraph input, and subgraph output → parent state |

#### (a) Shared state keys — pass the compiled graph to `add_node`

```python
class State(TypedDict):
    foo: str

subgraph_builder = StateGraph(State)
subgraph_builder.add_node(subgraph_node_1)
subgraph_builder.add_edge(START, "subgraph_node_1")
subgraph = subgraph_builder.compile()

builder = StateGraph(State)
builder.add_node("node_1", subgraph)      # <-- compiled graph as the node
builder.add_edge(START, "node_1")
graph = builder.compile()
```

The subgraph may also have **private** keys not present in the parent (`bar` alongside a shared `foo`); it reads/writes shared channels automatically. Docs note this is how multi-agent systems typically communicate — over a shared `messages` key.

#### (b) Transform pattern — invoke inside a node function

```python
def call_subgraph(state: State):
    subgraph_output = subgraph.invoke({"bar": state["foo"]})   # parent -> child
    return {"foo": subgraph_output["bar"]}                     # child  -> parent

builder.add_node("node_1", call_subgraph)
```

This nests arbitrarily (parent → child → grandchild examples are given), and at each hop "child or parent keys will not be accessible here" — isolation is real.

**Recommendation for our Workflow node:** use the **transform pattern (b)**. Two independently-authored user workflows will not share a state schema, and (b) is the documented answer for exactly that case. It also gives us an explicit place to hang the port-mapping logic (canvas edge → child input key) and keeps the child's private channels out of the parent. Pattern (a) is the right choice only if we deliberately impose a shared envelope schema (e.g. a common `messages` channel) across all user workflows.

#### How input/output schemas are declared

Declared on the builder ([Graph API — multiple schemas](https://docs.langchain.com/oss/python/langgraph/graph-api#multiple-schemas), [Define input and output schemas](https://docs.langchain.com/oss/python/langgraph/use-graph-api#define-input-and-output-schemas)):

```python
builder = StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)
```

Semantics: an internal ("overall") schema is used for node-to-node communication; the input schema constrains what may be passed in; the output schema **filters** what `invoke` returns. A node "can write to any state channel in the graph state" — the graph state is the union of the overall schema plus the input/output filters plus any private schema a node declares. Schemas can be `TypedDict` (main documented form), `dataclass` (for defaults), or Pydantic `BaseModel` (recursive validation, slower; note `create_agent` does **not** support Pydantic state). An optional `context_schema` declares runtime context (not part of state).

**Sharp edge worth designing around:** "**Private channels are not redacted when streaming.**" Input/output/private schemas constrain what nodes *read* and what `invoke` *returns* — they do **not** hide channels from `stream`. With `stream_mode="values"` the graph emits *all* state channels including private ones. Pass `output_keys=[...]` (or use `stream_mode="updates"`) to restrict. If our canvas streams live values to the browser, private child-workflow state will leak unless we set `output_keys`.

---

### 2. Checkpointer scoping for subgraphs, and resumability

Set via the `checkpointer` argument on the **subgraph's** `.compile()` ([Subgraph persistence](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#subgraph-persistence)):

| Mode | `checkpointer=` | Interrupts (HITL) | Multi-turn memory | Multiple calls, different subgraphs | Multiple calls, same subgraph | State inspection |
| --- | --- | --- | --- | --- | --- | --- |
| **Per-invocation** (default) | `None` | ✅ | ❌ | ✅ | ✅ | ⚠️ current invocation only, while interrupted |
| **Per-thread** | `True` | ✅ | ✅ | ⚠️ namespace conflicts possible | ❌ | ✅ |
| **Stateless** | `False` | ❌ | ❌ | ✅ | ✅ | ❌ |

- **Per-invocation** — "Each call starts fresh and **inherits the parent's checkpointer** to support interrupts and durable execution **within a single call**." Recommended for most applications, including multi-agent systems where subagents handle independent requests. Resumable mid-call; nothing carries between calls.
- **Per-thread (`True`)** — state accumulates across calls on the same `thread_id`; each call picks up where the last left off. **Warning: does not support parallel invocation** — parallel calls to the same per-thread subgraph write the same checkpoint namespace and conflict. The docs prevent this with `ToolCallLimitMiddleware`; with raw `StateGraph` "you need to prevent parallel tool calls yourself."
- **Stateless (`False`)** — "runs like a plain function call". Explicit warning: "Without checkpointing, the subgraph has **no durable execution**. If the process crashes mid-run, the subgraph cannot recover and must be re-run from the beginning."
- **Precondition:** "The parent graph **must** be compiled with a checkpointer for subgraph persistence features (interrupts, state inspection, per-thread memory) to work."

Namespaces: `checkpoint_ns` is `""` for the root graph and `"node_name:uuid"` for a subgraph invoked as that node; nested namespaces join with `|` (`"outer_node:uuid|inner_node:uuid"`). Readable inside a node via `config["configurable"]["checkpoint_ns"]`. Nested state is read with `graph.get_state(config, subgraphs=True)` then `.tasks[0].state`. Note also: "When a subgraph updates state, the parent graph may not see the changes immediately… each subgraph manages its own checkpoint namespace."

**The gotcha that matters most for a visual editor.** Namespace *stability* differs between the two composition patterns:

> If you call subgraphs inside a node, LangGraph assigns namespaces **based on call order** (first call, second call, etc.). This means **reordering your calls can mix up which subgraph loads which state.**

Subgraphs **added as nodes** get name-based namespaces automatically and are safe. The documented workaround for the transform pattern is to wrap each child in its own `StateGraph` with a **unique node name**, giving it a stable namespace:

```python
def create_sub_agent(model, *, name, **kwargs):
    agent = create_agent(model=model, name=name, **kwargs)
    return (StateGraph(MessagesState)
            .add_node(name, agent)      # unique name -> stable namespace
            .add_edge("__start__", name)
            .compile())
```

**Consequences for us:**
1. Our Workflow node must emit a **stable, unique node name** derived from a durable identity (the child workflow's ID / the canvas node's ID) — never from a user-editable display name, and never order-dependent. Node names are baked into `checkpoint_ns` and into resume dispatch.
2. Renaming or removing a node is the one topology edit that breaks an *interrupted* thread ([Graph migrations](https://docs.langchain.com/oss/python/langgraph/graph-api#graph-migrations)).
3. Default to **per-invocation** for Workflow nodes: it supports HITL and durable execution per call, tolerates the same child appearing multiple times on a canvas, and tolerates parallel fan-out. Only opt into `checkpointer=True` for a child that genuinely needs multi-turn memory — and then we must forbid parallel invocation of that child.
4. Never `checkpointer=False` for anything a user might pause or that must survive a crash.

---

### 3. Orchestrator-worker (`Send` + reducer key + synthesiser)

This is documented as a named pattern with built-in support ([Workflows and agents — orchestrator-worker](https://docs.langchain.com/oss/python/langgraph/workflows-agents)):

> "The `Send` API lets you dynamically create worker nodes and send them specific inputs. **Each worker has its own state, and all worker outputs are written to a shared state key** that is accessible to the orchestrator graph. This gives the orchestrator access to all worker output and allows it to synthesize them into a final output."

Mechanism ([Graph API — `Send`](https://docs.langchain.com/oss/python/langgraph/graph-api#send)): `Send` objects are returned from a **conditional edge**; `Send(node_name, state_for_that_node)`. It exists for the case where "the exact edges are not known ahead of time and/or you may want different versions of `State` to exist at the same time" — the fan-out count need not be known at authoring time.

The three ingredients, from the documented example:

```python
from langgraph.types import Send

# 1. A reducer key that accumulates worker output
class State(TypedDict):
    topic: str
    sections: list[Section]
    completed_sections: Annotated[list, operator.add]   # all workers write here in parallel
    final_report: str

# Worker state is *different* from orchestrator state
class WorkerState(TypedDict):
    section: Section
    completed_sections: Annotated[list, operator.add]

def orchestrator(state: State):
    return {"sections": planner.invoke([...]).sections}

def llm_call(state: WorkerState):                       # the worker
    return {"completed_sections": [section.content]}    # append, don't overwrite

def synthesizer(state: State):                          # 3. the synthesiser
    return {"final_report": "\n\n---\n\n".join(state["completed_sections"])}

# 2. Fan-out via a conditional edge returning Sends
def assign_workers(state: State):
    return [Send("llm_call", {"section": s}) for s in state["sections"]]

builder.add_edge(START, "orchestrator")
builder.add_conditional_edges("orchestrator", assign_workers, ["llm_call"])
builder.add_edge("llm_call", "synthesizer")
builder.add_edge("synthesizer", END)
```

Notes:
- The third argument to `add_conditional_edges` (`["llm_call"]`) is the list of possible destinations — needed so the graph can be drawn/validated.
- The **reducer is what makes the join work**: `Annotated[list, operator.add]` accumulates concurrent writes rather than last-write-wins. Default (no reducer) overwrites, which would silently lose all but one worker's output. Reducers are binary `(left=current_state, right=node_update)`; `Overwrite` (`langgraph.types`) exists to bypass a reducer deliberately.
- The synthesiser is just a normal node downstream of the worker node; it reads the accumulated key. LangGraph joins the fan-out automatically (all `Send`-ed workers run in the same super-step; the synthesiser runs in the next one).
- The same shape exists in the Functional API (`@task` + `@entrypoint`, gathering `.result()` futures) and as a plain map-reduce example (`Send("generate_joke", {"subject": s})` → `jokes: Annotated[list[str], operator.add]` → `best_joke`).
- Related primitive: `Command` (`update`, `goto`, `graph`, `resume`) — notably `graph=` lets a subgraph navigate in the **parent** graph.

**This is exactly the shape for "one workflow consumes another workflow's synthesised output."** A Workflow node that fans out to N child-workflow invocations writes into a reducer-backed key; a downstream node in the parent consumes the accumulated list. Our canvas must therefore know, per state key, whether it has a reducer — a "collector" port is semantically different from a plain port.

---

### 4. Can a subgraph's schema be introspected? (decides automatic port derivation)

**Yes — schemas are derivable from a compiled graph, and the docs demonstrate JSON Schema generation for input, output, state, config and context, recursively across subgraphs. But the documented, contractual surface for this is the Agent Server HTTP API, not a documented OSS Python method.** Calling this out explicitly, as asked.

**Evidence that it works (strongest first):**

1. [`GET /assistants/{assistant_id}/subgraphs`](https://docs.langchain.com/langsmith/agent-server-api/assistants/get-assistant-subgraphs) — returns, **per subgraph namespace**, a `GraphSchemaNoId` object with `input_schema`, `output_schema`, `state_schema` (all required) plus optional `config_schema` and `context_schema`. Query param `recurse` (default `false`) walks subgraphs-of-subgraphs. There is also [`GET /assistants/{assistant_id}/subgraphs/{namespace}`](https://docs.langchain.com/langsmith/agent-server-api/assistants/get-assistant-subgraphs-by-namespace) to fetch one namespace. **This is precisely the "derive a Workflow node's ports from the child workflow" API.**
2. [`GET /assistants/{assistant_id}/schemas`](https://docs.langchain.com/langsmith/agent-server-api/assistants/get-assistant-schemas) — same fields for the top-level graph, plus `graph_id`.
3. [Rebuild graph at runtime](https://docs.langchain.com/langsmith/graph-rebuild) names introspection as a first-class server access context: `assistants.read` = "**Schema and graph introspection for visualization, MCP, A2A, etc.**", and the code comment "Introspection calls (`get_schema`, `get_graph`, …) skip this" — i.e. schema extraction runs against a graph built with no expensive resources.
4. [Expose an agent as MCP tool](https://docs.langchain.com/langsmith/server-mcp) — a deployed graph's MCP tool definition is derived mechanically: "Tool name: the agent's name. Tool description: the agent's description. **Tool input schema: the agent's input schema.**" A graph's input schema is already being turned into a machine-consumable schema in production today.
5. Topology (not schema) introspection in OSS Python is documented: `graph.get_graph()` → `.draw_mermaid()` / `.draw_mermaid_png()`, and `get_graph(xray=True)` expands subgraphs. Low-level `Pregel` also carries `nodes`, `channels`, `input_channels`, `output_channels` ([LangGraph runtime](https://docs.langchain.com/oss/python/langgraph/pregel)).

**The caveats, stated in the docs themselves:**

- Every schema field is annotated "**Missing if unable to generate JSON schema from graph**", and `input_schema`/`output_schema`/`config_schema`/`context_schema` are *optional* on the top-level `/schemas` response. So JSON-Schema generation is **best-effort, not guaranteed** — a state schema using types the generator can't express yields no schema. Port derivation must therefore have a fallback path (manual ports / declared ports).
- I found **no documented OSS Python API named `get_input_jsonschema`/`get_input_schema` on a compiled graph** in these docs. The mechanism plainly exists (the server does it), and `CompiledStateGraph` is a Runnable-family object, but the docs MCP server does not document it. **Do not build on an undocumented method without verifying it against the class reference at `reference.langchain.com`.**
- If we author graphs ourselves (rather than relying on JSON-Schema reflection), the **authoritative port definition is our own stored workflow definition** — we know the child's `input_schema`/`output_schema` because we generated them. Reflection is then a validation/repair mechanism, not the source of truth.
- Practical requirement, from [server-mcp](https://docs.langchain.com/langsmith/server-mcp): "Define clear, **minimal** input and output schemas to avoid exposing unnecessary internal complexity." The default `MessagesState` uses `AnyMessage` and is "too general for direct LLM exposure" — and equally too general to render as ports. Every user workflow we compile should get explicit, narrow `input_schema` and `output_schema`, not a bare `MessagesState`.

**Verdict for the editor:** a Workflow node **can** derive its ports automatically. Preferred design: ports come from our own stored workflow definition (which we also use to generate `input_schema`/`output_schema`), with the subgraph-schemas introspection endpoint (or its Python equivalent, once verified) used to *verify* that the compiled child actually matches the declared ports. Declaring narrow input/output schemas per workflow is a hard requirement either way — it is what makes the ports meaningful, what makes the "subgraph interface" contract the docs describe actually hold, and what `invoke`'s output filtering relies on.

### Doc pages used

- [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) (incl. [Subgraph persistence](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#subgraph-persistence), [Checkpointer reference](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#checkpointer-reference))
- [Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api) — [multiple schemas](https://docs.langchain.com/oss/python/langgraph/graph-api#multiple-schemas), [reducers](https://docs.langchain.com/oss/python/langgraph/graph-api#reducers), [`Send`](https://docs.langchain.com/oss/python/langgraph/graph-api#send), [`Command`](https://docs.langchain.com/oss/python/langgraph/graph-api#command), [graph migrations](https://docs.langchain.com/oss/python/langgraph/graph-api#graph-migrations)
- [Use the Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api) — [define input and output schemas](https://docs.langchain.com/oss/python/langgraph/use-graph-api#define-input-and-output-schemas), [map-reduce and the Send API](https://docs.langchain.com/oss/python/langgraph/use-graph-api#map-reduce-and-the-send-api)
- [Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) (orchestrator-worker)
- [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) (checkpoint namespaces)
- [LangGraph runtime (Pregel)](https://docs.langchain.com/oss/python/langgraph/pregel)
- [Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)
- [Get Assistant Schemas](https://docs.langchain.com/langsmith/agent-server-api/assistants/get-assistant-schemas)
- [Get Assistant Subgraphs](https://docs.langchain.com/langsmith/agent-server-api/assistants/get-assistant-subgraphs) / [by namespace](https://docs.langchain.com/langsmith/agent-server-api/assistants/get-assistant-subgraphs-by-namespace)
- [Rebuild graph at runtime](https://docs.langchain.com/langsmith/graph-rebuild)
- [Expose an agent as an MCP tool](https://docs.langchain.com/langsmith/server-mcp)
