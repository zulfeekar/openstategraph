Type: grilling
Status: resolved
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

---

## Answer

### 1. The universal root already exists, is one field wide, and must stay that way

The requirement was "every concept derives from one extensible base". It already
does: `IIdentifiable { id }`, which `INodeDefinition` and every `Registry<T>`
entry extends. **Do not invent an `IEntity` on top of it.**

The tempting additions — `kind`, `version`, `metadata`, lifecycle hooks — each
fail for at least one family. An edge has no position; a provider is never placed
on a canvas; a tool is not selectable; only the discriminated families need
`kind`. A root carrying all of it is precisely the **god base class** CLAUDE.md
forbids, and an Interface Segregation failure: members would inherit capabilities
they cannot use.

So: **one shared field (`id`), and per-family interfaces below it.** The
hierarchy the requirement asks for is real, but it is *shallow at the root and
deep only inside a family* — which is where shared behaviour actually exists.

### 2. Where inheritance earns itself — and where it does not

Honest accounting, as the ticket demanded:

| Concern | Mechanism | Why |
| --- | --- | --- |
| Agent config schema (60+ fields, ticket 22) | **inheritance** — `AbstractAgentNode` | Genuinely shared by every agent; one reason to change |
| Middleware assembly | **data** — an ordered slot table | See the middleware section above; the library models it as data, not a class tree |
| Harness tier (react / deep) | **sibling leaves + a registered preset** | `create_deep_agent` is `create_agent` + a fixed slot assembly, not + subclassing |
| Retry / timeout / caching | **graph-assembly parameter** | Not a node concern at all — see §5 |
| Token accounting, logging | **middleware for agents; callbacks/tracing otherwise** | Different runtime mechanisms per family; a shared ancestor would be a lie |

Two structural reasons the tree stays shallow, both from the runtime rather than
from taste:

- **A LangGraph node is a function, not a class.** So a Python class tree over
  "nodes" models *authoring configuration*, never runtime behaviour. Deepening
  it adds no dispatch, only ceremony.
- **Pydantic flattens inheritance** (ticket 02, [pydantic#12071]): base classes
  never reach the generated schema. So any depth we add is *invisible* across the
  boundary — it cannot be relied on by a consumer of the generated types.

### 3. Agent tiers: three registered node types — decided

`ReactAgentNode`, `DeepAgentNode`, `CustomGraphNode` are separately registered
leaves, each with its own card, inspector and compile target.

Chosen over a `tier` discriminant on one type because the union of the three
config surfaces is 60+ fields, and a single card rendering all three makes
invalid combinations *expressible* — every one of which then needs a cross-field
validation rule to un-express. Three types make illegal states unrepresentable
instead, and give clean Liskov substitution with distinct compile targets.

**Accepted cost, recorded so it is not a surprise:** switching tier means
replacing the node, which drops its edges. Mitigation for ticket 13/25 — a
"convert tier" command that mints the new node, copies the fields the target tier
shares, and re-attaches every edge whose port survives. That is a command on the
existing stack, so it is one undo step.

```
INode -> BaseNode -> AbstractAgentNode        shared schema + middleware slot table
                     |- ReactAgentNode        -> create_agent
                     '- DeepAgentNode         -> create_deep_agent (deep slot preset)
         BaseNode -> CustomGraphNode          -> hand-written StateGraph node
         BaseNode -> ToolNode                 -> ToolNode / @tool
         BaseNode -> FunctionNode             -> plain callable
         BaseNode -> RouterNode               -> add_conditional_edges
         BaseNode -> GraderNode               -> evaluator-optimizer (ticket 24)
         BaseNode -> WorkflowNode             -> subgraph (ticket 05)
```

`DeepAgentNode` is a sibling of `ReactAgentNode`, not its subclass — reasoning in
the middleware section. A fourth harness arrives as a registered preset plus a
leaf, touching no `core/` file.

### 4. Prebuilt shapes are canvas templates — decided

A "shape" (single loop, orchestrator, router-style) differs in **topology**, and
a middleware preset cannot express topology. So shapes are **multi-node canvas
templates**: stamping one drops several wired nodes the developer then edits
freely. No new class, nothing opaque, and the result stays composable — which is
the property the whole use case rests on.

Rejected: a single `OrchestratorNode` compiling to a hidden subgraph. It reads
tidier and is worse — the internals are exactly what a developer needs to reach.

A template is therefore a `workflow.json` fragment plus paste-with-remapped-ids,
which the clipboard already does. Little new machinery.

### 5. Cross-family concerns: retry is not a node concern — it belongs to graph assembly

The ticket asked how retry/token-accounting/logging reach both agent nodes and
tool nodes without fattening a common ancestor. Verified against the docs, and
the answer is that **the premise was wrong for retry**: it is not an agent
capability at all.

`retry_policy=RetryPolicy(...)` is a parameter of **`StateGraph.add_node`**, so
it applies to *any* node of *any* family, and `StateGraph.set_node_defaults(...)`
applies retry, timeout and `error_handler` to **every node in a graph** without
repeating them per node (per-node values still win). `CachePolicy` works the same
way, and `error_handler` (needs `langgraph>=1.2`) runs a compensation branch
after retries are exhausted.

So the design is:

- **Workflow-level defaults** — `retry`, `timeout`, `error_handler`, `cache` live
  on the *workflow*, compiled to `set_node_defaults`. Declared once, inherited by
  every node, with no base class involved.
- **Per-node override** — an optional fragment on `BaseNode`, compiled to the
  `add_node` keyword.

This is CLAUDE.md's boundary rule confirmed by the library: a concern needed by
two different families turned out to be a **collaborator** (a graph-assembly
parameter), not a superclass. Anyone who had put `retry` on an agent base would
have had to duplicate it onto the tool base, and then reconcile two spellings of
one runtime feature.

Token accounting and logging stay genuinely per-family — middleware for agents,
LangGraph callbacks/tracing for everything else — so they are **not** unified.
Unifying them would mean inventing an abstraction the runtime does not have.

### 6. Authored entity vs runtime behaviour: the split survives in Python and dies in TypeScript

Phase 1 split `INodeDefinition` (serialisable authoring data) from
`INodeExecutor` (behaviour). Keep the split — ticket 23's one-directional compile
seam depends on it, and `INodeExecutor` / `IToolExecutor` being separate is the
Interface Segregation example CLAUDE.md cites.

But be explicit about a consequence nobody has written down yet: **ticket 07
ruled that the browser must never execute a workflow**, so the *TypeScript*
executor tier has no job once the FastAPI runtime lands. `core/execution` and
`core/providers` are phase-1 artefacts — which is exactly why ticket 11 recorded
their 10%/17% coverage as a stated gap rather than a debt. They are scheduled for
deletion, not for tests.

What survives on the TS side is `INodeDefinition` — schema, ports, defaults,
validation. Authoring only.

### 7. Which ports are buses

Only one today, and one that should become one:

| Port | Verdict |
| --- | --- |
| `tools` (agent) | **Bus.** `maxConnections: null`. Confirmed. |
| `skill` (agent) | **Should become `skills`, a bus.** `SkillsMiddleware` takes a *list*, and the project rule is that anything plural is a list by default. A single-slot `skill` port silently caps a list-valued config at one. |
| `prompt` (agent) | Single. Two prompts is meaningless. |
| `result` and all outputs | Unlimited by default. Fan-out is normal. |

Everything else varies **port count**, never port cardinality — a port whose type
changes between scalar and list at runtime is what typed ports exist to prevent.

Renaming `skill` → `skills` changes the shipped catalogue and any saved file
referencing that port id. It is cheap now and gets expensive the moment real
workflows exist, so it belongs in the next implementation ticket, with a
serializer migration. Filed as its own concern rather than done here, because
ticket 19's loader already drops links to vanished ports *with a warning* — so
without a migration, every existing file would silently lose its skill wiring.

### 8. Python vs TypeScript: the base means two different things

Made explicit, as the ticket required:

| | TypeScript | Python |
| --- | --- | --- |
| What the base owns | the **config schema** | the **resolution** — config to middleware |
| Runs middleware | never | always |
| Hierarchy source | hand-written | hand-written |
| Field types | **generated** from Pydantic | source of truth |

The subtlety that follows from ticket 02: because Pydantic flattens inheritance,
**the generated TypeScript can never express our ladder.** So the ladder is
hand-written on the TS side and *consumes* generated flat field types. The
generator owns data shapes; it does not own the class tree. Anyone expecting
`generated.ts` to contain `extends` will be confused — it never will.

### 9. Directory convention: `abc/` — decided

```
workflows/text-to-sql/
  nodes/          concrete node classes — registered in the palette
  functions/      concrete callables
  tools/          concrete tools
  abc/            I* interfaces and Base*/Abstract* classes — never registered
```

Mirrors Python's stdlib `abc`, and the same word works in both languages.

**Checked the obvious hazard rather than assuming it:** a workflow-local `abc/`
package does **not** shadow stdlib `abc`, even with the workflow directory as
`sys.path[0]`. `abc` is imported during interpreter startup and is already in
`sys.modules` before any user code runs, so `from abc import ABC` resolves to the
stdlib every time. Verified directly.

Worth noting the rule this *doesn't* generalise to: a directory named after a
stdlib module that is **not** pre-imported — `json/`, `csv/`, `secrets/` — would
shadow it. `abc/` is safe specifically because of the startup import. Discovery
(ticket 18) should still import workflows as a package rather than putting the
workflow directory on `sys.path`, which makes the question moot regardless.

### Downstream

Unblocks 09, 10, 18, 20, 24. Ticket 20 (cardinality fields) is now largely
answered — the `skills` bus and the "vary port count, not cardinality" rule are
settled here; what remains for it is the repeatable-group UI for subagent specs.
