Type: task
Status: open
Blocked by: 11

## Question

Make `workflow.json` deterministic. This is a confirmed defect, not a hypothetical.

`WorkflowModel.toJSON()` serialises `this.nodes()`, which returns `[...this.nodeMap.values()]` — **Map insertion order**. Delete a node and undo, and it re-inserts at the end, so a logically identical graph serialises in a different order.

Consequences, given the file is git-tracked and read by coding agents:
- Every save can produce a whole-file diff, making review impossible.
- An agentic coder cannot tell what actually changed.
- Two users making the same edit produce different files, so merges conflict spuriously.

Work:
- Canonical ordering — sort nodes and edges by id on serialise. Confirm ids are stable and sortable (`nextId` mints `node:<type>-<n>`; note `-10` sorts before `-2` lexically, so either zero-pad or sort numerically).
- Stable key order in emitted JSON, and a fixed formatting convention (indent, trailing newline).
- A round-trip property test: `parse(serialise(g)) === g`, and `serialise(parse(s)) === s` byte-for-byte.
- A test proving delete-then-undo produces a byte-identical file.

Blocked by 11 because the round-trip and idempotence tests are the deliverable, not an afterthought.
