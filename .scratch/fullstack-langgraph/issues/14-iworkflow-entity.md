Type: grilling
Status: open
Blocked by: 07, 10, 15

## Question

Make `IWorkflow` a first-class entity, and decide what a saved workflow *is* on disk.

The user's requirement: a workflow the user authors becomes real files under `workflows/<slug>/`. An unsaved or first-time workflow must prompt for a name; it must be renameable afterwards.

Decisions to reach:
- Where `IWorkflow` sits in the entity ladder (`IEntity → BaseWorkflow → ...`) and what it owns: identity, slug, name, version, the node/edge set, its input/output schema (so another workflow can consume it — see 05).
- **Slug versus name.** The directory is a slug; the display name is mutable. Renaming: does the directory move (breaking references from other workflows and any git history) or does the slug stay frozen as the identity? Argue it out — this is the decision most likely to hurt later.
- The first-save prompt: what is the minimum required to save, and what happens to an unsaved workflow on reload. Related: the undo stack is currently in-memory only.
- Referential integrity: workflow B references workflow A (subgraph). What happens when A is renamed, or deleted while referenced?
- Whether `IWorkflow` is the same object the runtime compiles, or an authoring projection of it.

Consult `/domain-modeling`.

---

## Layout as the user described it

First save prompts for a name, then creates:

```
workflows/text-to-sql/
  workflow.json     structure — canvas owns it, source of truth
  graph.py          generated (see below — possibly should not exist yet)
  tools/            user-owned, workflow-scoped
  functions/        user-owned, workflow-scoped
  tests/            user-owned, workflow-scoped
```

Everything under `tools/`, `functions/` and `tests/` is scoped to this workflow and usable by any node inside it. Discovery of those capabilities is ticket 18 — this ticket owns only the *layout and identity*.

Points to settle here specifically:

- **`graph.py` should probably not be created empty.** An agentic coder opening the directory sees `graph.py`, assumes it is the entry point, reads it and finds nothing. Either generate it on first save or do not create it until export (ticket 15 decides interpret-vs-generate). Recommendation: do not create an empty file that looks load-bearing.
- **`AGENTS.md` per workflow**, generated — what this workflow does, where things live, how to run its tests. This is the cheapest single thing that makes the layout legible to a coding agent.
- **Determinism is a prerequisite**, not polish — see ticket 19. A `workflow.json` whose node order varies destroys `git diff` and makes the directory unreviewable.
- Whether `workflows/` sits at the repo root or inside the Python package (interacts with ticket 12).
