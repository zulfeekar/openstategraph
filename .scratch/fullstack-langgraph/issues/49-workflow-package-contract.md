Type: grilling
Status: resolved (2026-08-08) — contract decided; validator+scaffold queued
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

## Resolution

One-liners: a workflow package = `workflow.json` (envelope) + `AGENTS.md` required; `tools/ functions/ middlewares/ tests/ data/` optional, discovered by convention (per the user's prebuilt+file-extension model, ticket 37 note); validator = a `WorkflowStore.validate(slug)` returning findings (missing AGENTS.md = warning, unparseable workflow.json = error) surfaced through `GET /api/workflows`; scaffold = `scripts/new_workflow.py <slug>` copying a template package; chinook-hardcoded endpoints (`/graph`, `/ask`) generalize to `{slug}` — folded together with ticket 54's Mermaid tab implementation.
