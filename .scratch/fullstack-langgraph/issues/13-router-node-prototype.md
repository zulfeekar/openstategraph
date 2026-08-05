Type: prototype
Status: resolved
Blocked by: 03, 09

## Question

Prototype the router node on the canvas — raise the fidelity of the routing discussion with something concrete to react to.

Build the cheapest artifact that answers: what does a router node *look like*, and how does a user author its branches?

Cover: how N labelled outputs are rendered without the card becoming unreadable; whether a branch condition is edited on the node or on the edge; how a default/fallback branch is shown; and how it reads when three branches fan out to three different node types (the user's scenario).

Use `/prototype`. Link the artifact from this ticket; do not paste it inline.

---

## Answer — built, not sketched

`src/nodes/routing/RouterNode.ts` + 22 tests. It went straight to a real node type
rather than a throwaway prototype because the mechanism turned out to need **no new
engine concept**, so there was nothing to de-risk first.

### The four questions

**How do N labelled outputs render without the card becoming unreadable?** Fine at
five: a 5-branch router is a 292px card with all six port labels legible
(`question`, `dataquery`, `info`, `help`, `greeting`, `off_topic`), verified in the
browser. Capped at **12** branches rather than made scrollable — a router with
twenty destinations is a design problem the editor should surface, not hide.

**Is the condition edited on the node or the edge?** **On the node**, and this
confirms ticket 09 survives a config-driven branch list. One `instruction` field
does the classifying; an edge's branch is decided by *which port it leaves from*.
So the "branch key on the edge" from ticket 09 needs no separate edge field — **the
port ID is the branch key**, which is a simplification ticket 09 did not anticipate.

**How is a fallback shown?** A `fallback` field naming one of the branches. That
port's description becomes "Fallback — taken when no other branch matches", so it
is visible on hover and in the inspector's Ports list rather than being a hidden
rule.

**How does it read fanning out to three different node types?** Each output is
`PORT.text`, so a branch wires to anything accepting text — an agent's `prompt`, an
output node. No new port type was needed.

### Mechanism: nothing new was required

`INodeDefinition.ports` has **always** been `(data) => IPortDescriptor[]`. The
Router is simply the first node type to use it. So "drag a router, name your
branches, wire them" needed one node file, and it produces ticket 03's complete
declared destination set from ordinary config — no engine change, no `core/` edit.
That is the Open/Closed claim in ticket 28 demonstrated rather than asserted.

The tier field also renders as intended: the inspector shows **Runtime ·
`Agent · create_agent`**, so role-as-node-type with tier-as-field (ticket 28) is
visibly working.

### Two things found while building

**A `standard` node with no TypeScript executor is silently skipped by the preview
engine.** The harness test caught this the moment the Router was registered. Rather
than weaken the invariant, the Router ships an executor that **refuses with a clear
message** — a router compiles to `add_conditional_edges` in Python, and the browser
must not execute (ticket 07). It deliberately does *not* classify using the mock
provider, which would fake a decision the real runtime makes differently, and it
will be deleted along with `core/execution`.

**Renaming a branch drops its edge.** Port ids derive from branch names, so a
rename changes the id and the serializer discards links to ports that no longer
exist (with a warning — ticket 19). Recorded as a sharp edge in the source. The fix
needs **stable per-branch ids**, which is exactly what ticket 20's repeatable-group
field would give: each branch carrying a generated id alongside an editable label.
Branches are newline-separated text until then; inventing a field kind inside this
ticket would have settled ticket 20 by accident.

### Not done here

The **Python compile target** — turning a Router node in `workflow.json` into
`add_conditional_edges` — is ticket 15's job. This ticket delivers the authoring
half.
