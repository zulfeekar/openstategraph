Type: grilling
Status: resolved v1 (2026-08-07) — 0274129
Blocked by: 30, 36

## Question

"Canvas = StateGraph, workflow composition = subgraphs" is settled vocabulary
with no implementation: one `StateGraph` per compile, `add_node` only ever
receives a plain callable, and no node type references another workflow.

Design `workflow.subgraph`:

- The node names another workflow by slug; the compiler loads that document,
  compiles it (recursively), and calls `add_node(name, compiled_graph)`.
- State mapping: the child's RunState is the same schema today — is that a
  guarantee or a coincidence? Explicit key mapping in/out, or shared schema
  with reducers doing the work? (A subagent-style isolation boundary is the
  *other* mechanism — do not conflate; CLAUDE.md's "state flows down;
  subagents do not receive it".)
- Cycle safety: a workflow that includes itself must be refused at plan
  time with a readable diagnostic.
- Streaming: `subgraphs=True` is already on; the sidebar keys on namespace —
  verify a real nested subgraph's namespace arrives as documented.
- Frontend: a card showing the child workflow's name with drill-in; palette
  lists open-able workflows from `WorkflowStore.list()`.

## Resolution

`workflow.subgraph` compiles the child at build time (self-inclusion refused with the chain named) and invokes with explicit mapping: upstream text in as question, answer out. Shared RunState is a deliberate v1; namespace-verified streaming and drill-in UI remain fog.
