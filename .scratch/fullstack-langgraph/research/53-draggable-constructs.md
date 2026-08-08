# Ticket 53 — Inventory of draggable LangGraph / LangChain / deepagents constructs

Source: `docs-langchain` MCP server only (paths cited per section). Researched 2026-08-08.

## Summary table

| # | Construct | Exact API | Compiles to | Canvas mapping proposal |
|---|-----------|-----------|-------------|-------------------------|
| 1 | Handoffs | tool updating `active_agent` state + conditional routing; or middleware on one agent | graph assembly (subgraph variant) / node config (middleware variant) | **Edge kind**: "handoff" edge between two agent nodes; compiler emits handoff tool + router edge |
| 2 | Skills (deepagents) | `create_deep_agent(skills=["/skills/"])`, `SkillsMiddleware`; `SKILL.md` + YAML frontmatter | node config (a field) | **Card/binding**: Skill card attached to an agent's `skills` bus port; card body = frontmatter + path |
| 3 | Subagents (sync) | `create_deep_agent(subagents=[SubAgent dict \| CompiledSubAgent])`, `SubAgentMiddleware`, `task()` tool | node config | **Card/binding**: Subagent card bound to agent's `subagents` bus; a subgraph node bound this way compiles to `CompiledSubAgent(name, description, graph)` |
| 4 | Async subagents | `update_async_task` / `cancel_async_task`, Agent Protocol server (preview, deepagents 0.5.0) | node config + external deployment | **Defer** — preview API, needs a server; not palette-ready |
| 5 | Memory / Store | `builder.compile(store=InMemoryStore())`, `BaseStore.put/search`, `runtime.store` in nodes | graph assembly (workflow-level attachment) | **Workflow resource node**: Store card, binding edges to nodes that read/write; namespace as config |
| 6 | deepagents memory files | `create_deep_agent(memory=["/memories/AGENTS.md"])` + backend | node config | **Field** on Deep Agent node (file-path list), not a canvas element |
| 7 | Backends / sandboxes | `backend=` on `create_deep_agent`: `StateBackend`, `StoreBackend`, `FilesystemBackend(root_dir)`, `CompositeBackend`, `LocalShellBackend`, `ContextHubBackend`, sandbox providers (E2B, Modal, Daytona, ...) | node config | **Card/binding**: Backend capability card bound to a Deep Agent's `backend` port (exactly-one cardinality) |
| 8 | Cache policy | `add_node(..., cache_policy=CachePolicy(ttl, key_func))`; `set_node_defaults(cache_policy=...)` | graph assembly | **Assignment/badge** on any node + workflow-defaults panel; never a node of its own |
| 9 | `Command(goto=)` | node returns `Command(goto="node", update={...})`; also `graph=Command.PARENT` | graph assembly (declared destinations) | **Edge kind**: dashed "dynamic" edge from node to each possible goto target; mutually exclusive with static edges from same node |
| 10 | `add_sequence` | `StateGraph(State).add_sequence([n1, n2, n3])` | graph assembly (pure sugar for chained `add_node`+`add_edge`) | **No new element** — compiler optimization when a linear chain is detected; optionally a visual group container |
| 11 | Parallel branches + join | multiple `add_edge` fan-out; barrier via `add_node(d, defer=True)` | graph assembly | Fan-out already expressible; **`defer` = boolean badge/flag on a join node** ("wait for all branches") |
| 12 | Send fan-out (map-reduce) | conditional edge returning `[Send("node", payload) for ...]` | graph assembly | Already the Orchestrator/Worker pattern; **edge kind** "map" for generic non-orchestrator fan-out |
| 13 | Streaming taps | `stream(stream_mode=[...], version="v2")`, `get_stream_writer()` in a node | runtime invocation, not workflow.json | **Not draggable** — invocation-time; only `get_stream_writer` custom emits could be a node config toggle |
| 14 | Evaluator-optimizer | pattern: generator + `with_structured_output(Feedback)` evaluator + conditional edge loop | graph assembly (composition of existing nodes) | Already covered by Grader + typed feedback cycle; **template**, not a new element |
| 15 | Interpreters | QuickJS middleware via `middleware=` on `create_deep_agent`; adds `eval` tool, stateful across calls | node config | **Card/binding**: Interpreter capability card on agent's middleware slot table |
| 16 | Node defaults (retry/timeout/error_handler) | `set_node_defaults(retry_policy=, timeout=, cache_policy=, error_handler=)`, per-node override at `add_node` | graph assembly | Workflow settings panel + per-node override badges (confirms existing CLAUDE.md rule) |
| 17 | Per-tool HITL on subagents | `SubAgent.interrupt_on: dict[str, bool | InterruptOnConfig]` | node config | Field on the Subagent card, inherits from parent agent by default |

---

## 1. Handoffs

Docs: `/oss/python/langchain/multi-agent/handoffs.mdx`, `/oss/python/langchain/multi-agent/index.mdx`.

Not a single API — a pattern with two documented implementations:
- **Single agent with middleware** (recommended "for most handoffs use cases"): tools update a state variable (`current_step` / `active_agent`); middleware swaps the prompt/tools. Compiles to *node config* on one agent.
- **Multiple agent subgraphs**: each agent a graph node; handoff tools set `active_agent`; a conditional edge routes on it. The handoff tool must append the triggering `AIMessage` + an acknowledging `ToolMessage` (matching `tool_call_id`) or history is malformed. Compiles to *graph assembly*.

Canvas: a distinct **"handoff" edge kind** between agent nodes. The compiler generates the `transfer_to_X` tool, the `ToolMessage` pair, and the `active_agent` router. The single-agent variant is instead a config option ("stages") on one agent node.

## 2. Skills

Docs: `/oss/python/deepagents/skills.mdx`, `/oss/python/langchain/multi-agent/skills.mdx`.

deepagents: `create_deep_agent(skills=["./path/skills/"])` — each skill is a directory with `SKILL.md` (YAML frontmatter `name`/`description` + instructions; optional `references/`, `scripts/`, assets). `SkillsMiddleware` does 3-level progressive disclosure (frontmatter at startup → body on invoke → resources on demand). Plain LangChain has no built-in: the docs implement it as a `load_skill` tool on `create_agent`.

Node config (a path list / middleware). Canvas: **Skill cards** attachable to an agent's `skills` bus port; a subagent card can carry its own `skills` field (isolated `SkillsMiddleware` instance, no inheritance except the general-purpose subagent).

## 3. Subagents (sync)

Docs: `/oss/python/deepagents/subagents.mdx`.

`create_deep_agent(subagents=[...])` where each entry is either:
- **`SubAgent` dict**: `name`*, `description`*, `system_prompt`*, optional `tools`, `model`, `middleware`, `interrupt_on`, `skills`, `response_format`, `permissions`. Tool/model/interrupt_on/permissions inherit from the main agent; system_prompt/middleware/skills do not.
- **`CompiledSubAgent(name, description, graph)`** — any prebuilt compiled LangGraph.

`SubAgentMiddleware` attaches the `task()` tool; only present when ≥1 sync subagent exists (`general_purpose_subagent.enabled = False` is the off switch; excluding the middleware raises `ValueError`).

Node config. Canvas (feeds ticket 52 Team members): **Subagent cards** on a `subagents` bus port. A canvas subgraph wired to that bus compiles to `CompiledSubAgent` — the strongest new element, since it makes any workflow reusable as a team member. Consistent with the "subagents are isolated" rule: the binding carries name+description only, never state.

## 4. Async subagents

Docs: `/oss/python/deepagents/async-subagents.mdx`. Preview in deepagents 0.5.0; requires an Agent Protocol server (LangSmith Deployments or self-hosted). Supervisor can `update_async_task` / `cancel_async_task`. **Refuted for the palette now** — unstable API plus a deployment dependency.

## 5. Memory / Store (LangGraph long-term)

Docs: `/oss/python/langgraph/stores.mdx`, `/oss/python/langgraph/add-memory.mdx`.

`graph = builder.compile(store=InMemoryStore())` (or any `BaseStore`); nodes access via `runtime.store.search(namespace, query=, limit=)` / `runtime.store.put(namespace, key, value)`; namespaces are tuples like `(user_id, "memories")`.

Graph assembly: the store is attached at compile, per workflow. Canvas: a **workflow-level Store resource card** with binding edges to nodes that use it; namespace template as config on the binding. (Serialize as a named store reference in workflow.json — reducer-enum-style, never an object.)

## 6. deepagents memory files

Docs: `/oss/python/deepagents/memory.mdx`. `create_deep_agent(memory=["/memories/AGENTS.md"])` — file paths whose storage location is the backend. Pure node config field; no canvas element needed.

## 7. Backends and sandboxes

Docs: `/oss/python/deepagents/backends.mdx`, `/oss/python/deepagents/sandboxes.mdx`.

`backend=` on `create_deep_agent`: `StateBackend()` (default, ephemeral in-state VFS), `StoreBackend()` (durable across threads via LangGraph store), `FilesystemBackend(root_dir=abs_path)`, `LocalShellBackend(root_dir, env)` (filesystem + shell, no isolation), `ContextHubBackend("repo")`, `CompositeBackend` (router mixing backends by path prefix), or a sandbox provider (LangSmith, AgentCore, Daytona, Deno, E2B, Modal, Runloop, local VFS) which adds an `execute` tool. `FilesystemMiddleware` (with a `tools` allowlist) restricts filesystem tools per agent/subagent.

Node config. Canvas: **Backend capability card** bound to a Deep Agent's `backend` port, `maxConnections: 1`. Sandbox providers are concrete variants of the same card family.

## 8. Cache policy

Docs: `/oss/python/langgraph/graph-api.mdx` (l.496–513), `/oss/python/langgraph/use-graph-api.mdx` (l.889–908, 1044–1052).

`builder.add_node("n", fn, cache_policy=CachePolicy(ttl=120))` (`key_func` optional); `set_node_defaults(cache_policy=...)` for graph-wide, per-node wins, applied at compile; defaults do **not** apply to error-handler nodes and are not inherited by subgraphs. Graph assembly — exactly per the CLAUDE.md rule. Canvas: an **assignment/badge on a node** plus a workflow-defaults panel. Not draggable as a node.

## 9. `Command(goto=)` dynamic edges

Docs: `/oss/python/langgraph/graph-api.mdx` (l.612–669).

A node returns `Command(goto="other_node", update={...})`; `graph=Command.PARENT` targets the parent graph (this is also the subgraph-handoff mechanism). Doc warning: Command adds edges *in addition to* static ones — "use either Command or static edges to route to the next nodes, not both."

Graph assembly, but only expressible if the workflow declares possible destinations. Canvas: a **"dynamic" edge kind** (dashed) from a node to each allowed goto target; validation rule forbids mixing static and dynamic out-edges on one node (straight from the docs warning).

## 10. `add_sequence`

Docs: `/oss/python/langgraph/use-graph-api.mdx` (l.361, 1094–1222). `StateGraph(State).add_sequence([step_1, step_2, step_3])` — shorthand for chained add_node/add_edge, `langgraph>=0.2.46`. **Refuted as a canvas element**: a linear chain of nodes already expresses it; at most a compiler peephole.

## 11. Parallel branches + deferred join

Docs: `/oss/python/langgraph/use-graph-api.mdx` (l.1370–1401). Static fan-out is plain multiple `add_edge`; the barrier is `builder.add_node(d, defer=True)` — the node "will not execute until all pending tasks are finished," even across unequal-length branches. Graph assembly. Canvas: **`defer` boolean on any node with >1 in-edge** ("wait for all branches"), surfaced as a barrier badge. Cheap and high-value.

## 12. Send fan-out (map-reduce)

Docs: `/oss/python/langgraph/graph-api.mdx` (l.612), `/oss/python/langgraph/use-graph-api.mdx` (l.1507): conditional edge returns `[Send("generate_joke", {"subject": s}) for s in subjects]` — dynamic edge count, per-branch private state. Already the Orchestrator/Worker compile target. Optional generalization: a **"map" edge kind** (expression selecting a list state key → target node) for fan-out without the full orchestrator. Reminder: fan-in keys need named reducers (existing CLAUDE.md rule).

## 13. Streaming taps

Docs: `/oss/python/langgraph/streaming.mdx`, `/oss/python/langgraph/event-streaming.mdx`. `graph.stream(inputs, stream_mode=["updates","custom"], version="v2")` yields uniform `StreamPart` dicts (`values|updates|messages|custom|checkpoints|tasks|debug`); v1.2 adds typed per-projection event-streaming iterators. Inside a node, `get_stream_writer()` emits custom chunks. **Refuted as a canvas element**: stream modes are invocation parameters, not graph structure. Only candidate: an "emit progress" toggle (node config) that compiles to `get_stream_writer` calls.

## 14. Evaluator-optimizer

Docs: `/oss/python/langgraph/workflows-agents.mdx` (l.773–840). Generator node + evaluator using `llm.with_structured_output(Feedback)` + conditional edge routing back or to END. **No new API** — it is exactly the existing Grader + typed-feedback cycle. Ship as a palette *template*, not an element.

## 15. Interpreters

Docs: `/oss/python/deepagents/interpreters.mdx`. QuickJS interpreter middleware passed via `middleware=` on `create_deep_agent`; adds an `eval` tool running JavaScript with optional variable persistence between calls; for composing tools in-code (loops, retries, parallel batches) vs sandboxes for OS-level work. Node config: an **Interpreter capability card** contributing a named slot to the middleware slot table.

## 16–17. Node defaults and per-subagent HITL

`set_node_defaults(retry_policy=, timeout=, cache_policy=, error_handler=)` (`/oss/python/langgraph/use-graph-api.mdx` l.889) confirms the existing "graph-assembly parameters" rule — workflow settings panel + per-node badges. `SubAgent.interrupt_on: dict[str, bool | InterruptOnConfig]` (`/oss/python/deepagents/subagents.mdx`) is a field on the Subagent card, inheriting from the parent agent.

---

## Doc pages consulted

- /oss/python/langgraph/graph-api.mdx, use-graph-api.mdx, stores.mdx, add-memory.mdx, streaming.mdx, workflows-agents.mdx
- /oss/python/langchain/multi-agent/{index,handoffs,skills,subagents}.mdx
- /oss/python/deepagents/{skills,subagents,async-subagents,backends,sandboxes,memory,interpreters}.mdx
