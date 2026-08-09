# Concierge (gateway) — HIDDEN

The predefined workflow that sits on top of the customer chat (ticket 67).
`hidden: true` keeps it out of every workflow list; /chat's "Auto" option and
the editor (by slug `concierge`) can still open it.

- **Routes** every message: music-store questions → `chinook-nl-to-sql`,
  explicit build requests → `workflow-architect` (hidden), everything else →
  its own general agent behind a no-fabrication/no-disclosure grader.
- **Read-only by construction**: the concierge binds no tools of its own
  beyond the read-only platform-introspection family on the general agent;
  child workflows resolve their own tools from their own packages
  (`registry_loader`).
