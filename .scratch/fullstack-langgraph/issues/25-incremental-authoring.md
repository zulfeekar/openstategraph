Type: grilling
Status: open
Blocked by: 09

## Question

Support the way the use case is actually authored: incrementally, by inserting into a graph that already runs.

From the use case — "developer decided to add another node to track/think, pipelined to something else". Nodes get inserted **between** existing nodes mid-build. Today that costs three manual operations: delete the edge, add the node, wire two new edges.

Decisions:
- **Splice-insert.** Dropping a node onto an existing edge should insert it inline — the edge is replaced by two edges through the new node. Confirm this is wanted, define the gesture (drop-on-edge highlight? a `+` affordance on edge hover?), and confirm it lands as a single undo step.
- **Type compatibility on splice.** The insert is only legal if the new node accepts the upstream output and produces something the downstream input takes. `ConnectionValidator` already answers this per link — reuse it to accept or reject the splice, and to *highlight which edges are valid drop targets* while dragging from the palette.
- **A "think" / trace node.** The use case names one. Is it a real node (a pass-through that records or reasons) or an annotation? If it passes data through unchanged its ports are polymorphic, which the current typed-port model cannot express — a genuine gap. Decide whether to add a pass-through / `any` port type or model it differently.
- Reconnecting rather than rewiring: dragging an existing edge endpoint to a new port. Phase 1 models edges as immutable (remove + add) — confirm that survives, since it is what makes undo exact.
