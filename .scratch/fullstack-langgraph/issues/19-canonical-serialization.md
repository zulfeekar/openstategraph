Type: task
Status: resolved
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

## Answer

Done, red-first. Three independent sources of drift, not one:

1. **Row order** — `toJSON()` emitted `Map` insertion order. Nodes now sort by
   id through `compareNatural` (`core/kernel/ordering.ts`), so `-2` precedes
   `-10`. Sorting lexically would have been equally *deterministic* and
   unreadable in a diff — a worse failure, because it looks correct.
2. **Key order** — `data` was spread, and `JSON.stringify` follows insertion
   order, so identical values serialised differently depending on which field
   the user edited first. `withSortedKeys` fixes the emitted record.
3. **Edge ids** — the one that actually needed a design decision. An edge id is
   a global creation counter, and nothing references an edge by id (edges
   reference nodes; nothing references edges). Writing it leaked build order
   into the file: two people drawing the same graph in a different order got
   different bytes, and inserting one link renumbered every row after it.
   Edges are now **content-addressed** — identified and sorted by their
   endpoint tuple, with no `id` written, and a fresh handle minted on load.
   Older files still load; their edge ids are ignored rather than migrated,
   which needs no version bump because it only narrows what is read.

Formatting is fixed at two-space indent plus a trailing newline.

Tests: `core/kernel/ordering.test.ts` (11) and the `determinism` / `canonical
order` blocks of `core/serialization/WorkflowSerializer.test.ts`. The two
originally-red tests were delete-then-undo and creation-order.

Commit: 52f96f7 (+ trailing newline follow-up).
