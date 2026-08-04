Type: grilling
Status: open
Blocked by: 07, 02

## Question

Decide the repo layout for a two-language codebase.

Decisions:
- Monorepo shape: where the Python package sits relative to `src/`, and whether a workspace tool is warranted (pnpm workspaces / uv / just a Makefile).
- Where generated TS types land, and whether they are committed.
- Dev workflow: two processes (Vite + the Python runtime) — one command or two? Ports, proxying.
- Dependency and lockfile management per language; how CI runs both.
- Whether `core/` stays pure TS or whether some of it becomes generated from Pydantic (the honest answer may be that parts of `core/model/contracts` are *replaced* by generated types).
