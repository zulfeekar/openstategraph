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
