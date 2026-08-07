Type: grilling
Status: open
Blocked by: 33, 35

## Question

Three workflows, three shapes (chinook: code, no document; intent-routed:
document, no code; tabular: both, no AGENTS.md). Nothing validates a
workflow directory; two endpoints hardcode a slug.

Define the contract: required (`workflow.json`, `AGENTS.md`) vs optional
(`tools/`, `functions/`, `tests/`, `data/`); a validator run by the store
on list/load with readable diagnostics; a `scaffold` command (backend CLI)
creating a conforming skeleton; migration of the three existing workflows;
de-hardcode the chinook endpoints behind `{slug}` routes.
