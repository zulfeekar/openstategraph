# Workflow Architect — HIDDEN

Turns a chat description into a complete, compile-validated workflow document
(ticket 69). Ephemeral-first: the Architect only *composes and validates* —
the document rides back in the answer, and saving is a human click in /chat.

- Loop-on-evidence: `validate_workflow` (the compiler as a tool) grades every
  draft; the grader refuses answers without a validated ```json fence.
- Grammar lives in `skills/document-grammar.md` — procedural memory, editable
  without touching code.
- Routed from the concierge's `build` branch ("build me a team that...").
