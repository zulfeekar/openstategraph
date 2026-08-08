# Data Analyst Team (a Team)

A Dyflow **team package** — supervisor + default worker + a grader whose
criteria are the team's outcome contract. Scaffolded by `scripts/new_team.py`.

- **Mount it**: add a **Team** node in any workflow with slug `data-analyst-team`.
- **Outcome**: edit `grader1`'s criteria — that is what "done" means here.
- **Members**: add workers (each a new archetype by title) and bind tools from
  `tools/`; `middlewares/` and `functions/` are discovered by convention.
