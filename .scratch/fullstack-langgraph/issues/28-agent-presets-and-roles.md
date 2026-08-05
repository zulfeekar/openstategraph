Type: grilling
Status: resolved — every role this ticket named is now a built, tested node type
Blocked by: 08

## Question

The user's requirement, restated:

1. **The generic path must work.** Drag an Agent onto the canvas, type a system
   prompt, tick "structured output", draw three edges out — and that agent *is* a
   router. Nothing about routing is special-cased in the engine.
2. **The prebuilt path should also exist**, because most developers should not
   have to assemble a router from parts: ship **Router**, **Supervisor** and
   **Orchestrator** nodes with the behaviour already wired, drag-and-drop.
3. **The tier is a developer choice** — "drag an agent and say whether it is a
   simple agent, or a deep agent, or whatever else."
4. State, context and memory must **drill down** per LangGraph/LangChain best
   practice.

Both paths are right and they are not in tension: **a preset is a
*registration*, never engine code.** That is the Open/Closed rule this codebase
already applies everywhere — a new capability must not require touching `core/`.
A Router is a registered entry in `NodeTypeRegistry` whose defaults happen to be
a classification prompt, a structured verdict schema, and outputs derived from
config. A developer who wants to build the same thing from a plain Agent still
can, and *must* be able to, or the presets have become privileged.

---

## This reverses part of ticket 08, and the reason matters

Ticket 08 settled: **three registered node types, one per tier**
(`ReactAgentNode`, `DeepAgentNode`, `CustomGraphNode`), chosen because the union
of their config surfaces is 60+ fields and one card rendering all three makes
invalid combinations expressible.

Requirement 2 breaks that, arithmetically. If **role** is also a node type, the
palette becomes role × tier:

| | React | Deep | Custom |
| --- | --- | --- | --- |
| plain agent | ✓ | ✓ | ✓ |
| router | ✓ | ✓ | ✓ |
| supervisor | ✓ | ✓ | ✓ |
| orchestrator | ✓ | ✓ | ✓ |

Twelve palette entries for two independent axes, growing multiplicatively with
every future role. That is not scalable, and the user explicitly asked for the
long-term answer.

**Resolution: role is the node type; tier is a config field.**

- **Role** decides *topology and compile target* — how many ports, what the node
  becomes in the graph. It is what a developer reaches for in the palette, and it
  cannot be changed without rewiring, so it belongs to identity.
- **Tier** decides *which factory builds the loop* — `create_agent`,
  `create_deep_agent`, or a hand-written node. It changes no ports and no edges,
  so it is safely a field.

Ticket 08's actual concern is preserved: illegal states stay unrepresentable
because validation is **per role**, and the 60+ field surface is handled by the
progressive disclosure ticket 22 already made mandatory, keyed on the tier field.
What ticket 08 got wrong was assuming tier was the *only* axis. It is the one that
should have been the field.

Record this as a supersession on ticket 08 rather than a silent change.

## The four roles and what each compiles to

| Role | Ports | Compiles to |
| --- | --- | --- |
| **Agent** | `prompt`, `skills` (bus), `tools` (bus), `result` | the tier's factory |
| **Router** | one input; **N outputs from config** | `add_conditional_edges(src, path, path_map)` with the complete declared destination set |
| **Supervisor** | one input; one `workers` output; one `result` | **`Send` fan-out** to a declared worker node — the only observable form (ticket 27) |
| **Grader** | `candidate` in; `pass` + `revise: feedback` out | conditional edge; the typed `feedback` port is what makes a cycle legal (ticket 09) |

**The mechanism for N outputs already exists** and needs no new concept:
`ports: (data) => IPortDescriptor[]` is already a function of node data. A router
configured with four branches exposes four output ports. This is exactly the case
CLAUDE.md says to prefer — *vary the number of ports*, never toggle one port's
cardinality.

So "drag a Router, name your branches, wire them" produces the declared
destination set ticket 03 requires, from ordinary config.

## What is a node type versus a canvas template

Ticket 08 answered "prebuilt shapes" as **canvas templates**. That still stands;
this refines rather than replaces it. The test:

- Does it stay **one node** whose behaviour is config? → **node type.** Router,
  Supervisor, Grader qualify.
- Does it require **several wired nodes**? → **template.** "Orchestrator
  pattern" — supervisor + worker + grader + synthesiser — is a topology, and a
  preset cannot express a topology.

So *Orchestrator* is probably a template, while *Supervisor* is the node inside
it. Settle the naming so the palette does not offer both under confusable names.

## State, context and memory — the drill-down rules

Not negotiable, and easy to get wrong in the UI:

| Concern | Mechanism | Scope |
| --- | --- | --- |
| Graph state | shared state schema + named reducers | flows to **nodes** |
| Thread memory | checkpointer (`thread_id`) | one conversation |
| Cross-thread memory | `Store`, `(namespace, key)` | across conversations |
| Subagent context | **none — isolated** | receives a task, returns a result |

**The rule the UI must not violate:** state flows *down to nodes*; it does **not**
flow into subagents. A subagent gets a task and reports back as a `ToolMessage`
(or a `Send` payload). Any inspector affordance implying a subagent inherits the
parent's history or graph state is a lie, and would teach developers something
false about their own workflow.

Consequence for the Supervisor node: its config declares **what each worker is
sent**, and that payload is the *entire* context the worker gets. Making that
explicit in the card is a feature, not a limitation.

## Decisions to settle

- Naming: Supervisor vs Orchestrator vs Parent Agent — the user used all three.
  Pick one for the node, one for the template, and never both for the same thing.
- Does the Router's branch list also carry its predicate, or does the *edge* carry
  a per-branch condition? Ticket 09 settled predicate-on-node, branch-key-on-edge;
  confirm that survives a config-driven branch list.
- Where does the tier field live in the schema so the generated TypeScript keeps a
  discriminated union? Ticket 02: a required `Literal` with no default.
- Is `Grader` a role or just an Agent with a structured verdict schema? It has a
  distinctive *port* shape (`revise: feedback`), which argues role.

## Resolved (2026-08-05) — settled by what got built, recorded here

Every role this ticket asked for exists as a real, tested node type:
`agent.llm` (plain Agent + system prompt = "the generic path", per this
ticket's own requirement 1), `route.classifier` (Router, ticket 13),
`route.grader` (Grader, ticket 24 — including a working `deep` tier as of
this session, not just a cosmetic field), `orchestrate.supervisor` +
`orchestrate.worker` (this session). Tier-as-config-field / role-as-node-type
holds exactly as this ticket argued: switching tier changes which factory a
node compiles through, never its ports or edges.

**Naming, settled**: the node is **Orchestrator** (label) /
`orchestrate.supervisor` (type id) — not "Supervisor" or "Parent Agent", the
other two names the user tried during grilling. "Orchestrator pattern" as a
multi-node **topology** (Orchestrator → Worker → report → Grader) is
demonstrated as a hand-wired document in
`backend/tests/test_intent_routed_workflow.py`, not shipped as a
one-click canvas **template** — dragging four nodes and wiring them is not
onerous enough yet to justify a template mechanism that does not otherwise
exist in this codebase. Revisit if template-worthy multi-node patterns
accumulate.

**Is Grader a role or "just an Agent with a schema"?** Settled as **role**:
its `revise: feedback` port shape is the only thing in the catalogue that can
close a cycle (ticket 09), which is a structural property no generic Agent
config could express without becoming the Grader in disguise.

**Confirmed still holding**: predicate-on-node/branch-key-on-edge (ticket 09)
survived the config-driven branch list unchanged — `RouterNode.ts`'s branch
port ids are still literally the branch names. The `tier` field's home in the
schema (a required `Literal`, no default) has not been re-verified against
generated TypeScript this session, since no codegen step exists yet (ticket
02's own recorded gap) — nothing to check against.
