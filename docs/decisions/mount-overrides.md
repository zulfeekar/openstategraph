# Per-mount overrides for mounted organisms

**Status: accepted, implemented.**

> **Node types, updated.** This decision was written while there were two mount
> types, `team.workflow` and `workflow.subgraph`, and its original title said
> "(Team / Subgraph)". Schema v3 collapsed the two into `workflow.subgraph`
> (production-ready ticket 16) — they compiled through one builder with no
> branch, so nothing here changes except the count of type ids. `MIGRATIONS[2]`
> in `backend/openstategraph/schema.py` carries each mount's `overrides` across
> untouched, which is the only thing this document depends on.

## Problem

A mount (`workflow.subgraph`) node references one shared package. Two mounts of one analyst package share one definition — which
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
edits the field as JSON with the same validation.

> **The per-field chips shipped** (noted 2026-08-16). This deferred them to
> "the (charted, separate) inspector drill-in work"; `MountContext` exposes
> `isOverridden` and `inheritedValue`, and `FieldRenderer` marks an overridden
> field and offers the revert. `gap-register.md` UX-05 deferred the same work
> and was closed on 2026-08-13 — this document was the half that did not
> follow. It is the shape this repository keeps finding: a doc defers
> something to a prerequisite, the prerequisite ships, and nobody returns to
> the deferral.

> **And the value now has somewhere to live** (noted 2026-08-16). The chips
> above shipped before persistence did, which made them a claim rather than a
> report: `SetMountOverrideCommand` wrote `data.overrides` on the host
> document `MountContext` retains, the field badged `overridden`, and nothing
> wrote that document — autosave is switched off for an instance, correctly,
> because what is on screen is derived. So `Back` re-fetched the host from
> disk and the override was gone, with `"overrides": ""` still on the file and
> no warning that anything had been dropped (organisms-first-class ticket 44).
>
> `diskAutosave.writeOpenMountHostToDisk` is the missing sink: the **host**,
> never the package, on the same debounce as every other edit, with a baseline
> recorded by both paths that can enter an instance and a compare-and-set the
> explicit Save already had. The package half was always correct and stays
> untested-by-change: two mounts of one package hold different overrides and
> the package's bytes do not move.

> **Back lost the override a second time, by a different route** (noted
> 2026-08-21, `production-ready` 101). With the sink above in place the file
> was correct — measured with md5, `front-desk/workflow.json` carried both
> mounts' overrides and `music-analyst/workflow.json` never moved — and
> pressing **← Back** still emptied `m2`'s override, on the canvas and then on
> disk.
>
> Not the same defect wearing a new hat. `Back` re-reads the host from disk and
> reads it correctly; what overwrote it was this browser's **draft** of the
> parent, written by the act of opening the parent *before* the drill-in and
> restored over the fresh file by `restoreDraftFor`. `writeOpenWorkflowToDisk`
> writes documents whole, so the absence in memory became a deletion in the
> file about ten seconds later.
>
> A draft means *this browser's unsaved edits to a package*, and it stops
> meaning that the moment this same browser writes that package from somewhere
> else — which is exactly what a mount save does, since the override lives on
> the parent. `workflowDrafts.supersedeDraftAfterHostWrite` drops it.
> Deliberately not a timestamp comparison inside `restoreDraftFor` — that
> function compares canonical bytes and not clocks on purpose, and the clocks
> here belong to two machines.
>
> **One seam, not two conventions** (`production-ready` 102). Until that ticket
> this passage read *"both host writers call it"*, which was true and was the
> whole of the guarantee: a third writer of a host package would have compiled,
> passed review and reintroduced the deletion — measured, by adding one and
> watching all 2495 tests stay green. Every host write now passes through
> `app/hostPackageWrite.writeHostPackage`, which owns the whole protocol: the
> compare-and-set on the parent's `saved_at`, the write, the supersede, and the
> adoption of this tab's own write as the next baseline. The two writers keep
> only what is theirs — autosave's change detection, and the button's sentence.
> `src/app/aThirdHostWriterCannotForget.test.ts` reads `src/` and goes red when
> a host document reaches a `save` call anywhere else, because no signature can
> stop code calling the client directly.

## Rejected alternatives

- **Fork-on-configure** (copy the package per mount): kills the single source
  of truth a mounted package exists for.
- **Deep merge with list semantics**: ambiguity about list replacement vs
  append invites silent misconfiguration; shallow per-field replace is
  predictable and matches how the inspector edits fields.
- **Override by node *title***: titles are display text and not unique; ids
  are the stable contract (same reasoning as the router branch-id decision).
