Type: research
Status: resolved
Blocked by: —

## Question

What are LangGraph's routing and control-flow primitives, precisely, and which one backs a canvas "router" node?

From the docs-langchain MCP only:
- `add_conditional_edges` — signature, what the router function returns, whether the destination list must be declared up front.
- `Command` (e.g. `Command(goto=...)`) — dynamic routing *from inside* a node; how it differs from a conditional edge and when each is correct.
- `Send` — dynamic fan-out to parallel workers with per-worker state.
- `START` / `END` semantics, recursion limit / `GraphRecursionError`.
- Whether a node may return both a state update and a routing directive.

The user's scenario to satisfy: text input → router node → routes on instruction/tools/whatever → output pipes into *any* node type. Determine which primitive expresses that, and what the canvas must capture per outgoing edge (a label? a predicate? a target set?).

## Answer

Sources (all from the docs-langchain MCP server; Python-first, TS noted where it differs):
[Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api) ·
[Use the Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api) ·
[Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) ·
[Multi-agent: Router](https://docs.langchain.com/oss/python/langchain/multi-agent/router) ·
[Router tutorial (knowledge base)](https://docs.langchain.com/oss/python/langchain/multi-agent/router-knowledge-base) ·
[`StateGraph.add_conditional_edges` reference](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges) ·
[`Command` reference](https://reference.langchain.com/python/langgraph/types/Command) ·
[`Send` reference](https://reference.langchain.com/python/langgraph/types/Send) ·
[Studio: graph edge issues](https://docs.langchain.com/langsmith/troubleshooting-studio#graph-edge-issues)

---

### 1. `add_conditional_edges`

Exact signature (Python, `langgraph.graph.state.StateGraph`):

```python
add_conditional_edges(
    self,
    source: str,
    path: Callable[..., Hashable | Sequence[Hashable]]
        | Callable[..., Awaitable[Hashable | Sequence[Hashable]]]
        | Runnable[Any, Hashable | Sequence[Hashable]],
    path_map: dict[Hashable, str] | list[str] | None = None,
) -> Self          # returns self, so calls chain
```

- `source` — the node this edge fires **after**. The virtual `START` node is a legal source (that is the "conditional entry point").
- `path` — the "routing function". Receives the current graph `state` (same calling convention as a node) and returns:
  - a **node name** (`str`), or
  - a **sequence of node names** — all of them run **in parallel in the next superstep**, or
  - `END` to terminate, or
  - one or more **`Send` objects** (see §3).
  The return type is `Hashable`, so non-string keys are legal *if* you supply a `path_map` (`{True: "node_b", False: "node_c"}` is the canonical example).
- `path_map` — optional. `dict[Hashable, str]` maps the routing function's return value to a node name; a bare `list[str]` just **declares the possible destinations** without remapping.

**Must destinations be declared up front?** Not for *execution* — a routing function returning a raw node name works with no `path_map`. But they must be declared for *rendering/validation*. The reference carries an explicit warning: without return type hints on `path` (e.g. `-> Literal["foo", "__end__"]`) **or** a `path_map`, "the graph visualization assumes the edge could transition to any node in the graph." The Studio troubleshooting page repeats this as a known symptom (spurious edges to every node). So there are three equivalent ways to declare the target set: a `Literal[...]` return annotation, a `path_map` dict, or a `path_map` list.

TypeScript: `graph.addConditionalEdges(source, routingFunction, pathMap?)`; routing functions are typed `ConditionalEdgeRouter<typeof State, "b" | "c">` instead of via `Literal`.

### 2. `Command` — dynamic routing from *inside* a node

```python
Command(
    *,
    graph: str | None = None,               # None = current graph; Command.PARENT = closest parent
    update: Any | None = None,              # state update, same shape a node would return
    resume: dict[str, Any] | Any | None = None,
    goto: Send | Sequence[Send | N] | N = (),
)
```
Import: `from langgraph.types import Command`. Note `goto` accepts a node name, a sequence of node names, a `Send`, or a sequence of `Send`s — so `Command` can itself fan out.

The docs name three usage contexts:
1. **Returned from a node** — `update` + `goto` (+ `graph`).
2. **Passed as input to `invoke`/`stream`** — `resume` only. There is an explicit warning that `Command(resume=...)` is the *only* pattern intended as input; passing a bare `Command(update=...)` as input resumes from the latest checkpoint (not `__start__`) and makes a finished graph appear stuck. Continue a conversation with a plain input dict instead.
3. **Returned from a tool** — same `update`/`goto` semantics from inside tool code.

Two hard constraints when returning `Command` from a node:
- You **must** annotate the return type with the reachable node names: `def my_node(state: State) -> Command[Literal["my_other_node"]]:`. This is what tells LangGraph (and the renderer) where the node can navigate.
- `Command` **only adds dynamic edges — static edges still fire.** If `node_a` returns `Command(goto="x")` *and* `add_edge("node_a", "node_b")` exists, **both** `x` and `node_b` run. The Graph API page states the rule as a warning: per node, pick *one* routing mechanism — normal edges for static routing, or conditional edges / `Command` for dynamic routing. Never mix them from the same node.

`Command(graph=Command.PARENT)` navigates from a subgraph node to a node in the closest parent graph (this is the multi-agent handoff mechanism). When doing so, any state key shared between parent and subgraph schemas **must** have a reducer defined in the parent.

**`add_conditional_edges` vs `Command`, per the docs:** they are functionally identical for control flow ("identical to conditional edges"). The stated decision rule is *state*: "Use `Command` when you need to **both** update state **and** route to a different node. If you only need to route without updating state, use conditional edges instead." Secondary difference: a conditional edge is a graph-topology artifact attached to a source node and is separately inspectable/renderable; a `Command` is a value returned by node code and only discoverable via its type annotation.

### 3. `Send` — dynamic fan-out with per-worker state

```python
Send(node: str, arg: Any, *, timeout: float | timedelta | TimeoutPolicy | None = None)
```
Import: `from langgraph.types import Send`.

`Send` exists for the case where the *number* of edges isn't known ahead of time **and** each downstream invocation needs a **different state object** than the main graph state. Canonical map-reduce shape:

```python
def continue_to_jokes(state: OverallState):
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

builder.add_conditional_edges("generate_topics", continue_to_jokes, ["generate_joke"])
```

Key points:
- `arg` is the state handed to *that* worker invocation; it may differ from and be narrower than the graph state. Results come back through **reducers** on the shared state (`Annotated[list, operator.add]`).
- `Send`s are returned from a **conditional edge's** routing function, or from `Command(goto=[Send(...), ...])`.
- Returning multiple `Send`s executes those nodes in parallel in one superstep. The router tutorial uses exactly this to hit GitHub/Notion/Slack concurrently before a `synthesize` node.
- `timeout` is per-pushed-task (a number or `timedelta` is treated as a hard `run_timeout`).

### 4. `START` / `END`, recursion limit

- `START` (`from langgraph.graph import START`, value `"__start__"`) is a virtual node representing the injection of user input. `add_edge(START, "node_a")` sets the entry point; `add_conditional_edges(START, routing_function)` gives a **conditional entry point**.
- `END` (`from langgraph.graph import END`, value `"__end__"`) is a virtual terminal node. `add_edge("node_a", END)`, or return `END` from a routing function, to stop.
- **Recursion limit** bounds the number of **supersteps** in a single execution, not the number of nodes. Exceeding it raises `GraphRecursionError` (`from langgraph.errors import GraphRecursionError`). **Default is 1000 supersteps as of v1.0.6.** Set it per-run as a *top-level* config key — explicitly **not** inside `configurable`:

  ```python
  graph.invoke(inputs, config={"recursion_limit": 5})
  ```
- Proactive handling (recommended over catching the error): the `RemainingSteps` managed value (`from langgraph.managed.is_last_step import RemainingSteps`) added as a state key tracks steps left, letting a node degrade gracefully. The raw counter is also readable at `config["metadata"]["langgraph_step"]`.
- A graph with a loop needs a conditional edge to `END` as its termination mechanism; the recursion limit is the backstop, not the design.

### 5. Can a node return a state update **and** a routing directive at once?

**Yes — and `Command` is the only way to do it.** This is the documented purpose of `Command`: "combine state updates and routing in a single function." The conditional-edges section carries a Tip pointing at `Command` for exactly this. A plain node returning a dict can only update state; the routing then has to come from a separate conditional edge evaluated after the node. Same applies inside tools: a tool returning `Command(update=..., goto=...)` mutates state and routes.

Caveat when a tool returns `Command` with `update`: you **must** include the message-history key (`messages`) in the update and it **must** contain a `ToolMessage`, or the history is invalid for the provider.

### 6. The canvas "router" node: which primitive, and what to capture

The scenario is *text input → router node → branch on instruction/tools/whatever → each branch feeds an arbitrary downstream node type*.

**Backing primitive: `add_conditional_edges(source, path, path_map)`.** Reasons, all doc-supported:

1. It is the primitive the docs themselves use for every visual router. `workflows-agents` "Routing" builds `llm_call_router` + `route_decision` + `add_conditional_edges(..., ["llm_call_1","llm_call_2","llm_call_3"])`. The Router multi-agent tutorial uses `add_conditional_edges("classify", route_to_agents, ["github","notion","slack"])`.
2. Destinations are **arbitrary node names** — the routing function returns names, and LangGraph doesn't care what kind of node sits behind a name (plain function, `ToolNode`, a compiled `create_agent`, or a subgraph, all of which are just nodes). This is what "output pipes into *any* node type" requires.
3. The edge set is a **topology artifact attached to the source node**, which is what a canvas needs to draw and persist. `Command` hides routing inside node code and is only renderable via a `Command[Literal[...]]` annotation — worse for a visual editor.

Use the other two as *modes* of the same router node rather than alternatives:
- **`Send`**, returned from the same routing function, when a branch must fan out to N parallel workers with per-worker payloads (the Router doc's "Multiple agents (parallel)" tab).
- **`Command(goto=...)`** when the router node must *also* write state in the same step (Router doc's "Single agent" tab uses `Command(goto=active_agent)`). If the canvas ever emits `Command`, it must **suppress static edges from that node** — otherwise both paths run.

**What the canvas must capture per outgoing edge:**

| Field | Why | Maps to |
|---|---|---|
| **Target node id** (required) | destination name | key/value in `path_map`, or the string the router returns |
| **Branch key / label** (required) | the value the routing function returns for this branch; must be `Hashable` and unique per source node | `path_map` key |
| **Predicate or classification spec** (per-branch, or one per node) | how the branch is chosen — LLM classification with a structured-output enum, or a deterministic expression over state | body of the generated `path` function |
| **Fan-out flag + per-worker payload template** (optional) | if this branch should emit `Send(target, arg)` instead of a bare name | `Send.arg` |
| **Default / fallback branch** | so an unmatched classification doesn't dead-end | `else` arm of `path`; often `END` |

**What the canvas must capture per router node** (not per edge): the **complete declared destination set**, emitted as either a `path_map` or a `Literal[...]` return annotation on the generated router function. This is not optional polish — omit it and every rendering of the graph (Studio included) draws the router as connected to every node in the graph. Also worth capturing: whether the router writes state (→ generate `Command`, and drop static edges) and any per-run `recursion_limit` override for graphs with loops.

One structural rule to enforce at the canvas level: **a node must not have both static outgoing edges and dynamic routing.** The docs state this twice (edges warning, `Command` warning) because both paths execute and the behaviour becomes hard to reason about.
