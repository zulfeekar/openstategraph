# Workflow Architect — HIDDEN

Turns a chat description into a complete, compile-validated workflow document
(ticket 69). Ephemeral-first: the Architect only *composes and validates* —
the document rides back in the answer, and saving is a human click in /chat.

- Loop-on-evidence: `validate_workflow` (the compiler as a tool) grades every
  draft; the grader refuses answers without a validated ```json fence.
- Grammar lives in `skills/document-grammar.md` — procedural memory, editable
  without touching code.
- Routed from the concierge's `build_workflow` branch ("build me a team
  that..."). Two ambient skills shape it: `document-grammar.md` (the grammar
  above) and `interview.md`, which makes it refuse to compose an
  underspecified request and ask **one** clarifying question instead — the
  reason it sometimes answers "Before I build:" with no JSON fence.
