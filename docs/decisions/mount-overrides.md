# Per-mount overrides for mounted organisms (Team / Subgraph)

**Status: accepted, implemented.**

## Problem

A Team (`team.workflow`) or Subgraph (`workflow.subgraph`) node references one
shared package. Two mounts of `chinook-metrics-team` share one definition — which
is correct OOP (class vs instance) — but a user legitimately wants *this*
mount to differ: a stricter grader outcome, a different `maxAttempts`, another
model. Today the only option is forking the package, which destroys the single
source of truth.

## Design

**Shape.** The mount node's `data` gains one optional field:

```json
"overrides": {
  "<childNodeId>": { "<fieldKey>": <JSON value>, ... },
  ...
}
```

- Plain JSON, keyed by the child document's own node ids and field keys — the
  vocabulary that already exists in `workflow.json`. No expressions, no host
  language, no new enum (CLAUDE.md portability rule 1: data, never code).
- Values replace the child node's field value (shallow, per key). Removing a
  key is not expressible — an override narrows, it does not delete; deleting
  behaviour belongs in the package itself.

**Where it applies.** Exactly one place: `apply_mount_overrides()` in
`compile/node_runtime.py`, called on the freshly loaded child document before
the child `WorkflowCompiler().build(...)`. The child document on disk is never
written — the compile seam stays one-directional; the merge exists only in the
in-memory copy handed to the compiler. Recursion composes naturally: a child
that itself mounts a grandchild applies its own `overrides` on the way down.

**Validation is loud, not fatal.** An override naming an unknown child node id
is reported through the same channel as an unresolved tool
(`runtime.override_warnings` → `runtime_warnings()` → the run response and the
Validate tool). It does not crash the run: a misspelled override degrading to
"the package default ran, and you were told" beats a run that cannot start.
Unknown *field keys* are applied as-is — the child schema is the authority on
what it reads, and a field the package ignores is harmless; node-id typos are
the dangerous silent case, so that is what warns.

**UI contract (inherited vs overridden).** The mount card's composition
annotation appends `· n overridden` when overrides exist, so a group visual
never claims the package default while something else runs. The inspector
edits the field as JSON with the same validation. Richer per-field
"inherited/overridden" chips ride on the (charted, separate) inspector
drill-in work.

## Rejected alternatives

- **Fork-on-configure** (copy the package per mount): kills the single source
  of truth the Team concept exists for.
- **Deep merge with list semantics**: ambiguity about list replacement vs
  append invites silent misconfiguration; shallow per-field replace is
  predictable and matches how the inspector edits fields.
- **Override by node *title***: titles are display text and not unique; ids
  are the stable contract (same reasoning as the router branch-id decision).
