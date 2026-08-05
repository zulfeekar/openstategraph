Type: grilling
Status: resolved (2026-08-05) — backend graph mechanics, TS node registration, worker tool-use bug, and the streaming/sidebar contract are all built and verified
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

## Backend resolution (2026-08-05)

Both open questions above are answered and built, backend-only, per
[the loop/graph/harness decision doc](decisions/loop-graph-harness.md):

- **`Send` fan-out to a declared worker node** — recommended above, now real.
  `IOrchestrator -> BaseOrchestrator -> Orchestrator` (`backend/dyflow/abc/orchestrator.py`,
  the same ladder as Router/Grader) plans a bounded, generation-scoped subtask
  list; `WorkflowCompiler` recognises a `worker`-typed port as a fan-out
  declaration (a third category alongside control flow and tool/skill binding)
  and compiles it to `add_conditional_edges` returning `Send` objects. Verified
  against the real installed LangGraph, not assumed: a `Send` payload replaces,
  never merges with, the dispatched node's state.
- **Functions vs. tools, settled as recommended**: `function.format_report` is
  a deterministic graph step the compiler always runs (no model in the
  decision); Chinook's SQL execution stays a tool, chosen by the worker agent
  mid-loop. Different node types, not one type with a flag, exactly as
  recommended.
- **The revise loop re-enters the fan-out/join subgraph**, not just a single
  agent node — proven in `backend/tests/test_orchestrator_graph.py` (10 tests):
  dispatch count, result-join-by-id, deterministic report ordering, a real
  replan (not a bare retry) on `revise`, and that the recursion budget still
  terminates a persistently-failing loop with fan-out inside it.
- **Two real bugs surfaced only by combining fan-out with a revise loop**, both
  now fixed and regression-tested: a bare-scalar `answer` field written by two
  nodes in the same superstep (`InvalidUpdateError`, fixed with a named
  reducer — `test_answer_channel_concurrency.py`), and subtask ids colliding
  across replans, silently blending stale and fresh results (fixed with
  generation-scoped ids — `test_orchestrator.py`).
## Worker tool-use bug — root-caused and fixed (2026-08-05)

The "worker tool-use reliability" gap noted above was not a model/prompting
limitation after all: `WORKER_TYPE`'s compiler port-spec table never declared
a `tools` or `skill` port, so an edge into either silently fell through to
"ordinary control flow" instead of registering as a binding — a worker with
Chinook tools wired on the canvas ran with **zero** tools every time,
regardless of prompt wording. Fixed in `workflow_compiler.py`
(`DEFAULT_PORT_SPECS[WORKER_TYPE]`), with a regression test mirroring the
agent's own binding coverage. Verified live, twice, against
`ollama:gpt-oss:120b-cloud`: correct answers produced by the real tool
sequence (`chinook_list_tables` → `chinook_get_table_schema` →
`chinook_execute_sql`), confirmed by inspecting each message's `tool_calls`
directly, not by the answer's plausibility. Full account in
[the decision doc](decisions/loop-graph-harness.md).

## TypeScript node registration — done (2026-08-05)

`OrchestratorNode.ts`, `WorkerNode.ts`, `FormatReportNode.ts`
(`src/nodes/orchestrate/`), registered in the palette alongside Router and
Grader. A developer can now drag all three onto the canvas.

## Streaming/sidebar contract — done (2026-08-05)

`POST /api/runs/stream` (`backend/dyflow/api/main.py`) streams the compiled
graph via `graph.stream(..., stream_mode=["updates", "messages"],
subgraphs=True)`, translated to SSE frames: `update` (a node just acted),
`token` (a message chunk), `error`, and a final `done` carrying the same
shape `/api/runs` returns — folded from the incremental `updates` payloads
using the *same* named reducers `RunState` declares
(`keep_latest_nonempty`, `merge_decisions`), so the two endpoints cannot
silently disagree about what "the final answer" means.

**One assumption from this ticket's original notes turned out to be wrong,
checked directly against the installed LangGraph rather than left as a
guess:** `namespace` does not distinguish two `Send`-dispatched instances of
the *same* worker node — a dispatched task shares its parent's checkpoint
namespace, unlike an actual nested subgraph, which does get its own. So
every concurrently dispatched worker reports `namespace: []`, and the task
id read from `worker_results` is what the sidebar actually keys on to tell
dispatched instances apart. `subgraphs=True` is kept regardless, since it
costs nothing and would matter for a future node type that does nest a real
subgraph.

`RuntimeClient.runStream()` (`src/core/runtime/RuntimeClient.ts`) is the
frontend's SSE consumer — `fetch` plus manual frame-buffering rather than
`EventSource`, since `EventSource` cannot POST a body and the workflow
document has to go in the request. `AskPanel.tsx` calls it and selects
`event.node` on the canvas as each `update` arrives — the "highlight
whichever node is currently in charge" requirement — with a live "Activity"
feed showing each dispatched worker's task id as it appears, before the
final answer replaces it. Verified live in the browser against a real
`uvicorn` backend: a three-attempt revise loop streamed correctly, the
canvas selection followed the run in real time, and the final "path taken"
matched the SSE frames exactly.

22 new RuntimeClient tests (frame parsing, mid-frame chunk splits, error and
missing-done paths) plus 6 new backend tests (per-node update events, the
worker task-id distinguishing signal, malformed-document handling). No new
tests were added for `AskPanel.tsx` itself — this codebase has no React
component test infrastructure anywhere (`grep` for `.test.tsx` returns
nothing), and introducing one is a standing-infrastructure decision bigger
than this ticket; the component is thin glue over the now-well-tested
`RuntimeClient`, consistent with this project's existing "canvas/view stays
deliberately untested, core is unit-tested" split (ticket 11).

This closes every part of the ticket's original shape.
