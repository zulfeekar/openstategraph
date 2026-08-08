Type: grilling
Status: open
Blocked by:

## Question

"It is not clear what is behind the scenes of each workflow — what it
generates, how it works, for reusability." Make the compiled artefact
visible and reusable.

What exists: `compiled.get_graph(xray=True).draw_mermaid()` already returns
the real compiled topology (one hardcoded endpoint); ticket 15 decided
**interpret to execute, generate to read** — the read-only `graph.py`
generator was designed (CompiledPlan is its input; property: generated and
interpreted graphs produce identical Mermaid) but never built.

Decisions to grill:

- Is the "behind the scenes" view the Mermaid preview surfaced in the editor
  per workflow (cheap, already computable), the generated `graph.py` export
  (real code a developer can lift into their own project — the portability
  story), or both, and in which order?
- Where does it live in the UX — a tab on the workflow, an export button,
  part of the Team node's drill-in?
- What makes a workflow *reusable* by another developer: the package
  contract (ticket 49), the generated code, or a template/instantiate flow
  ("new workflow from this one")?
