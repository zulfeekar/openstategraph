# Concierge (gateway) — HIDDEN

The predefined workflow that sits on top of the customer chat (ticket 67).
`hidden: true` keeps it out of every workflow list; /chat's "Auto" option and
the editor (by slug `concierge`) can still open it.

- **Routes** every message on three branches, `general` being the fallback:
  - `music_store` → `workflow.subgraph` onto `chinook-assistant`

    **Changed by ticket 10, and the old reasoning no longer holds.** This used
    to mount `chinook-nl-to-sql`, the hidden analyst, *deliberately* — the
    concierge had already classified the message, so routing into a second
    router would have paid for the same decision twice. That analyst no longer
    exists as a package: the one Chinook example is a single document with its
    router inline. So the double classification is now real, and accepted: it
    is one cheap model call, and the alternative is either keeping a second
    Chinook package alive purely so the gateway can skip a hop, or letting the
    gateway reach *inside* another document — which the compile seam does not
    allow and should not.

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
