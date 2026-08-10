# Chinook Metrics Team (a Team) — HIDDEN

`hidden: true` keeps this shared library package out of the workflow list —
it is infrastructure to mount, not an example to open.

An OpenStateGraph **team package** — supervisor + default worker + a grader whose
criteria are the team's outcome contract. Scaffolded from the shape
`scripts/new_team.py` produces.

The worker explores the shared Chinook music-store database
(`chinook-nl-to-sql/data/Chinook_Sqlite.sqlite`) through the generic SQL
Explorer tools — the one sample database every example evaluates against.

The package is deliberately just `workflow.json` and this file: its three
`tool.sql-*` nodes are the **built-in** SQL Explorer family, so there is no
package-local `tools/` to carry. `Store Analytics` mounts it on the
`database_deep_dive` branch.

- **Mount it**: add a **Team** node in any workflow with slug `chinook-metrics-team`.
- **Outcome**: edit `grader1`'s criteria — that is what "done" means here.
- **Members**: add workers, each a new archetype named by its title, and wire
  the tool bus into each one.
- **Growing it**: `tools/`, `middlewares/`, `functions/`, `skills/` and
  `knowledge/` are discovered by convention if you add them — none exists yet.
