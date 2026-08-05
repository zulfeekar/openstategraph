Type: grilling
Status: open
Blocked by: 13, 24

## Question

Build the **cookbook / kitchen-sink workflow** — one workflow that exercises
everything the platform can do, end to end, visible in the editor.

The user's shape, restated:

```
question
  └─ router  (its only job is to classify)
       ├─ greeting   → direct reply                       → END
       ├─ help       → describe what this workflow can do → END
       ├─ offtopic   → polite decline                     → END
       ├─ info       → explain the schema / capabilities   → END
       └─ dataquery  → orchestrator
                         ├─ plans subtasks from the prompt
                         ├─ may spawn N subagents *dynamically*
                         ↓
                       grader ──revise──┐
                         │ pass         │ (loop back)
                         ↓              │
                       synthesise ──────┘
                         ↓
                       report → END
```

Plus: **multiple tools and functions**, and a **chat sidebar** that streams
progress and **highlights the node currently in charge** — with dynamically
spawned subagents appearing in the UI as they are created.

---

## Two requirements collide with how LangGraph works. Resolve these first.

### 1. "Subagents appear as nodes" — only one of the two subagent mechanisms allows it

There are two ways to get a subagent, and they differ in exactly the property
this feature needs:

| Mechanism | How it runs | Visible to the editor? |
| --- | --- | --- |
| **`SubAgentMiddleware`** (deep agents) | invoked *inside a tool function*; result returns as a `ToolMessage` | **No.** The docs are explicit: "Because subagents are called inside tool functions, LangGraph cannot statically discover them" — `get_state(subgraphs=True)` will not return subagent state. |
| **`Send` fan-out** to a real worker node | dynamic *tasks* against a declared node | **Yes.** Each task streams under its own namespace. |

So the ticket-08 answer ("subagents are isolated, invoked as tools") is right
about *semantics* but is the wrong mechanism for *this* feature. If the sidebar
must show subagents, the orchestrator has to fan out with **`Send` to a declared
worker node**, not spawn tool-subagents.

**Recommendation: `Send` fan-out.** It keeps isolation (each task gets only the
payload it is sent), and it is the only option the frontend can observe.
Tool-subagents stay available for cases where nobody needs to watch.

### 2. "Nodes are added dynamically" — LangGraph never adds a node at runtime

A compiled graph's topology is fixed. `Send` creates dynamic **tasks**, not
nodes. So the honest UI model is:

> The graph has **one** `worker` node. At runtime it has **N task instances**,
> and the canvas renders those instances stacked under (or fanned out from) the
> static node.

This matters because building "the frontend adds nodes" literally would mean
mutating `workflow.json` from runtime events — which breaks ticket 23's
one-directional compile seam. Runtime instances are **view state**, never
document state. Decide the visual (stacked badge with a count? fan of ghost
cards?) but not the storage: nothing runtime-derived is persisted.

---

## Decisions to settle

- **Router implementation.** A small classify agent with structured output is the
  obvious choice, but note the live finding from the Chinook run:
  `response_format` makes `create_agent` *raise* on malformed JSON. For a router
  that is a total outage. Options: constrain to a tool call, use
  `with_structured_output` and catch, or classify with a cheap keyword pre-pass
  and only escalate to a model when ambiguous. **Recommend: model classification
  with a deterministic fallback to `dataquery`** — a misroute is recoverable, a
  crash is not.
- **Router destination set.** Ticket 03's rule: the canvas must capture the
  *complete declared destination set*, or every renderer draws the router as
  connected to everything. Five branches means five declared destinations.
- **Orchestrator tier.** Which of the three tiers is it? A `create_deep_agent`
  with planning middleware is the batteries-included answer; a hand-written
  `StateGraph` node that emits `Send`s is the transparent one. **Recommend
  hand-written**, because the whole point is that the editor can *see* the
  fan-out, and a harness that plans internally is opaque for the same reason
  tool-subagents are.
- **Functions vs tools.** The user asked for both. Settle the distinction in the
  node catalogue: a *tool* is model-callable; a *function* is a deterministic
  step the graph calls. `share_of_total`, `format_report` are functions;
  `execute_sql` is a tool. They must not be one node type with a flag.
- **Report node.** Markdown artefact. Deep agents' filesystem middleware could
  write it to the virtual FS, which would also demonstrate that capability.
- **Streaming contract for the sidebar.** Two modes multiplexed over one SSE
  connection: `updates` (which node just ran → highlight) and `messages`
  (tokens, attributed by `metadata.langgraph_node`). **`subgraphs=True` is
  mandatory** — without it the inner agents' tokens never surface at all, which
  is the single most likely way this feature ships looking broken.

## Scope guard

This is a *cookbook*, so the temptation is to add every capability. The
constraint that keeps it useful: **every element must be something the editor can
render and a developer can inspect.** A capability that only exists inside a
harness demonstrates nothing about *this* product. That is the test for anything
proposed as an addition.

## Prerequisites

Blocked by 13 (router prototype) and 24 (grader node) — both are components this
assembles, and building them inside a kitchen-sink graph would settle their
design by accident.

Also wants, but is not blocked by:
- the TypeScript Chinook nodes moved to workflow scope and generated from the
  Pydantic schemas (currently global, and still describing the deleted mock)
- the canvas wired to `POST /ask`
