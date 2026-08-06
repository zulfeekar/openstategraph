# Map: Full-stack LangGraph workflow platform

Label: `wayfinder:map`

## Destination

A production-ready, full-stack platform — a **Python LangGraph runtime** plus the **TypeScript editor** — in which *every* domain concept (node, edge, tool, provider, workflow) derives from one uniform, extensible base hierarchy (`IEntity → Base* → concrete`), defined **once** in Pydantic and **generated** into TypeScript. Reached when: a user can author, persist, compose and run multi-workflow graphs end to end, under test, with no hand-mirrored types.

## Notes

**Domain.** Visual AI workflow builder. Editor exists (phase 1: TS / React 19 / JointJS core / MVC engine, ~17k lines, runs against a Mock provider). Runtime does not exist yet.

**Authority.** LangGraph and LangChain facts come **only** from the `docs-langchain` MCP server. Nothing invented, nothing recalled from memory. Two concepts are already pinned:
- **Graph engineering** = `StateGraph` — nodes, conditional edges, shared state, `Send` fan-out, subgraphs.
- **Loop** = `create_agent` (ReAct). It *returns a compiled LangGraph*, so an agent drops into a larger `StateGraph` as a node or subgraph.
- Therefore: **canvas = StateGraph, Agent node = the loop, workflow composition = subgraphs.**

**Skills each session should consult.** `/grilling` and `/domain-modeling` for decisions · `/research` for facts · `/tdd` for all implementation · `/codebase-design` when shaping a module seam.

**Working model for "bidirectional"** (proposed, formalised by tickets `14`/`15`/`18` — not yet ratified). It is **two one-way channels over disjoint concerns**, never a round-trip:

| Channel | Direction | Owns | Source of truth |
| --- | --- | --- | --- |
| Structure | canvas → code | nodes, edges, branches | `workflow.json` |
| Capability | code → canvas | what a node can *do* — functions, tools, skills | the `.py` files |

They cannot collide because they own different things: the canvas never writes `functions/`, and code never rewrites topology. This is precisely where round-trip UML tooling failed — it tried to own both directions for the same artifact. The capability channel reuses the existing `Registry<T>` seam: a discovered function is a registration arriving at runtime from the filesystem rather than at boot from a module.

**Token discipline.** `graphify-out/graph.json` exists (1120 nodes, 1936 edges, 69 communities). Query the graph — `graphify explain "X"`, `graphify path "A" "B"` — *before* reading source files. Rebuild with `graphify update .` after structural changes.

**Standing preferences.** See [`CLAUDE.md`](../../CLAUDE.md) — it is the binding statement of the architecture principles (no god classes, `I*`→`Abstract*`→`Base*`→concrete, SOLID applied concretely, DRY, small named packages, the one-way layering rule). Read it before any implementation ticket.

**Two god classes are already over budget** and must not be added to: `WorkflowController` (38 public members, 7 responsibilities) and `WorkflowModel` (41). Decomposition is ticket `17`, blocked behind the test suite.

## Decisions so far

- [Pydantic → TypeScript codegen](issues/02-pydantic-to-ts.md) — Toolchain: `model_json_schema()` → **json-schema-to-typescript** (MIT, active) via a small project-owned script; generated output committed, CI gated on `git diff --exit-code`. quicktype is disqualified (it *merges* union members and destroys the tagged union); `pydantic-to-typescript` is unmaintained — copy its logic, don't depend on it. **Pydantic flattens inheritance**: `model_json_schema()` inlines inherited fields and emits no `allOf`/`$ref`, so base classes never reach the generator ([pydantic#12071](https://github.com/pydantic/pydantic/issues/12071)). Generated TS can therefore never say `extends` — at best named **intersections** via a post-processor. Discriminated unions survive fully (require `Literal` discriminants with no default, plus `extra="forbid"`); generics are monomorphised.
- [LangGraph routing primitives](issues/03-langgraph-routing.md) — Router node = **`add_conditional_edges(source, path, path_map)`**; `path` returns a node name, a list, `END`, or `Send` objects, and destinations may be *any* node type. `Command(goto=...)` is not an alternative but the mode used when the router must also write state (`Command(update=..., goto=...)`, needs a `Command[Literal[...]]` annotation); `Send(node, arg)` is the fan-out mode. Canvas must capture **per edge**: target id, branch key (`Hashable`), predicate spec, optional fan-out + payload template, fallback — and **per router**: the complete declared destination set, or every renderer draws the router as connected to every node. **Hard rule: a node must never have both static edges and dynamic routing — both execute.**
- [Agents, tools & subagents](issues/06-langgraph-agents-tools.md) — Standalone **`ToolNode`** is supported and documented (a whole graph can be `START → ToolNode`), accepting raw tool-call dicts with no model and no loop — so "function-calling node on its own" is a first-class node type. `create_agent` takes **`system_prompt:`** (not `prompt=`); dynamic prompts go through `@wrap_model_call` middleware. For subagents use **agent-as-tool via `SubAgentMiddleware`** (`deepagents`), which injects a `task` tool from `{name, description, system_prompt, model, tools}` specs — `create_supervisor` is documented as unmaintained and swarm is absent from current docs.
- [LangGraph persistence](issues/04-langgraph-persistence.md) + [composition](issues/05-langgraph-composition.md) — LangGraph is a **runtime-state system only**. Runtime is fully covered (checkpointer packages for SQLite/Postgres/etc., mandatory `thread_id`, `get_state_history`, replay-vs-fork time travel, `Store` for cross-thread memory). **Authoring state: zero opinion, entirely ours** — there is no serialisable graph-definition format; graphs are Python modules registered by import path in `langgraph.json`, and "edge topology is not persisted in the checkpoint". Assistants are config-only and not in OSS. Subgraph schemas *are* introspectable, but only via the Agent Server API (`GET /assistants/{id}/subgraphs?recurse=true`) and best-effort — derive ports from our own definition and use introspection to verify. **Sharp edge: node names are identity.** Renaming or removing a node hard-breaks an interrupted thread, and subgraphs called *inside* a node get `checkpoint_ns` by call order, so reordering makes one load the wrong state.
- [Editor ↔ runtime boundary](issues/07-runtime-boundary.md) — **LangGraph Agent Server is ruled out on licence.** `langgraph` itself is MIT, but the server (`langgraph-api`, `langgraph-runtime-inmem` — everything behind `langgraph dev`/`up`/`build`) is **Elastic License 2.0**: source-available, not OSI-open, forbids providing the software as a hosted service, validates a licence key in every deployment mode, and self-hosting needs an Enterprise plan plus egress to `beacon.langchain.com`. Fails twice for an OSS project. **Build our own FastAPI** on the MIT pieces (`langgraph`, `langgraph-checkpoint-postgres`, `langgraph-sdk` as client only), copying Agent Server's *shape* (assistants/threads/runs, `stream_mode`, SSE envelope) so a later swap stays cheap. The browser must never reach a runtime directly — proxy through our backend, keys server-side. Streaming is SSE with `event:` = stream mode, so token-level (`messages-tuple`, attributed by `metadata.langgraph_node`) and node-level (`updates`, `tasks`) multiplex on one connection. Canvas status enum: `pending|running|complete|error|interrupted|timeout`. Constraint: at most one run per thread concurrently.
- [Context management](issues/22-context-management.md) — **"Autocompaction" does not exist as an API** — no `AutoCompactionMiddleware`, no `autocompact` parameter. What the term means in practice is deep agents' always-on *context compression* = **offloading** (tool payloads over 20,000 tokens replaced by a file reference plus the first 10 lines; deterministic, no LLM, no knob) plus **summarization**. Three real mechanisms, cleanly separable: `SummarizationMiddleware` (LLM-backed, replaces old messages with a summary; inert unless `trigger` is set — the `deepagents` variant instead fires at 85% of `max_input_tokens` and keeps 10%); `ContextEditingMiddleware` + `ClearToolUsesEdit` (deterministic, no LLM, replaces old *tool output* with a placeholder — and `ClearToolUsesEdit` is the only `ContextEdit`, so **no thinking-block strategy is documented at the LangChain layer**); and `Store` (cross-thread `(namespace, key)` documents) as the counterpart to the thread-scoped checkpointer. A "deep agent" is both a real harness and a reproducible middleware composition — `deepagents` adds Filesystem, Skills, Memory, Rubric, Async subagents and more on top of `SubAgentMiddleware`; planning (`TodoListMiddleware`) is langchain's and opt-in. **Consequence for the editor: the Agent node's full config surface is 60+ fields**, so a `harness` preset acting as a master dial plus progressive disclosure is mandatory, not a nicety. Two cross-field validations for `WorkflowValidator`: HITL and `thread_limit` require a checkpointer; fractional triggers require a model profile.
- [Runtime agnosticism](issues/23-runtime-agnosticism.md) — **Hypothesis confirmed, and stronger than posed: an `IOrchestrator` with `addNode`/`addEdge` is *unbindable*, not merely leaky.** No competitor accepts an authorable serialisable graph, so every target needs a compiler by definition. Microsoft's Declarative Workflows 1.0 is a sequential action list in Power Fx with **no fan-out action at all**; ADK Agent Config is experimental, Gemini-only and explicitly excludes graphs; Vercel (`'use workflow'`) and the OpenAI Agents SDK have no topology object. LangGraph has no round-trip either (`langgraph.json` is a code pointer; `Graph.to_json()` has no inverse) — so **our JSON is doing real work**. **Decision: (b) go deep on LangGraph and document the port cost.** All candidates are MIT/Apache-2.0, so there is no licence pressure, and the field is *converging* on LangGraph's shape (MAF is modified-Pregel with executors/edges/fan-in barriers; ADK 2.0 added a graph engine and durable HITL) — the intersection widens over time, so keep the JSON expressive and pay later. Option (c) capability flags is "dishonest by construction": the flags that matter are exactly the ones no second runtime satisfies. Second-compiler cost ≈ one engineer-quarter, but the real price is a permanent N-way multiplier on every new node type. **Surrendered if we ever chase portability:** `Send`/dynamic map-reduce, reducer state merging, checkpoint namespacing/time-travel/fork, `interrupt()` anywhere (degrades to tool-boundary approvals), `Command(goto=, graph=Command.PARENT)`, per-`Send` timeouts. **Four cheap guardrails adopted now** (see CLAUDE.md): expressions as a JSON AST, reducers as a named enum, a one-directional compile seam, and our own runtime vocabulary. Precedent: [Oracle Agent Spec](https://github.com/oracle/agent-spec) is the only multi-runtime compiler that exists; n8n, Dify, Langflow and Flowise all own their executor.
- [Universal entity hierarchy](issues/08-entity-hierarchy.md) — **The crux, resolved.** The universal root **already exists and is one field wide**: `IIdentifiable { id }`. Do not add `kind`/`version`/`metadata` to it — each fails for some family (an edge has no position, a provider is never placed, a tool is not selectable), and a root carrying all of it is the god base class CLAUDE.md forbids. Hierarchy is **shallow at the root, deep only inside a family**. Two runtime facts keep it shallow, not taste: a LangGraph node is a **function**, so a class tree models config and never dispatch; and **Pydantic flattens inheritance**, so any depth is invisible across the generated boundary. **Middleware: `resolveMiddleware()` returns an ordered name-keyed slot table, not a list.** Forced by the docs — list position means *three different things* (`before_*` first→last, `after_*` **reverse**, `wrap_*` nested), so `super() + [mine]` means "before-last, after-**first**, innermost-wrap" and any single-number position scheme (append, prepend, priority int) expresses something that does not exist. `create_deep_agent` already solved it: a **fixed 12-slot order** with documented semantic reasons per slot (Skills before Filesystem so skill metadata precedes file tools; Memory after prompt caching to avoid invalidating the cache prefix), user middleware in **one named slot**, and **name-matched in-place replacement** rather than accumulation. So `create_deep_agent` is `create_agent` **+ a fixed slot assembly, not + subclassing** — the library expresses the relationship as *data*, which collapses the (A)/(B) tension: **DeepAgentNode is a sibling of ReactAgentNode**, differing by a registered preset, and a fourth harness needs no class and no `core/` edit. **Retry was the big surprise: it is not a node concern at all.** `retry_policy` is an **`add_node` parameter** available to every family, and `StateGraph.set_node_defaults(...)` applies retry/timeout/`error_handler` graph-wide with per-node override — so it lives on the *workflow* and compiles to graph assembly, never on a base class. CLAUDE.md's collaborator-not-superclass boundary, confirmed by the library. Token accounting and logging stay deliberately **not** unified (middleware for agents, callbacks otherwise) — unifying them would invent an abstraction the runtime lacks. **Decided with the user:** three separately registered agent tiers (illegal states unrepresentable, vs 60+ union fields on one card; accepted cost is that switching tier drops edges, mitigated by a convert-tier command); prebuilt shapes are **multi-node canvas templates**, since a shape is a *topology* and a preset cannot express one; directory is **`abc/`**. Verified rather than assumed: a workflow-local `abc/` **cannot** shadow stdlib `abc`, because `abc` is in `sys.modules` before user code runs — but `json/`/`csv/`/`secrets/` *would*, so discovery must import workflows as a package. **`INodeDefinition`/`INodeExecutor` survives in Python and dies in TypeScript** — ticket 07 bars the browser from executing, so `core/execution` + `core/providers` are phase-1 artefacts scheduled for deletion, which is why ticket 11 logged their coverage as a gap rather than a debt. **Buses: `tools` only — and `skill` must become `skills`**, since `SkillsMiddleware` takes a list and a single-slot port silently caps it at one; needs a serializer migration, because ticket 19's loader drops links to vanished ports with only a warning.
- [Graph vs loop in the editor](issues/09-graph-vs-loop-ux.md) — **One document type**: the canvas *is* a `StateGraph` and a loop is a node in it; the graph/loop distinction is already carried by the node type (ticket 08's three tiers), so a second authorable kind would fork palette, inspector, serializer and compiler to express one field. **Conditional edges split by half**: the **predicate (JSON AST) lives on the router node**, the **branch key on the edge**. Forced, not stylistic — `add_conditional_edges` takes *one* `path` function, so N edge-predicates would be merged at compile time with merge order silently deciding precedence; ticket 03's requirement that the canvas capture the router's complete destination set makes an edge-scattered predicate unrenderable; and ticket 03's both-execute hard rule is one check on a node versus a whole-graph pass over edges. **The Agent loop is inspectable but not expandable** — its internals are *generated*, so an editable canvas group would imply reading runtime structure back into the model, which ticket 23's one-directional seam forbids. Preview comes from `compiled.get_graph(xray=True).draw_mermaid()`, which is the loop as it actually compiled rather than an approximation that can drift. **Hard rule found: never `draw_mermaid_png()`** — it defaults to posting the graph to the **Mermaid.Ink API**, shipping a private workflow's structure off the machine; `draw_mermaid()` is text, offline, no extra dependency. **Cycles: the port *type* is the gate, so the rule stops being about cycles.** The ticket-11 finding reframed it — cycles were never *forbidden*, they were **inexpressible** (no input accepts a `result`). So open one deliberate typed path: `GraderNode.revise: feedback` → a new single-slot `AgentNode.feedback` input. Accidental cycles stay undrawable; evaluator-optimizer becomes two clicks; no rule relaxation. Three termination layers, only the middle ours: a cycle must contain ≥1 conditional edge (`acyclicRule` becomes `staticCycleRule`); `recursion_limit` surfaced as workflow config — a **standalone `config` key, not inside `configurable`**, default 1000 Python / 25 JS; and a generated **`RemainingSteps`** guard so a runaway loop routes to `END` instead of raising `GraphRecursionError`. **UI honesty requirement: the budget counts supersteps, not iterations** — the docs' own fan-out example costs four supersteps per lap, so "max iterations" would mean two laps in one graph and ten in another. `staticCycleRule` is **unreachable by construction today**, exactly as `acyclicRule` was — kept as defence for future node types and exercised via `registerLoopableType`; recorded so nobody rediscovers the dead code and deletes it.
- [Decompose the god classes](issues/17-decompose-god-classes.md) — **`WorkflowController`: 41 public members -> 11**, one reason to change (which collaborators exist), split into `NodeEditor` (9), `EdgeEditor` (4), `GroupingController` (4), `ClipboardController` (4), `HistoryController` (6), `DocumentController` (5), `SelectionActions` (5). **Explicitly not a façade** — the ticket's own warning decided it: forwarding 41 methods is the same god class with an extra layer and leaves every consumer depending on everything. Making the surface explicit closed two leaks: `AutoLayout` was reaching through `controller.commands.transact(...)`, handing a canvas feature the whole command stack (`execute`, `clear`) to group a batch of moves; and the toolbar subscribed to the stack's `changed` event, re-rendering on every model change to learn something that only changes at an undo boundary. `registry` and the clipboard *service* turned out to have **no external consumers at all** and became private — the kind of thing a 41-member class hides. Arrows run one way (`grouping <- nodes <- selectionActions <- clipboard`), so construction order is forced and acyclic. **No Abstract/Base tier** — one implementation each, no shared behaviour, so the ladder would be depth for its own sake; CLAUDE.md's ladder is for entity *families*, not collaborators. Commit `2f0bf8e`, verified by `tsc`, 101 tests rewritten to the new API, and a real click in the browser. **`WorkflowModel` is designed but outstanding**: `AdjacencyIndex` (the index is *written* by mutation and *read* by queries, so it is a collaborator the model owns, not a free-floating query object) + `GraphQueries` + pure `topology.ts`/`bounds`. Honest limit recorded — the aggregate root still keeps ~25 members afterwards, above the ~10 heuristic but **one reason to change** (the graph's consistency invariant); reaching ten would need a `NodeCollection`/`EdgeCollection` rename across 100+ call sites for a smaller number rather than a clearer design, so it is recommended against unless the ceiling is a hard rule.
- [Canvas blank after reload — RETRACTED](issues/26-canvas-blank-after-reload.md) — Filed as a defect, then **retracted: not reproducible, an environment artifact, the product is not broken.** Kept in the map because the *way it fooled me* is the reusable lesson. The observation was real and stable (`.joint-element`/`foreignObject`/`.joint-link` all 0 while the minimap showed 6 and no console error) and it reproduced after stashing the ticket-17 refactor onto `6c52505` — which was taken as proof of a pre-existing bug but was actually the clue it was **not code at all**: an identical failure in two different builds points outside both. It survives none of 6 clean loads, a cold start, a warm reload, or repeated force-reloads; instrumented directly, the graph holds 10 cells, the paper is unfrozen and non-zero-sized, and StrictMode's second mount is correctly populated. Two hypotheses tested and rejected — a premature read against the `async: true` paper (the tool round-trip is ~7.8s post-navigation, far past any render batch) and a zero-size paper culling views (no `viewport` function is configured). Likely cause: the dev server was **killed while the page was live** and restarted on the same port, so the tab held Vite module URLs with stale optimizer (`?v=`) hashes and the canvas layer never seeded. **Trap to remember: this false positive is silent, stable, and reproduces across code versions — defeating the usual stash-and-compare test for "pre-existing".** Rule: after restarting a dev server, hard-reload before trusting the canvas, and confirm on a freshly started server before concluding anything. The residue worth keeping is the **reload smoke check** — one assertion that the canvas has cells would have settled this in seconds; it belongs with ticket 11's deferred canvas harness.
- [Git baseline](issues/01-git-baseline.md) — Repo initialised, single baseline commit `b86018a` over the phase-1 editor (149 files). `graphify-out/` ignored (derived; `graphify update .` rebuilds it). **`.scratch/` is tracked** — the map, tickets and decision records are the shared artifact of a multi-session effort; ignoring them would strand the plan on one machine. No branch-per-ticket convention yet — revisit when ticket 12 settles CI. Unblocks ticket `11`.
- [Test strategy](issues/11-tdd-strategy.md) — Vitest with **`environment: 'node'`** (not jsdom — `core/` imports neither React nor JointJS, so a DOM env would mask an accidental dependency and make the layering rule enforced by config rather than discipline) + pytest, no shared runner. Three tiers: unit over `core/`, integration through the **public `WorkflowController` API** (testing command classes directly verifies a path nothing uses), contract across the generated boundary. **The canvas is deliberately untested** — it is a one-way projection, and every phase-1 canvas bug (`var()` in SVG presentation attributes, `paper.remove()` under StrictMode, the measurement feedback loop) was a real-browser behaviour jsdom reproduces wrongly or not at all; the adapter's translation against a fake paper is a named deferred gap. Gate is **named critical paths, not a coverage %** (a global floor rewards testing the declarative surface); floor of 65% lines on `core/model` + `core/commands` purely as a regression catch. **101 tests across 7 suites.** Their value was in what they *found*, not what they prevent: serializer non-determinism (ticket 19), `Infinity` in a serialisable field (ticket 08), and **`acyclicRule` being unreachable dead code** — no cycle is expressible with the shipped catalogue, which reshaped ticket 09. `core/execution` (10%) and `core/providers` (17%) are a **stated gap**, not an oversight: tickets 07 and 15 are likely to replace them. Performance budget stands unvetoed, ratified by default, implementation deferred with the canvas harness.
- [Canonical serialization](issues/19-canonical-serialization.md) — Fixed, red-first. **Three independent sources of drift, not one.** (1) Rows were emitted in `Map` insertion order, which is not stable for a given graph — delete-then-undo re-inserts at the end. Nodes now sort by id through `compareNatural`, so `-2` precedes `-10`; a lexical sort would be *equally deterministic and unreadable*, which is a worse failure because it looks correct. (2) `data` was spread, and `JSON.stringify` follows insertion order, so identical values serialised differently depending on which field was edited first. (3) The one needing a design decision: **edge ids were written to the file.** An edge id is a global creation counter and nothing references an edge by id (edges reference nodes; nothing references edges), so writing it leaked build order — two people drawing the same graph in a different order got different bytes, and inserting one link renumbered every row after it. Edges are now **content-addressed**: identified and sorted by their endpoint tuple, no `id` emitted, fresh handle minted on load. Older files still load — their edge ids are ignored rather than migrated, which needs no version bump because it only *narrows* what is read. Format fixed at two-space indent plus trailing newline.
- [PureMVC as a framework — rejected](decisions/puremvc.md) — Keep the MVC *layering*; do not adopt the framework. Its notification bus is string-keyed with untyped bodies (destroys the value of both TS and Pydantic); Mediator-per-component is a re-render storm on a large canvas (reproduced in phase 1 at only 6 nodes); a PureMVC `Command` is a notification handler with no `undo`, so adopting it would cost the undo stack; and in Python LangGraph already owns control flow and state, so PureMVC would be a second, competing orchestrator. Feature-frozen since 2008.

## Destination update — the cookbook workflow (2026-08-05)

The acceptance target is now a **kitchen-sink workflow**: question -> router
(`greeting | help | offtopic | info | dataquery`) -> orchestrator -> dynamically
spawned subagents -> grader (loop) -> synthesise -> report, with multiple tools
*and* functions, streamed into a chat sidebar that highlights whichever node is
currently in charge. Charted as [ticket 27](issues/27-kitchen-sink-workflow.md).

**Two of its requirements collide with LangGraph and had to be resolved before any
code:**

1. **"Subagents appear as nodes" rules out tool-subagents.** `SubAgentMiddleware`
   invokes subagents *inside tool functions*, and the docs are explicit that
   LangGraph therefore "cannot statically discover them" — `get_state(subgraphs=True)`
   returns nothing for them. Only **`Send` fan-out to a declared worker node** is
   observable. Ticket 08's "subagents are isolated, invoked as tools" is right about
   semantics but is the wrong *mechanism* when the editor must watch.
2. **LangGraph never adds a node at runtime.** `Send` creates dynamic **tasks**, not
   nodes. So the UI model is one static `worker` node with N runtime task instances
   rendered under it — and those instances are **view state, never document state**.
   Implementing "the frontend adds nodes" literally would mean writing runtime
   events back into `workflow.json`, breaking ticket 23's one-directional seam.

Also settled there: the orchestrator should be **hand-written**, not a harness, for
the same reason tool-subagents are rejected — a planner that plans internally is
opaque, and the point is that the editor can see the fan-out. And the sidebar needs
`updates` + `messages` multiplexed over one SSE stream with **`subgraphs=True`**,
without which the inner agents' tokens never surface — the most likely way this
feature ships looking broken.

## Roles vs tiers — ticket 08 partly superseded (2026-08-05)

The user's requirement: a plain Agent plus a system prompt, structured output and
three out-edges *is* a router (nothing special-cased in the engine) — **and** ship
prebuilt **Router / Supervisor / Orchestrator** nodes so the common case is
drag-and-drop. Plus: pick the tier (simple / deep / custom) per node. Charted as
[ticket 28](issues/28-agent-presets-and-roles.md).

Both paths coexist because **a preset is a registration, never engine code** — the
Open/Closed rule already used everywhere here.

**But it reverses part of ticket 08, arithmetically.** Ticket 08 made *tier* the node
type (three registered types). If *role* is also a node type the palette becomes
role x tier — twelve entries for two independent axes, multiplying with every future
role. So: **role is the node type** (it decides ports and compile target, and cannot
change without rewiring, so it is identity); **tier is a config field** (it picks the
factory, changes no ports, no edges). Ticket 08's real concern survives — validation
is per role, and the 60+ field surface uses ticket 22's progressive disclosure keyed
on tier. Recorded as an explicit supersession on ticket 08, not a silent edit.

**No new mechanism is needed for a router's N outputs:** `ports: (data) => IPortDescriptor[]`
is already a function of node data, so a router configured with four branches exposes
four output ports — exactly the "vary the number of ports, never toggle a port's
cardinality" rule CLAUDE.md already sets, and it yields ticket 03's complete declared
destination set from ordinary config.

**Node type vs canvas template, settled test:** stays *one node* whose behaviour is
config -> node type (Router, Supervisor, Grader); needs *several wired nodes* -> template
(the "Orchestrator pattern" is a topology, and a preset cannot express a topology). This
refines ticket 08's canvas-template answer rather than replacing it.

**Memory drill-down rules, restated because the UI can easily lie about them:** graph
state flows to **nodes** via the shared schema + named reducers; thread memory is the
checkpointer; cross-thread memory is `Store`; and **subagents get nothing** — a task in,
a result out. A Supervisor's config declares what each worker is *sent*, and that payload
is the entire context the worker has. Any inspector affordance implying a subagent
inherits parent history would teach developers something false about their own workflow.

## Router node — built (ticket 13, 2026-08-05)

`src/nodes/routing/RouterNode.ts` + 22 tests, and it went straight to a real node
type because the mechanism needed **no new engine concept**: `INodeDefinition.ports`
has always been `(data) => IPortDescriptor[]`, and the Router is the first type to
use it. So the whole "drag a router, name your branches, wire them" experience is
one node file, producing ticket 03's complete declared destination set from ordinary
config with no `core/` edit — ticket 28's Open/Closed claim demonstrated rather than
asserted. The tier renders as **Runtime · `Agent · create_agent`** in the inspector,
so role-as-node-type + tier-as-field is visibly working.

**A simplification ticket 09 did not anticipate: the port ID *is* the branch key.**
Ticket 09 settled "predicate on the node, branch key on the edge"; with a
config-driven branch list, an edge's branch is decided by which port it leaves from,
so no separate edge field is needed at all. Verified in the browser: 5 branches is a
292px card with all six labels legible; capped at 12 rather than scrollable, since a
router with twenty destinations is a design problem to surface.

**Two findings.** (1) A `standard` node with **no TypeScript executor is silently
skipped** by the preview engine — the harness test caught it immediately. Rather
than weaken the invariant the Router ships an executor that *refuses with a clear
message*, because it compiles to `add_conditional_edges` in Python and the browser
must not execute (ticket 07); it deliberately does not classify via the mock
provider, which would fake a decision the real runtime makes differently. (2)
**Renaming a branch drops its edge** — port ids derive from branch names, so a
rename changes the id and ticket 19's loader discards links to vanished ports. Needs
stable per-branch ids, which is precisely ticket 20's repeatable-group field;
branches stay newline-separated text until then rather than inventing a field kind
here and settling ticket 20 by accident.

The Python compile target belongs to ticket 15.

## Prompt composition — the machinery is not editable (2026-08-05)

The user's correction, and it applies to **every** node that drives a model: the
generic part of a prompt belongs to the base and must not be an editable field; the
developer supplies only domain rules. `IRouter -> BaseRouter -> Router` with default
behaviour, so a new kind of router is *configuration*, not a new class.

**It caught a real bug in the Router I had just shipped.** It had one editable
`instruction` textarea **pre-filled with the output contract** — so clearing it, which
is the first thing anyone does when writing their own rules, produced a router whose
answer could not be parsed. Now the field is `rules` only; preamble and contract are
locked constants.

Four parts, and **order is the substance**: `preamble -> context -> developer rules ->
output contract`, with the contract **last**. Prompts are order-sensitive like
middleware — later instructions win ties — so if developer text came last, a rule such
as "explain your reasoning" would countermand the output format and every parse would
fail. Their rules shape the *decision*; the base keeps the *shape of the answer*.

**"If generic, think twice" changed the answer on where it lives.** The natural move is
an `AbstractPromptedNode` shared by Router, Grader and Agent. But those compile to
*different graph constructs* — conditional edge, conditional edge with a feedback port,
node — so they are different **families**, and CLAUDE.md's own boundary rule says a
cross-family concern is a **collaborator, not a superclass**. A shared ancestor would
begin the god base class that rule exists to prevent, and would force a prompt onto
`CustomGraphNode`, which has none. So `SystemPrompt` is a composed value object
(`backend/dyflow/abc/prompt.py`); nothing inherits it.

Also built: `BaseRouter.normalise()` is **deliberately tolerant** — a router is the
entry point, so a strict parse is a total outage, which is exactly how the live Chinook
run failed on `response_format`. It accepts `"dataquery."`, `'"dataquery"'`,
`"DataQuery"` and a branch name inside a chatty sentence, and falls back with a reason
when genuinely ambiguous. A misroute is recoverable; a crash is not. And
`compile_path_map()` **omits unwired branches** rather than pointing them at `END`, so a
half-wired router shows as a missing destination instead of silently terminating a run.

Now in CLAUDE.md as a binding principle. 24 router tests + 7 TS prompt-composition tests.

## Grader node + prebuilt-and-overridable criteria (ticket 24, 2026-08-05)

Built in both languages: `IGrader -> BaseGrader -> Grader` (25 pytest) and
`GraderNode.ts` (13 Vitest). Criteria are **prebuilt** so a grader works before
configuration, and the developer **extends** them (default) or **replaces** them
(explicit) — because prebuilt behaviour that cannot be overridden is a
straitjacket. Two guards: replacing with an *empty* string keeps the defaults (a
cleared field is usually a slip), and an override **cannot reach the output
contract**, since criteria are rules while preamble and contract are machinery. So
`replace` can never yield an unparseable grader, and the contract still renders last
so "ignore formatting, write an essay" loses the tie. Generalised onto `SystemPrompt`
(`default_rules` + `replace_defaults`) so every node composing one gets extend/replace
free — and that surfaced a latent bug: `with_context` did not carry the new fields
forward, and because the type is frozen and rebuilt, that silently turned a `replace`
back into an `extend`.

Also: **deterministic checks run before the model** (empty answer, transported error —
the failure modes actually seen in the Chinook run), with tests asserting the model is
*not* called for them. `Verdict.reject()` defaults feedback to the reason, because a
rejection with nothing actionable makes the revise loop pure cost; and an *unreadable*
verdict **passes**, since a grader that cannot decide must not discard work the agent
did.

**The cycle is now drawable** — `PORT.feedback` + grader `revise` + agent `feedback`,
with `acyclicRule` scoped to permit a cycle only when it closes on a feedback port.
**But the prediction that this would wake `acyclicRule`'s rejection branch was wrong:**
the obvious accidental loop (grader `pass` -> agent `prompt`) is refused by
`typeCompatibilityRule` first, because `result` cannot feed `text`, so the cycle check
never runs. Ticket 11's finding still holds — that branch stays unreachable through the
real catalogue and **the type graph is doing the work, not the rule**. Pinned by a test
asserting the message is a *type* error and not a loop error, plus one asserting the
grader is the only node type that can emit `feedback`.

## Compile target: interpret to execute, generate to read (ticket 15, 2026-08-05)

**Chose (c) both**, decided by the ticket's own three questions. Does a stale
`graph.py` ever execute? Under generate-only yes — under (c) **never**, because the
file is not imported; staleness is only dangerous on the execution path, so take it
off that path rather than managing it. Can a user hand-edit it? **No**, and say so
plainly — it is regenerated; hand-written code lives in `tools/`/`functions/`, which
are user-owned and referenced by name. What does `git diff` show after moving a node?
**Nothing** — which is a *requirement on the generator*: geometry must never reach
emitted code, or every drag becomes a code diff and the export is worthless for
review.

**Built the interpreter** (`workflow_compiler.py`, 24 tests). `plan()` yields an
inspectable `CompiledPlan`, `build()` turns it into a `StateGraph`; the plan is
separate so the future generator consumes the *same* plan, making
interpreter/generator agreement true by construction.

**The load-bearing finding: not every canvas edge is a graph edge.** A `tool` or
`skill` link is a **binding** — no node, no edge; `text`/`result` is control flow;
`feedback` is part of a conditional edge. Sequencing a tool would run it standalone
*and* let the agent call it — the same work twice, with a plausible result.

**Two bugs found only by compiling a document exported from the real canvas**, both
invisible to hand-written fixtures: (1) **LangGraph reserves `:` in node names** and
our ids are `node:agent.llm-1`, so `add_node` raised — now sanitised from the *id*,
not the label, because a node name is identity and a rename breaks an interrupted
thread; (2) **a bound tool became an entry node** — excluded from `exits` but not
from `nodes`, so it had no incoming edge, was treated as an entry and wired from
`START`, reintroducing the exact doubling the binding rule prevents. **The unit tests
passed while that was live**, because they only asserted `exits`. Reusable lesson:
fixtures agree with the code that produced them; a real export is the only thing that
disagrees.

Verified end to end — input → router → agent (+ bound tool) → grader with `revise`
looping back compiles to labelled conditional edges, the loop intact, the tool absent
from the topology, `START`/`END` correct, no warnings. **What you drag is now what
runs.**

`DEFAULT_PORT_SPECS` duplicates TS port types, which CLAUDE.md forbids — marked
temporary, the resolver is **injectable**, and a test asserts the compiler goes
through the injection point so the seam cannot rot shut (ticket 02 owns generation).

## Orchestrator + `Send` fan-out/join — backend built (ticket 27, 2026-08-05)

Grounded against a shared external framework (a DevCompass "loop/graph/harness"
deck the user supplied) before building anything — see
[the decision doc](decisions/loop-graph-harness.md). It confirmed, rather than
changed, the architecture already in place: Router/Grader are the loop layer,
the compiler+FastAPI seam is the harness layer, and it sharpened one point —
"the state schema and how parallel results merge" is a graph-engineering
decision, which is exactly the class of bug found below.

Built: `IOrchestrator -> BaseOrchestrator -> Orchestrator` (16 pytest,
deterministic decomposition, no model required for the default) plus a third
compiler-recognised edge category — a `worker`-typed port is a **fan-out
declaration**, compiling to `add_conditional_edges` returning `langgraph.types.Send`
objects, alongside the existing control-flow and tool/skill-binding
categories. Proven with a revise loop that re-enters the fan-out/join subgraph
itself, not just a single node (`test_orchestrator_graph.py`, 10 tests) —
the harder graph-engineering case implied by ticket 27's original shape.

**Two real bugs, found only by running this live, not by any fixture:** a bare
`answer: str` field written by two nodes in the same superstep raised
`InvalidUpdateError` — fixed with a named reducer
(`keep_latest_nonempty`) and now a **standing rule**: any state key more than
one node type can write must be `Annotated[T, reducer]`, never a bare scalar.
And subtask ids collided across replans (`Orchestrator.plan()` always started
at `task-1`), silently blending a rejected attempt's stale results with the
fresh replan's — fixed by folding the attempt count into every id.

**What looked like a model-reliability limitation turned out to be a third
wiring bug, found by refusing to accept the first live result as inconclusive
and chasing it further.** `WORKER_TYPE`'s compiler port-spec table never
declared `tools`/`skill` ports at all — an edge into either fell through the
"unknown port" fallback and was silently treated as control flow, so a
worker's bound Chinook tools never reached it regardless of prompt wording.
Fixed with two added `PortSpec` entries plus a regression test mirroring the
agent's own binding coverage. Verified live, twice, against
`ollama:gpt-oss:120b-cloud`, by inspecting each message's `tool_calls`
directly: the real sequence ran (`chinook_list_tables` →
`chinook_get_table_schema` → `chinook_execute_sql`) and produced correct,
grounded answers.

**TypeScript node types now exist for all three** — `OrchestratorNode.ts`,
`WorkerNode.ts`, `FormatReportNode.ts` (`src/nodes/orchestrate/`), following
the Router/Grader shape (Orchestrator and Worker refuse to execute in the
browser preview; Format Report genuinely runs there). A new `PORT.worker`
port type was added, capped at one connection on the orchestrator's `workers`
output since the compiler records at most one dispatch target per
orchestrator. A developer can now drag all three onto the canvas.

**The streaming/sidebar contract is also built.** `POST /api/runs/stream`
streams `graph.stream(stream_mode=["updates","messages"], subgraphs=True)` as
SSE, folding the incremental payloads through the *same* reducers `RunState`
declares so the streamed and blocking endpoints cannot disagree about the
final answer. One assumption checked and corrected against the real
LangGraph: `namespace` does **not** distinguish two `Send`-dispatched
instances of the same worker node (only an actual nested subgraph gets its
own), so the sidebar keys on the worker's task id instead.
`RuntimeClient.runStream()` consumes it (`fetch` + manual SSE framing, since
`EventSource` cannot POST a body), and `AskPanel.tsx` selects the active node
on the canvas as each update arrives — verified live against a running
`uvicorn` backend, not only in tests. 187 pytest + 199 Vitest passing, `tsc`
clean. Ticket 27 is now fully resolved.

## Ticket sweep — deep grader, per-intent grading, file persistence, capability discovery (2026-08-05)

Closed or advanced every open ticket in one pass, at the user's request, with
a standing instruction to test everything live rather than ask before
finishing. Full account per-ticket lives on each ticket file; summarized
here:

- **New feature, live-verified end to end**: a router classifying into
  `dataquery`/`off_topic`/`general_knowledge`/`greeting`, the `dataquery`
  branch fanning through Orchestrator → Worker → report → a **deep-tier**
  Grader, the other three intents each with their own lighter grader —
  "a different grader per intent" answered as ordinary canvas composition
  (multiple `route.grader` nodes), not a new field or node type. The Grader's
  `tier: deep` field, previously cosmetic, now actually routes judgement
  through `create_deep_agent` (`_DeepAgentAsChatModel`, built at the
  compiler/runtime boundary so `BaseGrader` stays model-agnostic).
- **Tickets 10/14 (persistence, resolved — authoring half only)**: workflows
  now live at `workflows/<slug>/workflow.json`, backend-owned, slug frozen at
  creation. Runtime-state persistence and an `IWorkflow` entity-ladder class
  are real, named gaps, not fabricated as done.
- **Ticket 16 (partly resolved)**: editor-writes-file direction works;
  watching for external changes does not exist.
- **Ticket 21 (decision recorded)**: prompts stay inline in `workflow.json` —
  checked directly against a real saved file that the "unreadable diff" fear
  does not hold yet, rather than assumed.
- **Ticket 18 (partly resolved)**: `tools/`/`functions/` discovery works,
  verified live against the real Chinook tools through the running API;
  node-type discovery (a hand-written class becoming a new palette entry) is
  unbuilt.
- **Ticket 12 (resolved)**: mostly recording what was already true, plus one
  real gap it surfaced and fixed — no Python dependency manifest existed
  anywhere; added `backend/pyproject.toml`.
- **Ticket 28 (resolved)**: every role it asked for is now a built, tested
  node type; naming settled.
- **Tickets 20, 25 (decisions recorded, not implemented)**: 20's motivating
  examples turned out to be already solved a different way (ports and node
  composition, not a new field kind) — building the primitive now would have
  no consumer. 25's splice-insert design is fully settled but the canvas
  drop-on-edge gesture itself was not risked into sensitive interaction code
  without dedicated testing time.
- **Ticket 17 not attempted this pass** — `WorkflowModel`'s decomposition is
  a real refactor of load-bearing code with an already-recorded design
  (`AdjacencyIndex` + `GraphQueries` + `topology.ts`); rushing it without the
  TDD-first treatment CLAUDE.md requires would have been a worse outcome than
  leaving it exactly where it already was.

237 pytest + 208 Vitest passing, `tsc` clean, throughout.

## Production-readiness pass: workflow-scoped registry shipped, chat panel bug found and fixed (2026-08-06)

Closed the gap this file itself flagged (previous section, last sentence) plus
a production-readiness sweep, at the user's `/goal` request to find and fix
gaps and to test everything end to end rather than only in Vitest.

- **Workflow-scoped registry overlay, built.** The mechanism the "Not yet
  specified" entry below describes (`workflow-local shadowing global`) is now
  real: `src/nodes/workflowScoped.ts`. `syncWorkflowScopedNodes` registers/
  unregisters Chinook's node family as the model's own nodes change
  (`workflow:reset`/`node:added`/`node:removed`); `registerNodeTypesForRawDocument`
  does the same *before* any `importJSON`, because `WorkflowSerializer.fromJSON`
  resolves each node's type via the registry and **silently skips** any node
  whose type isn't registered yet — a load-order hazard found by reading the
  serializer, not by hitting it live. Chinook is no longer in
  `registerNodeCatalogue`.
- **Regression this surfaced, fixed**: `seedDemo.ts`'s seeded showcase writes
  Chinook nodes straight to the model before any document exists, so it threw
  `unknown id "tool.chinook-get-all-tables"` synchronously at startup — before
  React ever mounts, so no error boundary can catch it. Root-caused via git-
  stash bisection → diagnostic logging → a top-level try/catch that captures
  the real stack. Fixed with `registerChinookNodes`, an unconditional variant
  `seedDemoWorkflow` calls for itself, since it is the one legitimate case
  that needs Chinook stated outright rather than inferred from a document.
- **Gap found in the process, filled**: the app had no error boundary and no
  pre-mount crash handling anywhere — *any* future unhandled error would
  blank `#root` with nothing visible. Added `ErrorBoundary.tsx` (the one
  top-level net) and a `main.tsx` try/catch for the pre-mount case a React
  boundary structurally cannot reach.
- **Production-readiness audit** (logging, secrets, README) found: no
  `.env.example` despite `.gitignore` reserving one; zero backend logging
  configuration, with silent `except Exception` swallows in
  `capability_discovery.py` making a broken tool file vanish from discovery
  with no trace; README missing test commands, env var docs, and
  prerequisites. All four fixed.
- **Real bug found by the E2E test itself, not by code reading**: asked the
  live app a Chinook question through the chat panel at a sub-1100px
  viewport and the Send button did nothing — no error, no network request.
  Root cause: the narrow-window overlay rule in `AppShell.css` gives every
  `.panel--right` `position: absolute; right: 0`, written when Inspector was
  the only panel that side could ever hold. Since the chat panel shipped,
  Inspector and chat can both be open at once, and under 1100px they land in
  the identical rect with Inspector (mounted second) silently intercepting
  every click meant for chat. Fixed by grouping both under one
  `.app-shell__right-panels` flex container so the overlay rule positions the
  *pair*, not each individually. Verified live: both panels visible and
  independently clickable at 1095px, and a chat message now actually reaches
  the backend and streams back an answer.

247 Vitest + 197 pytest passing, `tsc` clean, throughout.

### End-to-end sweep, beyond the one query above

The stop-hook feedback correctly flagged that one chat query is not "all
use cases." Extended the sweep against the real persisted document
(`workflows/intent-routed-demo/workflow.json`), through the actual endpoints
the frontend calls (`/api/runs`, `/api/runs/stream`), not a stub:

- **All 4 router branches, scripted against `/api/runs`**: `greeting` →
  correct casual reply, grader passes first try. `off_topic` (both an
  explicit "write me a haiku" and literal keyboard-mash nonsense) → correct
  branch, grader passes. `general_knowledge` ("capital of France", "what does
  jazz sound like") → correct branch and correct answers. `dataquery`
  ("highest total sales revenue in the Chinook database") → correct branch,
  orchestrator fan-out visible (`task-1` in the report), correct answer
  (**Rock, $826.65**) matching the real Chinook data.
- **Error paths, all handled cleanly, none silent**: an empty question → 422
  with a clear Pydantic message; a malformed workflow with no edges → 502
  with `ValueError: Graph must have an entrypoint`; `recursion_limit=10` on a
  multi-hop dataquery run → 502 with a clear `GraphRecursionError` pointing at
  the docs. No crash, no hang, no empty response in any case.
- **`/api/runs/stream` verified independently of `/api/runs`**: same
  document, same dataquery question, scripted directly against the SSE
  endpoint — routed correctly to `worker1`'s tool calls, same as the blocking
  endpoint.
- **Multi-turn chat, live in the browser**: three questions sent in one
  session; the thread correctly grew to three turns, each with its own
  question, activity feed and answer — the chat-panel fix above holds across
  repeated sends, not just the first.
- **A genuine router-classification miss, investigated and ruled out as a
  code bug**: the live browser chat twice classified a clearly
  Chinook-flavoured question as `general_knowledge` instead of `dataquery`.
  Reproduced the *exact* same question against `/api/runs/stream` by script
  and got the correct `dataquery` routing on the first try — so the
  misclassification is the router LLM's own run-to-run variance (an already
  accepted characteristic of a cloud classifier with no `temperature=0`
  guarantee), not a defect in the routing code, the stream wiring, or the
  chat panel. Recorded here rather than silently dropped, per the "no silent
  caps" norm — a developer relying on this router for a production intent
  boundary should know it is not 100% deterministic on ambiguous phrasing.

## Real crash found from "the chat did nothing", fixed (2026-08-06)

User reported the chat felt broken ("hello prompt does nothing, are you sure
the backend is up?"). Backend was up (`/api/health` 200 throughout) — the
real defect was upstream of that report: an earlier chat turn had actually
failed, and the chat panel had rendered the raw exception text as if it were
part of the model's answer, which reads exactly like "nothing happened."

Root cause: `RunState.attempts` (`node_runtime.py`) was a bare `int`, but
`_agent` and `_orchestrator` both write it for their own retry/replan
budgets — the identical hazard already documented and fixed for `answer`
(`keep_latest_nonempty`), just not yet hit for this field. Under a fan-out
that schedules both writers in one superstep, LangGraph raised
`InvalidUpdateError: At key 'attempts': Can receive only one value per
step`. Fixed with `keep_max` (a budget counter should only grow, so the
higher of two concurrent writes is always correct), mirroring the existing
`answer` fix exactly. Regression test at the same `StateGraph` level as
`test_answer_channel_concurrency.py`. Verified live post-fix: a
multi-clause dataquery question that fans out to two workers now completes
cleanly (`attempts=2`, no error).

202 pytest passing throughout.

## "Run" gave zero feedback on an unrunnable graph, fixed (2026-08-06)

Same investigation thread as the `attempts` fix above, continued: user
reported the diagnostics panel's 13 red entries ("AI Agent needs a 'prompt'
input", "X is part of a loop" ×9) and that clicking **Run** (the canvas
preview button, not Chat) produced nothing — no toast, no active node, no
response.

Root cause, in `ExecutionEngine.run()`: a blocking diagnostic or a detected
cycle correctly computed `{ ok: false, error }`, but both pre-flight paths
`return`ed *before* calling `bus.emit(...)` — so neither `run:start` nor
`run:finish` ever fired. `TopBar`'s own `run:finish` listener (which already
turns a failure into a toast, added for the mid-run failure case) never got
the chance to run. The intent-routed demo is unrunnable by this engine *by
design* — it is a sequential DAG walk, and the demo's revise loops are only
valid for the backend LangGraph compiler — but a legitimate limitation
silently indistinguishable from a bug is still a bug in the reporting.

Fixed with `rejectBeforeStart()`: both paths now emit the same
`run:start`/`run:finish` pair a real run would, so the existing listener
handles them with no new UI plumbing. Also improved the message the acyclic
case actually shows: `acyclicGraphRule`'s per-node "X is part of a loop"
diagnostics read like the graph is broken; the toast now says plainly that
this preview engine can't run a loop and to use Chat instead. Regression
test at `ExecutionEngine.test.ts` (blocking-diagnostic case and cycle case,
each asserting the `start`/`finish:false` event pair). Verified live:
reloading the actual cyclic intent-routed demo and clicking Run now shows
the toast immediately.

249 Vitest + 202 pytest passing, `tsc` clean.

## RunState's bare-scalar hazard, closed for good (2026-08-06)

Same investigation thread, continued a third time: the user reported the
chat panel showing two grader verdicts landing together (a "greeting"
rejection alongside criteria that reads like the off-topic grader's own),
then `InvalidUpdateError: At key 'feedback': Can receive only one value per
step`, with Formatted Output left empty — fully explained by the run
aborting mid-graph before `out1` was ever reached, not a separate defect.

`feedback: str` had the identical shape as the already-fixed `answer` and
`attempts`: this document alone has four `_grader` instances, each writing
it on every step. Annotated it with the existing `keep_latest_nonempty`
reducer (pass writes `""`, revise writes real text — "keep whichever is
non-empty" is exactly right, already proven for `answer`).

With three of these found one at a time across one afternoon, audited the
rest of `RunState` rather than waiting for a fourth report: `question`,
`task_id` and `task_instruction` are read-only from every node factory
(`state.get(...)`, never returned in a node's update dict), and `messages`
already carries LangGraph's own `add_messages` reducer. `answer`,
`attempts` and `feedback` were the only three actual multi-writer bare
scalars in the schema, and all three now have named reducers. No open
hazard of this shape remains.

206 pytest passing throughout. Verified live: 5/5 repeated greeting runs
against the restarted backend complete cleanly with no crash.

## Framework-wide gap sweep, one real bug fixed, two findings recorded (2026-08-06)

User asked for a broader sweep beyond the immediate repro, and gave one
directly: "who is the best artist of all time?" through chat.

**Real bug found and fixed**: the orchestrator's revise loop was forking a
grader's rejection feedback into its own bogus subtask instead of refining
the existing one. Root cause and fix are detailed in the commit
("Fix orchestrator revise-loop forking grader feedback into a bogus
subtask") — briefly: appending feedback as a semicolon clause *before*
`Orchestrator.split()` handed the deterministic splitter one more clause to
split on, so ordinary critique prose ("be more decisive") became its own
`Subtask`, dispatched to a worker as if it were a fresh question. Fixed by
splitting first, then appending feedback to each resulting subtask
afterward. `test_orchestrator_graph.py` updated to the corrected behaviour
plus a new regression test pinning the exact live failure.

**Second real bug found in the same pass, fixed**: `hasOutputRule` checked
port *descriptors* (does this node type declare zero out-ports) rather than
actual wiring, so any graph legitimately ending at an Agent/Router/Grader
without a separate Output node — which the backend supports fine — was a
false "nothing consumes the result" warning. Fixed to check whether a
node's out-ports are actually unwired.

**Findings recorded, not acted on** — a background sweep (general-purpose
agent) additionally reported:
- The `Send`/join synchronization assumption in `_format_report_function`
  (all dispatched workers land in one superstep before the join reads
  `worker_results`) is asserted in code comments as verified against the
  installed LangGraph, but no test asserts it directly for N>1 workers.
  Worth a `docs-langchain` check before ever changing retry/timeout
  semantics near this join; not touched this pass.
- A full TS-schema-vs-Python-factory field diff (every field a node type
  declares in `src/nodes/*/` has a matching read in `node_runtime.py`, and
  vice versa) was not completed — flagged as unexplored, not assumed clean.
- Zero-subtask orchestrator plans are already guarded by
  `BaseOrchestrator.plan()`'s "never zero subtasks" fallback, and the API's
  `question: Field(min_length=1)` means the one input that could produce a
  truly empty instruction is already rejected before it reaches the
  compiler — the sweep's concern here is real in principle but not
  reachable through any path the app currently exposes.
- `ConnectionValidator`'s cardinality rule and the remaining backend
  `except Exception` sites were checked and found correct/already visible
  to the caller — no gap.

207 pytest + 252 Vitest passing, `tsc` clean.

## "Production ready" goal — status and explicit scope line (2026-08-06)

The standing `/goal` this session ("production ready, find all gaps and fix
it and any missing feature, do a proper end to end test with all usecases")
is open-ended by construction — "all gaps" and "all usecases" have no
finish line a single session can reach. Recording concretely what this
session actually covers, so the goal is judged against a stated scope
rather than an unbounded one:

**Verified clean, this session, against current `main`:**
- All 4 intent-routed-demo branches (`greeting`, `off_topic`,
  `general_knowledge`, `dataquery`) run end to end via `/api/runs` with no
  crash, no `InvalidUpdateError`, no self-contradictory answer.
- 207 pytest + 252 Vitest passing, `tsc` clean.
- The live app loads, the seeded demo renders, chat round-trips to the
  backend and streams a real answer, the canvas "Run" button gives visible
  feedback either way (success or a clear reason it can't run).

**Real bugs found and fixed this session** (each with a regression test,
each verified live, not only in a test): the Chinook-global-registration
architecture violation; the `seedDemo` startup crash it caused; three
`RunState` bare-scalar reducer hazards (`answer` pre-existing,
`attempts`/`feedback` found and fixed here); the chat-panel/Inspector
layout collision under 1100px; the silent `ExecutionEngine.run()` failure
path; the orchestrator feedback-forking bug; the `hasOutputRule` false
positive. Also closed: missing `.env.example`, missing backend logging,
missing error boundary, README gaps (test commands, env vars,
prerequisites).

**Explicitly not attempted this session** (real, named gaps — not silently
skipped, see also "Not yet specified" and "Out of scope" below):
ticket 16 (filesystem watch-back), ticket 25 (canvas splice-insert
gesture), ticket 17 (further `WorkflowController`/`WorkflowModel`
decomposition beyond the ticket-40 pass), a full TS-schema-vs-Python-factory
field diff, and a direct test of the `Send`/join synchronization assumption
under N>1 concurrent workers.

**What "all usecases" would need beyond this**: every node type exercised
in isolation (not just the ones the intent-routed demo happens to wire),
the Reddit tool's live-vs-fallback path, PNG/SVG export on both Chromium
and WebKit, undo/redo across a real editing session, the accessibility
checker's own claims, and the workflow-manager save/load/rename/delete
paths. None of these were touched this session; flagging them by name is
the honest alternative to claiming a coverage this session did not do.

## TS-schema-vs-Python-factory field diff, plus live verification of the
## remaining named gaps (2026-08-06)

Closed out the last few items this session's "production ready" pass had
named but not yet checked.

**Live-verified, no bug found:**
- JSON/SVG/PNG export — all three ran clean in the live app with no
  console error (this Chromium-based browser rasterises `foreignObject`
  content, so PNG succeeded too; WebKit's documented refusal is unrelated
  to this environment).
- The accessibility checker's own claims — spot-checked "84 interactive
  controls have accessible names" against a hand-rolled DOM query (86, a
  close match attributable to a slightly different heuristic, not a
  fabricated number).
- The Reddit tool's live-fetch-then-fallback — confirmed directly that
  `fetch('https://www.reddit.com/...')` genuinely throws `Failed to fetch`
  from this browser origin, and the code's own fallback path is exactly
  what the comments claim, correctly labelled as sample data.
- Undo/redo across a real mixed session (node-add, then a rename, both via
  the real controller/history APIs) — interleaves correctly across two
  different command types in proper LIFO order.

**Real bug found and fixed**: the Workflows panel's "Save current" button
read `workbench.model.name` directly in render, so renaming the document
via the Inspector while the panel stayed open left the button's own label
stale until an unrelated re-render happened to refresh it. The rename and
the eventual save were always functionally correct — verified by actually
completing a rename-then-save round trip and confirming the backend stored
the new name — only the button's displayed text lagged. Fixed by
subscribing to the model's `workflow:name` event, same pattern `useNode`
already uses for other mutable fields.

**Field-diff sweep** (a background agent, then independently confirmed by
reading the code directly): every node type's TS field schema
(`src/nodes/*/`) compared against its Python factory's reads in
`node_runtime.py`.

- **Real bug, fixed**: `FormatReportNode.ts` declares `reportTitle`;
  `_format_report_function` read `data.get("title")` — a key no real
  document has ever produced. The Inspector's title field was fully inert
  on every backend-executed run, silently falling back to `"Report"`.
  Fixed the read, added a regression test (none existed that asserted the
  configured title actually appears — exactly how this went unnoticed).
- **Real, significant missing-feature gap — flagged, not silently
  built**: `AgentNode.ts`'s per-card `model` and `tokenBudget` fields are
  fully inert for backend/Chat execution. `NodeRuntime` receives one
  `self.model` for the *entire graph* (`main.py`'s `run_workflow` resolves
  a single model from the request and passes it once), and `_agent` always
  uses that shared instance — confirmed directly in the code, not inferred.
  The canvas visibly lets a developer set three different AI Agent nodes
  to three different models (the intent-routed demo does exactly this),
  which creates a reasonable expectation that each backend-executed agent
  uses its own — it doesn't. Implementing real per-node model routing is a
  feature addition (resolving N models instead of one, handling a missing
  key for any one of them, deciding whether local-preview parity matters),
  not a one-line fix, so it was not attempted without checking scope. The
  local canvas preview (`AgentNode.execute()`) *does* honor its own
  per-node model field — only the backend path is affected.
- **Real, lower-severity gap — flagged, not fixed**: `RouterNode.ts`'s
  `tier` field is declared but `_router` never reads it (contrast
  `GraderNode`, where `tier: "deep"` genuinely swaps in
  `_DeepAgentAsChatModel`). Inert exactly like the two above.
- **Recorded, not a bug**: Chinook's `tableName`/`maxRows` canvas fields
  are inert by design, not by drift — the real tool classes
  (`workflows/chinook-nl-to-sql/tools/chinook.py`) let the *model* supply
  `table`/`max_rows` per call, which is more correct than a fixed
  per-node default for a tool an agent calls dynamically. Worth a UI
  affordance question (should the field be relabelled "default" or
  removed?) but not a runtime bug.

208 pytest + 257 Vitest passing, `tsc` clean.

## Per-node model selection and Router's deep tier, implemented (2026-08-06)

The two remaining flagged missing-feature gaps from the field-diff sweep are
now built, not just documented:

- **Per-node model selection.** `NodeRuntime._resolve_model(data)` reads a
  node's own `provider/modelId` selection (the canvas's own format,
  `ProviderRegistry.selectionFor`), converts it to `init_chat_model`'s
  colon-joined key, and caches the built client per key. No selection, or
  still set to Mock (a frontend-only local-preview simulator with no
  backend equivalent), falls back to the graph's one shared default exactly
  as before; an unresolvable selection (no key, unknown model) falls back
  too rather than taking the whole run down. Wired into `_agent` and
  `_grader` (both already had per-node model-adjacent fields) and `_router`
  (which did not — see next item).
- **Router's `tier: "deep"`.** `RouterNode.ts` declares the same `tier`
  select `GraderNode.ts` does; `_router` never read it. Fixed to mirror
  `_grader`'s existing `_DeepAgentAsChatModel` wrap exactly.

Unit-tested in isolation (`TestPerNodeModelResolution`: own selection, Mock
fallback, two distinct models, caching, graceful failure —
`init_chat_model` monkeypatched, same reasoning `TestDeepGrader` already
applies to `create_deep_agent`) and `TestDeepRouter` (mirrors
`TestDeepGrader`). Verified live: the real intent-routed demo, with two AI
Agent nodes forced onto different real Ollama-cloud models, ran cleanly
through the actual backend.

**End-to-end sweep against the fully-updated backend** (all fixes from
this whole session applied): all 4 intent-routed-demo branches plus the
original artist-question repro — 5/5 clean runs, no crash, no
`InvalidUpdateError`, no self-contradictory answer.

**Deliberately not changed**: Chinook's canvas `tableName`/`maxRows`
fields stay inert by design — the real tool lets the *model* supply
`table`/`max_rows` per call, which is more correct than a fixed per-node
default for a tool an agent calls dynamically with a different table each
time. Wiring the canvas value through as a *default* would require tools
to become per-node-parameterized instances rather than one bare
type-shared singleton per tool type (`self.tools: ToolRegistry`) — a real
structural change to how tools are resolved, not a fix scoped to this pass.

215 pytest + 257 Vitest passing, `tsc` clean.

## Not yet specified

- ~~**Shared capabilities across workflows.**~~ **Settled 2026-08-05 by the user:** the shared tier *is* the generic tier — `AgentNode`, `TextInput`, `MarkdownFile`, `Output`, `Group`, `Note` are the editor's **grammar** and ship in `src/nodes/`; anything bound to one domain (the Chinook tools) lives in `workflows/<slug>/{nodes,tools,functions}/` and is only in the palette while that workflow is open. Mechanism is a **workflow-scoped registry overlay** on the global `Registry<T>` (`upsert()` already exists), with **workflow-local shadowing global**, so a workflow can override a generic node without forking and `core/` is never edited. Rationale: put one workflow's tools in the shared catalogue and every future palette carries every past workflow's tools — unbounded growth, useless exactly when the product starts working. **Immediate consequence: Qwen registered the Chinook tools globally in `src/nodes/index.ts` (verified in the running palette) — that is on the wrong side of this line and must move.**
- Sandboxing capability discovery. Importing user modules executes their code; acceptable for a local dev tool, unresolved for hosted use — becomes specifiable only if hosting comes into scope.
- Whether `tests/` are *run* by the app (a "run tests" affordance on a workflow) or merely colocated for the developer and their coding agent.
- Streaming and observability into the editor — token streams and per-node traces from a running LangGraph back onto the canvas.
- Human-in-the-loop: how `interrupt` / `HumanInTheLoopMiddleware` surfaces as a canvas affordance.
- Per-node error, retry and timeout semantics once the entity hierarchy is fixed.
- Migrating existing v1 workflow JSON to the generated schema (a serializer migration chain already exists).
- Provider credentials once the backend exists — browser-side `localStorage` keys go away; unclear what replaces them.
- Multi-user / auth — only becomes specifiable after the persistence shape is decided.
- Evaluation and tracing (LangSmith) — plausible but not yet in view.

## Out of scope

- **Real-time collaborative editing of a workflow** (two people dragging nodes on one canvas). Ruled out — the artifact is source code in git, not a document. It would move the graph into Postgres and demote `workflow.json` to an export, losing git as the sync mechanism (and with it the agentic-coder-friendliness that motivates the file layout); it would replace the linear `CommandStack` with collaborative per-user undo; and it would leave the product with *two* collaboration models, since `functions/` and `tools/` are Python files that cannot be co-edited anyway. No comparable tool does this (n8n, Langflow, Flowise, Node-RED all decline it). **Kept instead:** git for sync, PR for review, Postgres Realtime for *live multi-viewer run observation* — which needs no CRDT — and an optional advisory lock ("Alice is editing this") if concurrent edits become a real problem. Settles the open branch in ticket `10`.
- Deployment, hosting and infrastructure.
- Further visual parity work against the JointJS+ demo — phase 1 closed this.
- Replacing JointJS core with another canvas library.
