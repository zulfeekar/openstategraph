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

### Bug to fix while typing this: `Infinity` is not JSON

`AgentNode.ts:102` sets `maxConnections: Number.POSITIVE_INFINITY`, and `maxConnectionsOf()` returns `Number.POSITIVE_INFINITY` as the output default. **`Infinity` is not representable in JSON** — `JSON.stringify` emits `null`, and Pydantic/JSON Schema cannot express it either. It happens to survive today only because port descriptors live in code and are never serialised; the moment the node-type manifest is emitted (ticket 18) it becomes a silent coercion.

Fix as part of the Pydantic model: **`max_connections: int | None`, where `None` means unlimited.** Never put a non-finite float in a serialisable field. Cross-reference ticket 19 (canonical serialization) and ticket 02 (generated types).

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
