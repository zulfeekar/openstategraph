# Concierge (gateway) — HIDDEN

The predefined workflow that sits on top of the customer chat (ticket 67).
`hidden: true` keeps it out of every workflow list; /chat's "Auto" option and
the editor (by slug `concierge`) can still open it.

- **Routes** every message: videogames → `tabular-analytics`, music →
  `chinook-nl-to-sql`, live data → `open-api-explorer`, everything else → its
  own tool-less general agent behind a no-fabrication/no-disclosure grader.
- **Read-only by construction**: the concierge binds no tools at all; child
  workflows resolve their own from their own packages (`registry_loader`).
  The code-workshop (write-capable) workflow is deliberately NOT routed —
  file-mutating flows stay explicit-selection only.
