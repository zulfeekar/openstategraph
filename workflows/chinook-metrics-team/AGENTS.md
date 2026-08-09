# Chinook Metrics Team (a Team) — HIDDEN

`hidden: true` keeps this shared library package out of the workflow list —
it is infrastructure to mount, not an example to open.

An OpenStateGraph **team package** — supervisor + default worker + a grader whose
criteria are the team's outcome contract. Scaffolded from the shape
`scripts/new_team.py` produces.

The worker explores the shared Chinook music-store database
(`chinook-nl-to-sql/data/Chinook_Sqlite.sqlite`) through the generic SQL
Explorer tools — the one sample database every example evaluates against.

- **Mount it**: add a **Team** node in any workflow with slug `chinook-metrics-team`.
- **Outcome**: edit `grader1`'s criteria — that is what "done" means here.
- **Members**: add workers (each a new archetype by title) and bind tools from
  `tools/`; `middlewares/` and `functions/` are discovered by convention.
