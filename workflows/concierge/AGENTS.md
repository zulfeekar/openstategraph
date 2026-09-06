# Concierge (gateway) — HIDDEN

The predefined workflow that sits on top of the customer chat (ticket 67).
`hidden: true` keeps it out of the **chat** catalogue — `GET /api/workflows`
defaults to `surface=editor`, which returns hidden packages deliberately, each
flagged, so the editor can mark them rather than pretend they do not exist.
`?surface=chat` is the list this is hidden from. /chat's "Auto" option routes
here without listing it, and the editor opens it by slug.

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
- **The eight *wired* tools are read-only**: platform introspection
  (`platform-list-workflows`, `platform-describe-workflow`, `platform-ls`,
  `platform-read-file`, `platform-grep`), `knowledge-lookup`, and
  `web-search` / `web-fetch` for anything current. None of them writes.

  **But eight is the wired count, not the bound count.** Every `agent.llm`
  additionally gets the memory tools whenever a store exists — and one always
  does, because `build_store()` falls back to an in-process store rather than
  returning nothing. So the general agent runs with eleven tools, three of
  which (`save_memory`, `search_memory`, `forget_memory`) include a writer and
  a deleter. This file used to say "Nothing writes", which was flatly
  contradicted by `skills/app-memory.md` two directories away.
- **This package is the app spine.** `skills/app-memory.md` is an ambient skill
  — prompt context for every agent here — telling this workflow's agents when a
  finding belongs to `scope="app"`, the pool every workflow can read, and at
  greater length when it does not. The mechanism is permissive: *any* workflow
  may write app scope. What makes the concierge the spine is that file.
- The concierge binds no tool of its own to the routed branches — a child
  resolves tools, functions, skills and middleware from **its own** package,
  carried by `PackageAssets` (`compile/node_runtime.py`).
