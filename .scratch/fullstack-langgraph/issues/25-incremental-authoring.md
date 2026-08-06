Type: grilling
Status: resolved (2026-08-06) — splice-insert implemented exactly per the settled design below. See map.md's "Implement ticket 25" entry, `SpliceInsertCommand` (edgeCommands.ts), `EdgeEditor.insertOnEdge`, `closestEdgeToPoint` (topology.ts). The "think"/trace polymorphic-port question below remains open — that was scoped out of this ticket as a separate ports-and-types decision, not implemented.
Blocked by: 09

## Question

Support the way the use case is actually authored: incrementally, by inserting into a graph that already runs.

From the use case — "developer decided to add another node to track/think, pipelined to something else". Nodes get inserted **between** existing nodes mid-build. Today that costs three manual operations: delete the edge, add the node, wire two new edges.

Decisions:
- **Splice-insert.** Dropping a node onto an existing edge should insert it inline — the edge is replaced by two edges through the new node. Confirm this is wanted, define the gesture (drop-on-edge highlight? a `+` affordance on edge hover?), and confirm it lands as a single undo step.
- **Type compatibility on splice.** The insert is only legal if the new node accepts the upstream output and produces something the downstream input takes. `ConnectionValidator` already answers this per link — reuse it to accept or reject the splice, and to *highlight which edges are valid drop targets* while dragging from the palette.
- **A "think" / trace node.** The use case names one. Is it a real node (a pass-through that records or reasons) or an annotation? If it passes data through unchanged its ports are polymorphic, which the current typed-port model cannot express — a genuine gap. Decide whether to add a pass-through / `any` port type or model it differently.
- Reconnecting rather than rewiring: dragging an existing edge endpoint to a new port. Phase 1 models edges as immutable (remove + add) — confirm that survives, since it is what makes undo exact.

## Design settled, implementation deferred (2026-08-05)

Decided, not built — recorded precisely so a future session implements this
instead of re-litigating it:

- **Splice-insert, confirmed as the right gesture.** Dropping a palette node
  onto an existing edge should replace that one edge with two, through the
  new node, as **one undo step**. `WorkflowController`'s existing
  transaction support (`CommandStack`'s coalescing/transactions, already
  used elsewhere for multi-step edits) is the mechanism — no new undo
  primitive is needed, only a command that does remove-edge +
  add-node + add-two-edges atomically.
- **Type compatibility reuses `ConnectionValidator` exactly as proposed** —
  the splice is legal only if the dropped node's *default* input port accepts
  the edge's source type and its *default* output port satisfies the edge's
  target type. No new validation concept; the same `typeCompatibilityRule`
  chain that already gates an ordinary drag-to-connect gates this.
- **The "think"/trace node names a real gap, not a new node.** A pass-through
  node with polymorphic ports (accepts and re-emits whatever type arrives)
  cannot be expressed by the current typed-port model, which has no `any`
  port type. This is a genuine, separate design decision (does `PORT.text`
  grow an `accepts: '*'` sibling, or does a dedicated pass-through type exist
  per data kind?) — left open rather than folded into this ticket's own
  scope, since it is really a ports-and-types question, not an authoring-UX
  one.
- **Edges stay immutable** (remove + add, never mutate-in-place) — confirmed
  as still correct; nothing built this session gave a reason to revisit it,
  and it is what keeps undo exact.

**Not implemented**: the actual drop-on-edge hit-testing and highlight
gesture in `CanvasStage.tsx`/`PaperController.ts`. This touches a sensitive,
load-bearing piece of the canvas (pointer-driven drag/drop against JointJS's
own link geometry) that deserved dedicated attention and testing this
session's remaining scope did not have room for without risking a fragile,
under-tested landing in core interaction code — the kind of corner CLAUDE.md's
own TDD rule argues against cutting. The design above is complete enough to
implement directly next time.
