# Concierge (gateway) — HIDDEN

The predefined workflow that sits on top of the customer chat (ticket 67).
`hidden: true` keeps it out of every workflow list; /chat's "Auto" option and
the editor (by slug `concierge`) can still open it.

- **Routes** every message on three branches, `general` being the fallback:
  - `music_store` → `workflow.subgraph` onto `chinook-nl-to-sql`
  - `build_workflow` → `workflow.subgraph` onto `workflow-architect` (hidden),
    and *only* for explicit "build me a …" requests — questions about how the
    platform works are `general`
  - `general` → its own agent behind a no-fabrication/no-disclosure grader
- **Read-only by construction.** The general agent's eight tools are all
  read-only: platform introspection (`platform-list-workflows`,
  `platform-describe-workflow`, `platform-ls`, `platform-read-file`,
  `platform-grep`), `knowledge-lookup`, and `web-search` / `web-fetch` for
  anything current. Nothing writes, and the concierge binds no tool of its
  own to the routed branches — child workflows resolve their own tools from
  their own packages (`registry_loader`).
