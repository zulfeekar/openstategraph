Type: grilling
Status: resolved (2026-08-07) — decisions recorded, implementation queued
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

## Resolution (auto-mode decisions, one-liners)

- Both surfaces, Mermaid first: per-workflow "Graph" tab rendering `compiled.get_graph(xray=True).draw_mermaid()` from a generalized `GET /api/workflows/{slug}/graph` (de-hardcodes the chinook-only endpoint) — cheapest honest view of what actually compiles.
- `graph.py` generator second, per ticket 15's standing design: consumes `CompiledPlan`, property-tested by Mermaid equality with the interpreter, exported read-only ("regenerated — hand-written code lives in tools/functions/").
- Reusability = package contract (ticket 49) + a "duplicate as template" store operation; no separate template registry invented.
- Implementation: queued behind the in-flight sessions (compiler/API files are contended); folded into ticket 49's implementation pass.

## Implementation (2026-08-08)

Mermaid surface built: generic `GET /api/workflows/{slug}/graph` compiles the real document (xray=True — subgraphs expanded; retired the chinook-hardcoded endpoint), `WorkflowFileClient.compiledGraph`, TopBar 'View compiled graph' overlay rendering locally via lazy-loaded mermaid (strict security, Copy-Mermaid button — the text is the portable artifact). Live-verified on the concierge: 11 nodes, labelled branches, revise loop visible. This is also ticket 68's cheap half. `graph.py` generator remains the recorded follow-up.
