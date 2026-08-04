Type: grilling
Status: resolved
Blocked by: 03, 05, 08

## Question

How are "graph" and "loop" exposed to the user in the editor?

Given: canvas = `StateGraph`, Agent node = `create_agent` loop, composition = subgraphs.

Decisions:
- Is there one document type (a graph, in which some nodes happen to be loops), or two authorable kinds? The user distinguishes them conceptually — does the UI need to?
- How are **conditional edges** authored? A router node with N labelled outputs, a predicate on the edge itself, or both? What does the canvas capture per edge (depends on 03)?
- How does a user see that an Agent node is internally a loop — is the loop inspectable / expandable on the canvas?
- **Found while writing tests: `acyclicRule` is currently unreachable dead code.** No cycle is expressible with the shipped catalogue — the only input that accepts a `result` is on the output node, which has no output port, so there is no type-legal path back. The rule can only be exercised against a synthetic symmetric-port node type (see `registerLoopableType` in `core/testing/fixtures.ts`). This *changes the shape of the work*: cycles are not currently forbidden by the rule so much as inexpressible by the port-type graph. Enabling grader loop-back therefore needs a port-type path that permits it — scoping `acyclicRule` alone is not sufficient.
- **Cycles are on the critical path, not optional.** Phase 1 forbids them via `acyclicRule`, but the use case *requires* one: grader rejects → loop back to the generator (LangGraph's evaluator-optimizer pattern). So the rule must be scoped, not global. Decide what remains forbidden — an unbounded cycle with no termination path is still a bug worth catching, and LangGraph's own answer is a `recursion_limit` raising `GraphRecursionError`. Likely: allow cycles, but require every cycle to contain at least one conditional edge with a reachable exit, and surface `recursion_limit` as workflow config. Feeds ticket 24.
- Where does a compiled-graph preview belong (LangGraph can emit Mermaid)?

---

## Answer

### 1. One document type. The canvas *is* a `StateGraph`; a loop is a node in it

There are not two authorable kinds. The user distinguishes graph from loop
conceptually, but that distinction is already carried by the **node type** —
ticket 08 settled three registered agent tiers, so "this node is a loop" is
visible from its card without a second document mode.

Two authorable kinds would fork the palette, the inspector, the serializer and
the compiler, to express something one field already expresses. Rejected.

### 2. Conditional edges: the predicate lives on the router node, the branch key on the edge

Not "either/or" — each half belongs somewhere different, and splitting them the
other way breaks something concrete.

| What | Where | Why |
| --- | --- | --- |
| The predicate (a JSON AST) | **the router node** | Ticket 03 established the canvas must capture the router's *complete declared destination set*, or every renderer draws it as connected to every node. A predicate smeared over N edges makes that set implicit and unrenderable. |
| The branch key (which case this edge serves) | **the edge** | It is per-edge by definition, and it is what `path_map` needs. |

Three further reasons the predicate cannot live on edges:

- `add_conditional_edges(source, path, path_map)` takes **one** `path`
  function. N edge-predicates would have to be merged into one function at
  compile time, and merge order would silently decide precedence.
- Ticket 23's guardrail says expressions are a serialisable JSON AST. One AST on
  one node is reviewable in a diff; N fragments across N edges is not.
- Ticket 03's hard rule — a node must never have both static edges and dynamic
  routing, because **both execute** — is enforceable on a node in one check. On
  edges it would need a whole-graph pass.

### 3. The Agent loop is inspectable but not expandable — a read-only compiled preview

The loop's internals are **generated**, not authored. Making them an expandable
group on the canvas would imply they are editable, and editing them would mean
reading runtime structure back into the model — exactly what ticket 23's
one-directional compile seam forbids.

So: an Agent node shows a "view compiled graph" affordance that renders the real
thing, obtained from the compiled object via
**`compiled.get_graph(xray=True).draw_mermaid()`**. `xray=True` expands subgraph
internals, so this is the loop as it actually compiled, not a hand-drawn
approximation that can drift from the compiler.

**Use `draw_mermaid()`, never `draw_mermaid_png()`.** The `_png` variant defaults
to posting the graph to the **Mermaid.Ink API** — a third-party network call that
would ship the structure of a user's private workflow off the machine. The
alternatives it offers are local but need extra dependencies (pyppeteer or
graphviz). `draw_mermaid()` returns Mermaid *text* with no network and no extra
dependency; the frontend renders it. This is a privacy requirement, not a
preference — record it as a hard rule.

### 4. Cycles: the port *type* is the gate, and the rule stops being about cycles

The finding from ticket 11 reframed this: cycles are not currently *forbidden*,
they are **inexpressible** — no input accepts a `result`, so there is no
type-legal path back. So the question is not "how do we relax `acyclicRule`" but
"where do we deliberately open a typed path back".

**Design: a dedicated feedback port type.**

```
GraderNode   outputs:  pass   : result       -> onward
                       revise : feedback     -> back upstream
AgentNode    inputs:   feedback : feedback   (new, single-slot)
```

A loop is drawable only where someone declared a `feedback` input. The type
system stays the gate, so an *accidental* cycle remains impossible to draw, while
the evaluator-optimizer pattern the use case requires becomes a two-click wiring
job. No rule relaxation, no global escape hatch.

**Termination has three layers, and only the middle one is ours:**

1. **The conditional edge.** A cycle must contain at least one — a cycle of only
   static edges can never terminate. This is what `acyclicRule` becomes:
   `staticCycleRule`, rejecting all-static cycles rather than all cycles.
2. **`recursion_limit`,** surfaced as workflow config. Standalone `config` key —
   **not** inside `configurable`, which is the easy mistake. Default is 1000 in
   Python (since 1.0.6) and 25 in JS; exceeding it raises `GraphRecursionError`
   (`GRAPH_RECURSION_LIMIT`).
3. **`RemainingSteps`,** a managed state channel exposing the steps left. A
   grader's router can read it and return `END` instead of dying, turning a
   runaway loop into a degraded-but-complete run rather than a crash. Recommend
   the editor generate this guard automatically for any cycle it compiles.

**Honesty requirement for the UI: `recursion_limit` counts supersteps, not
iterations.** The docs' own branch example shows one lap of a loop costing four
supersteps when a step fans out to two nodes. Labelling the field "max
iterations" would make a limit of 10 mean two laps in one graph and ten in
another. Label it "step budget" and say what a step is.

**And be honest about `staticCycleRule`: it is unreachable by construction
today**, exactly as `acyclicRule` was, because the only cycles the port types
permit go through a conditional `feedback` edge. It is kept as defence for future
node types, and it is testable — `registerLoopableType` in the fixtures exists
precisely to exercise a rule the shipped catalogue cannot reach. Recording this
so nobody later "discovers" the dead code again and deletes it.

### 5. The compiled-graph preview is a panel, fed by the backend

The Mermaid text comes from the compile step, which lives in Python — the
TypeScript side has no compiled object to introspect and must not acquire one.
So: the backend returns Mermaid text alongside the compile result, and the editor
renders it in a panel (and in the Agent node's inspector for the `xray` view).

This is a second, weaker projection of the same model. It is worth having despite
the duplication, because it shows what the *compiler* produced rather than what
the canvas believes — the one view that can reveal a compiler bug.

### Downstream

Unblocks 13 (router prototype), 24 (grader node), 25 (incremental authoring).
Ticket 24 is now largely specified: the grader's two typed outputs and the
agent's `feedback` input are the whole of its topology contract.
