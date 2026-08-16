# `workflow.subgraph` keeps its name

**Decided 2026-08-16** — consistency-sweep ticket 10. Status: settled.

## The question

The settled lexicon gives the user *mount*, *instance* and *workflow node*, and
reserves nothing called a subgraph. CLAUDE.md's portability rule 4 is explicit:
*do not leak LangGraph type names into `workflow.json` or into `core/`*.

The node type id in every shipped document is `workflow.subgraph`:

```json
{ "id": "mount-mid", "type": "workflow.subgraph", "data": { "workflow": "nested-mounts-mid" } }
```

So the type id breaks a stated non-negotiable, on the file the docs tell a user
to read, version and hand-edit. The ticket asked for a decision either way, and
this is it.

## The decision

**The type id stays `workflow.subgraph`. Every user-facing sentence stops
saying it.**

Four surfaces were fixed in the same commit — the self-mount refusal, the
drill-in breadcrumb, the compiled-graph preview's hint, and a run timeline's
lane tooltip — and `src/view/userFacingLexicon.test.ts` now fails if the word
reappears inside a string a person reads.

## Why not rename it

Three reasons, in the order they matter.

**It is a migration, not a rename.** The literal appears in 119 places across
`src/` and `backend/`, in `compile/port_specs.json`, in the v2→v3 migration
target (`schema.py::_MOUNT_TYPE`), and — the part that decides it — inside the
`workflow.json` of four shipped examples and of every document any adopter has
already saved. Changing it means a schema version, a migration step, and a
window in which a hand-edited document written against the docs stops loading.

**The cost lands on the user we are protecting.** The argument for renaming is
that `workflow.json` is the vendor-neutral layer a user reads and edits. That
same user is the one whose saved documents a rename breaks. Rule 4 exists so a
second runtime stays *possible*; a type id is one string in a migration table
on that day, which is the cheapest thing in that project rather than the
expensive one.

**The word was never load-bearing anyway.** The leak that actually cost
anything was in prose — the refusal sentence said "subgraph" twice, and the
preview promised "subgraphs expanded" for a construct this compiler does not
emit (production-ready 37: a mount is a closure over the child's `invoke()`,
verified byte-identical under `xray`). Fixing the sentences fixes what a person
meets. The type id is read by the compiler and by `git diff`.

## What would reopen this

A schema version bump for an unrelated reason. `workflow.mount` should ride
along with that migration rather than justify one of its own — at which point
this file becomes the note saying the rename was always wanted and only ever
too expensive alone.

## What this does not license

`workflow.subgraph` is exempt as an **identifier**. The wire enum
`kind: 'subgraph'` on a `spawn` frame and the identifiers built from it are
exempt for the same reason. Nothing else is: a new string a user reads says
*mount*, and the lexicon guard is what makes that a red test rather than a
paragraph.
