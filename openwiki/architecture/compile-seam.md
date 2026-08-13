---
title: The compile seam
description: How workflow.json becomes a LangGraph StateGraph — ports, bindings, plans and graph assembly.
type: page
---

# The compile seam

Source: [`backend/openstategraph/compile/workflow_compiler.py`](../../backend/openstategraph/compile/workflow_compiler.py)
and [`backend/openstategraph/compile/node_runtime.py`](../../backend/openstategraph/compile/node_runtime.py).

**OpenStateGraph is a single-target compiler, not a runtime.** The output is a plain
LangGraph `StateGraph`, so checkpointing, `interrupt()`, `Send` fan-out,
reducers and streaming are inherited, never reimplemented.

## Not every edge is a graph edge

The compiler's central rule — the target *port type* decides what an edge
means:

| Target port type | Meaning | Becomes |
| --- | --- | --- |
| `tool` | the tool is available to that agent | a **binding** (no graph edge) |
| `skill` | the text shapes the agent's prompt | a **binding** (no graph edge) |
| `text`, `result` | control flow | `add_edge` |
| `feedback` | a grader/approval rejection returning upstream | a **conditional** edge |
| `worker` | a `Send` dispatch target | `plan.fan_out`, no static edge |

Getting a tool link wrong would put the tool node *in the execution order*, so
it would run once by itself and again when the agent called it. Getting a
feedback link wrong would create an all-static cycle that can never terminate.

Port types per node type live in `DEFAULT_PORT_SPECS`, resolved through the
injectable `port_resolver` (`default_port_resolver`). An unknown port falls
back to control flow — wrong in the safe direction.

## Two phases

1. **`WorkflowCompiler.plan(document) -> CompiledPlan`** — pure data:
   `nodes`, `edges`, `conditional`, `tool_bindings`, `skill_bindings`,
   `fan_out`, `bound_only`, `entry`, `exits`, `warnings`. Directly assertable
   in a test ([`backend/tests/test_workflow_compiler.py`](../../backend/tests/test_workflow_compiler.py)).
2. **`WorkflowCompiler.build(...)`** — turns the plan into a `StateGraph`,
   calling a `node_factory` per node and wiring `START`/`END`.

Node **names are node ids**, sanitised by `safe_name()` (LangGraph reserves
`:`, and our ids look like `node:agent.llm-1`). Ids, not labels — LangGraph
treats a name as identity, so a rename must not break an interrupted thread.

## Node decides, edge dispatches

Routers, graders and `human.approval` all follow the same split: the node
returns a decision into state, and a *conditional edge* maps that decision to
a destination. Grader labels are `pass`/`revise`; approval labels are the
literal port ids `approved`/`rejected`.

## Graph-assembly parameters

`retry_policy`, `timeout`, `error_handler` and `cache_policy` are `add_node` /
`set_node_defaults` concerns, never node-family concerns. `build` sets a
graph-wide default and `_node_overrides()` applies the canvas's per-node
`maxRetries` / `timeoutSeconds`. `_default_error_handler` writes the failure
into `outputs[node]` so an exhausted node still produces evidence instead of
aborting the run.

## Node builders

`NodeRuntime._builders` (in `node_runtime.py`) is a registry keyed by node
type, so adding a node type is a registration:

`input.text`, `input.markdown`, `agent.llm`, `route.classifier`,
`route.grader`, `human.approval`, `orchestrate.supervisor`,
`orchestrate.worker`, `function.format_report`, `output.formatted`.

Resolved after the registry, by convention: `workflow.subgraph` and
`team.workflow` (both `_subgraph`), any `function.<name>` discovered in the
package, and finally a passthrough.

`NodeRuntime` is constructed once per request in `runtime_for()`
([`api/main.py`](../../backend/openstategraph/api/main.py)) so run, stream and resume
can never disagree about capabilities. It carries the tool/function
registries, a `document_loader` and a `package_loader` returning
`PackageAssets` (a child workflow
resolves tools from *its own* package), the memory `store`, the joined
`skills_context`, and the package's `workflow_middleware` slots.

Unresolved wiring is surfaced, never swallowed: `unresolved_tools`,
`unresolved_functions`, `unresolved_subgraphs` become run warnings — an agent
that silently loses its tools answers confidently from parametric knowledge.

## State

`RunState` (in `node_runtime.py`) is the shared schema. Any key more than one
node type can write carries a **named reducer** — `merge_decisions`,
`keep_max`, `keep_latest_nonempty` — because concurrent writers in one
superstep otherwise raise `InvalidUpdateError`.
