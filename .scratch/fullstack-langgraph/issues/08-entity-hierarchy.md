Type: grilling
Status: open
Blocked by: 02, 03, 06

## Question

Design the universal entity hierarchy — the crux of this effort.

The requirement: **every** concept in the ecosystem (node, edge, tool, provider, workflow, and future ones) derives from one extensible base, in *both* Python and TypeScript, so that shared fields and overridable behaviour are inherited rather than repeated.

Decisions to reach:
- Is there a single root (`IEntity`) with parallel `BaseNode` / `BaseEdge` / `BaseTool` branches, or independent hierarchies per family? What genuinely belongs on the root (id, kind, version, metadata)?
- **Inheritance versus composition.** The stated preference is inheritance. But LangGraph nodes are *functions*, not classes; and Pydantic discriminated unions favour flat tagged models over deep trees. Decide honestly where inheritance earns its place and where it becomes ceremony — and say so.
- What is `abstract` versus `concrete`; which members are overridable; how a plugin extends the tree without touching core.
- How the hierarchy survives Pydantic → TS generation (depends on 02) — if generation flattens it, either the hierarchy or the generator must change.
- The relationship between an authored entity (config, serialisable) and its runtime behaviour (executor). Phase 1 split these deliberately (`INodeDefinition` vs `INodeExecutor`) — does that survive, or collapse?

Consult `/domain-modeling`. Produce the type tree, in both languages, with the reasoning for each split.

---

## Agent *type* is a first-class developer choice — and it mirrors the library's own layering

Verified against the docs. LangChain publishes a three-tier model ("Frameworks, runtimes, and harnesses"):

| Tier | What it is | Construct |
| --- | --- | --- |
| **LangGraph** | the low-level orchestration *runtime* — deterministic + agentic mixed | a hand-written `StateGraph` node |
| **LangChain** | the *framework* — "a minimal, highly configurable harness" | `create_agent` |
| **Deep Agents** | an *agent harness* — batteries-included: context compression, virtual filesystem, subagent spawning | `create_deep_agent` |

Decisive detail: **`create_deep_agent` "pre-assembles a middleware stack on top of `create_agent`"**. So the inheritance the user asked for is not a modelling preference — it *mirrors the library*:

```
INode
└── BaseNode
    ├── BaseAgentNode          shared agent config + resolveMiddleware()
    │   ├── ReactAgentNode     → compiles to create_agent
    │   └── DeepAgentNode      → compiles to create_deep_agent  (extends ReactAgentNode,
    │                            because a deep agent literally *is* create_agent + a stack)
    ├── ToolNode               → ToolNode / @tool
    ├── FunctionNode           → plain callable
    ├── RouterNode             → add_conditional_edges
    ├── GraderNode             → evaluator-optimizer (ticket 24)
    └── WorkflowNode           → subgraph (ticket 05)
```

Settle here: the **agent-type field** on the node (LangGraph node / `create_agent` / `create_deep_agent`) and whether switching type is a *different node type* or a discriminant on one type. The former gives clean Liskov substitution and distinct compile targets; the latter gives an easier UI. Note ticket 02: the discriminant must be a required `Literal` with no default for the tagged union to survive codegen.

### Convention is by *location*, not by name prefix

Superseded: an earlier draft used a `Final*` prefix. **Rejected** — location is the better convention, and it is the same principle already adopted for generated-vs-user-owned code: separate by directory, never by markers inside the file. Applying it consistently means one rule to learn instead of two.

```
workflows/text-to-sql/
  nodes/          concrete node classes — registered in the palette
  functions/      concrete callables
  tools/          concrete tools
  _abstract/      I* interfaces and Base* classes — never registered
```

Consequences:
- Names stay idiomatic: `ReactAgentNode`, not `FinalReactAgentNode`. Neither Python nor TypeScript has a `final` idiom, so the prefix was noise.
- The interface/base ladder is unchanged — `IAgentNode → BaseAgentNode → ReactAgentNode`. Only *where the files sit* decides what is user-facing.
- Discovery scopes by folder rather than parsing names (ticket 18).

Settle the leaf-directory names (`_abstract/`? `abc/`? `base/`?) and whether the ladder is per-workflow, shared, or both (ticket 18 covers shading/shadowing).

### Edge cardinality lives on the **port**, not the node

Proposed: `INode(multiple_edges=True|False)`, overridable, settable per instance as `XAgent(multiple_edges=True)`.

**Reject the node-level flag.** One node has ports with *different* cardinalities simultaneously — the existing agent proves it:

| Port | Direction | Cardinality |
| --- | --- | --- |
| `prompt` | in | exactly 1 — two prompts is meaningless |
| `skill` | in | 1 |
| `tools` | in | **many** — it is a bus |
| `result` | out | many — fan-out to several consumers is normal |

A single boolean on the node cannot express that. The capability is right; the location is wrong.

**It already exists, on the port:** `IPortDescriptor.maxConnections?: number`, resolved by `maxConnectionsOf()` with defaults *in = 1, out = unlimited*, and enforced by `capacityRule` in the `ConnectionValidator` — which additionally *replaces* the incumbent link when a single-slot input is full rather than rejecting the drop.

**Two mechanisms already exist and answer different questions. Keep both, and keep them distinct:**

| Question | Mechanism |
| --- | --- |
| "This one port accepts many links" (a bus) | `maxConnections` on the port |
| "This node's *number* of ports varies with config" | `ports: (data) => IPortDescriptor[]` — already a function of node data |

**Recommend against freely toggling cardinality per instance.** If a port sometimes carries one value and sometimes many, the value's *type* changes (scalar vs list) and the executor must branch — a runtime type-contract change, which is exactly what the typed-port model exists to prevent. Prefer varying the **number of ports**: `MergeNode(inputs=3)` exposes three single-valued typed ports. Same expressive power, no ambiguity, and the wiring stays visually explicit. Genuine buses (`tools`) remain the exception, declared as such.

Settle: which node types are buses, and which expose configurable arity via dynamic ports.

### Bug to fix while typing this: `Infinity` is not JSON — **FIXED**

`AgentNode.ts:102` sets `maxConnections: Number.POSITIVE_INFINITY`, and `maxConnectionsOf()` returns `Number.POSITIVE_INFINITY` as the output default. **`Infinity` is not representable in JSON** — `JSON.stringify` emits `null`, and Pydantic/JSON Schema cannot express it either. It happens to survive today only because port descriptors live in code and are never serialised; the moment the node-type manifest is emitted (ticket 18) it becomes a silent coercion.

Fix as part of the Pydantic model: **`max_connections: int | None`, where `None` means unlimited.** Never put a non-finite float in a serialisable field. Cross-reference ticket 19 (canonical serialization) and ticket 02 (generated types).

**Done ahead of the Pydantic work**, since it was a one-line type change guarded by a test sweep and the TypeScript side is the source the generator will mirror. `maxConnections?: number | null`, `maxConnectionsOf(): number | null`, `null` = unlimited. Two details worth carrying into the Pydantic model:

- The resolution check is `=== undefined`, not `!= null`. `null` is a *declaration* (unlimited) and `0` is a real cap; a `!= null` or truthiness check would silently fall both through to the direction default.
- `capacityRule` no longer leans on `Number.isFinite`; it branches on `null` explicitly, and returns early for an unlimited input before counting occupants.

Guarded by `core/model/contracts/ports.test.ts`, which sweeps **every registered node type's ports** and asserts each descriptor survives `JSON.parse(JSON.stringify(...))`. That sweep is the part that keeps this fixed — it fails for any future node type that declares a non-finite cap, rather than relying on anyone remembering this note. It reads ports via `definition.ports(defaultsFrom(definition.fields))`, since port sets are a function of data.

**Tension to resolve — and it reverses an earlier proposal in this ticket.** Above, `DeepAgentNode extends ReactAgentNode` was proposed because `create_deep_agent` wraps `create_agent`. That breaks `Final*` = leaf: `ReactAgentNode` would be both a registered leaf *and* a base.

Two ways out:

- **(A) Siblings.** `IAgentNode → BaseAgentNode → { FinalReactAgentNode, FinalDeepAgentNode }`. `Final*` stays strictly a leaf. The fact that `create_deep_agent` is built on `create_agent` becomes a **compiler** detail, not a class-tree detail.
- **(B) Chain.** `FinalDeepAgentNode extends FinalReactAgentNode`, mirroring the library but abandoning leaf semantics.

**(A) is likely correct**, and the reason generalises: the class tree models *authoring configuration*; the compiler models *runtime construction*. They are different concerns and conflating them is what makes hierarchies brittle — a change in how LangChain composes `create_deep_agent` should not reshape our authoring model. Decide explicitly, and record the reasoning either way.

Also settle: prebuilt agent *shapes* the user picks from — single loop, orchestrator, router-style. Are these separate `Final*` classes, or configuration of one? They differ in topology, not just config, so probably classes.

## Subagents are isolated — confirmed

The user's model is correct and the docs bear it out: a subagent is invoked as a **tool**, and "when the subagent finishes, its structured response is JSON-serialized and returned as the `ToolMessage` content to the parent agent" (or its last message text, without `response_format`). Subagents therefore do **not** share the parent's message history or graph state — they receive a task and report a result.

Consequences to design around:
- Graph state flows down to *nodes* via the shared state schema; it does **not** flow into subagents. Two different mechanisms, and the UI must not imply otherwise.
- A subagent spec carries its own `model`, `system_prompt`, `tools` and optionally `response_format` — so the subagent list (ticket 20) is a repeatable group, not a multi-select.
- `response_format` on a subagent is what makes its result machine-usable by the parent. Decide whether the editor exposes it.

## Shared concerns on the base — the specific design to settle

Requirement: middleware and every other component shared by all agents lives on the base class, not duplicated per concrete type. CLAUDE.md now records the principle and its boundary; this ticket must produce the actual design.

Decide concretely:
- **Where the 60+ shared agent fields are declared.** Ticket 22 enumerated them (summarization, context-editing, filesystem, subagents, HITL, fault-tolerance, PII). They belong once on `AbstractAgentNode`. Confirm that, and confirm concrete types (`ReactAgentNode`, `DeepAgentNode`, …) add only what is genuinely theirs.
- **`resolveMiddleware(config) -> list` on the base**, as the single place config becomes middleware. Then settle the hard part: **how a subclass contributes middleware at a specific position**, given LangChain middleware order is significant and `super() + [mine]` can only append. Options: an ordered slot/priority scheme, an explicit pipeline the base assembles from named stages, or subclasses declaring `(stage, middleware)` pairs. Pick one — appending-only will not survive contact with HITL, which must wrap tool calls rather than sit at the end.
- **The cross-family cases.** Retry, token accounting and logging are wanted by agent nodes *and* tool nodes, which are different families. Per CLAUDE.md these are collaborators, not a shared superclass. Decide the mechanism (middleware registry? decorator applied at compile time?) and prove it does not force a common ancestor to fatten.
- **Where this lives in Python vs TypeScript.** The Python side composes real LangChain middleware; the TypeScript side only ever holds *config* (it never runs middleware). So the "shared base" means two different things per language — the TS base shares the schema, the Python base shares the resolution. Make that split explicit, and confirm it survives ticket 02's finding that Pydantic flattens inheritance in generated output.

---

## Middleware composition — resolved from the docs, and it reshapes the class tree

Verified against `docs-langchain`. Two findings, the second decisive.

### 1. List position means three different things at once

| Hook | Order |
| --- | --- |
| `before_*` | first to last |
| `after_*` | **last to first (reverse)** |
| `wrap_*` | nested — first middleware wraps all others |

So `super().resolveMiddleware() + [mine]` does **not** mean "mine runs last". It
means: my `before_*` runs last, my `after_*` runs **first**, and I am the
*innermost* wrapper. The ticket's worry that appending "will not survive contact
with HITL" is confirmed, but the reason is worse than stated: **there is no
single positional semantic to reason about**, so any scheme that expresses
position as one number — append, prepend, or a priority integer — is
expressing something that does not exist. A developer setting
`priority=10` cannot know what they have ordered.

### 2. `create_deep_agent` already solved this, and its answer is not inheritance

`createDeepAgent` "builds middleware in a **fixed order**" — 12 documented
slots, each conditional on whether the matching config was supplied:

`Skills → Filesystem → SubAgent → Summarization → PatchToolCalls →
AsyncSubAgent → **your middleware** → harness-profile extras → excluded-tool
filtering → prompt caching → Memory → HumanInTheLoop`

Three details that carry directly into our design:

- **The order encodes real constraints, with documented reasons.** Skills sits
  before Filesystem "so skill metadata is available before file tools run";
  `MemoryMiddleware` sits *after* prompt caching "so updates to injected memory
  are less likely to invalidate the cache prefix"; HITL is last, which — given
  `after_*` runs in reverse — is what puts its approval gate *first* among
  after-model hooks. These are semantic, not arbitrary. A numeric priority
  exposed to users would let them express an invalid order silently.
- **User middleware occupies one named slot** (7), not an arbitrary index.
- **Name-keyed replacement, not accumulation:** "An instance whose `.name`
  matches one of the built-in entries above **replaces that instance in place**
  instead of duplicating it."

### Decision

**`resolveMiddleware()` returns an ordered, name-keyed slot table — not a list.**
The abstract base owns the canonical slot order and the resolution from config; a
subclass or plugin contributes by *naming a slot*, never by appending. The
compiler flattens the table to a list as its last step. Replacement is by slot
name, mirroring the library.

This is CLAUDE.md's rule made concrete: **inherit the capability to compose, do
not inherit the composition.** The slot table is the capability; the filled
slots are the composition.

### Consequence: the (A)/(B) tension collapses, and (A) wins on stronger grounds

The ticket proposed (A) siblings vs (B) `DeepAgentNode extends ReactAgentNode`,
and reasoned that (A) is "likely correct" because authoring and runtime
construction are different concerns. The docs make it firmer than that:

**`create_deep_agent` is not `create_agent` plus subclassing — it is
`create_agent` plus a fixed slot assembly.** The relationship the library
actually expresses is *data*, not inheritance. So `DeepAgentNode` is not
"`ReactAgentNode` with more behaviour"; it is the same base configuration with a
different **slot preset**.

Adopt **(A)**, and the class tree stays deliberately shallow:

```
INode -> BaseNode -> AbstractAgentNode          shared config schema + slot table
                     |- ReactAgentNode          preset: empty (user slots only)
                     '- DeepAgentNode           preset: the 12-slot deep stack
```

A preset is a named, ordered slot table — a value in a `Registry`, not a class.
This means a third harness arrives as a *registered preset*, touching no class
and no `core/` file, which is the Open/Closed rule this project already applies
everywhere else.

It also removes the reason the tree wanted to be deep. Depth was being proposed
to model "deep agent = react agent + stack"; once the stack is data, the depth
buys nothing. Per CLAUDE.md — "inheritance must earn itself" — it does not here.

### Still open (needs the user)

- Whether agent *type* is a distinct registered node type per tier or a
  discriminant on one type. Affects the palette and the inspector, not the
  compiler.
- Whether prebuilt agent *shapes* (single loop, orchestrator, router-style) are
  classes or presets. Note they differ in **topology**, which presets cannot
  express — a preset changes middleware, not the graph.
- The `_abstract/` directory name.
