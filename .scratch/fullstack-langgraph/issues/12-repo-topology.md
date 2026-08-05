Type: grilling
Status: resolved — as-built, plus the one real gap it surfaced (no Python dependency manifest existed at all)
Blocked by: 07, 02

## Question

Decide the repo layout for a two-language codebase.

Decisions:
- Monorepo shape: where the Python package sits relative to `src/`, and whether a workspace tool is warranted (pnpm workspaces / uv / just a Makefile).
- Where generated TS types land, and whether they are committed.
- Dev workflow: two processes (Vite + the Python runtime) — one command or two? Ports, proxying.
- Dependency and lockfile management per language; how CI runs both.
- Whether `core/` stays pure TS or whether some of it becomes generated from Pydantic (the honest answer may be that parts of `core/model/contracts` are *replaced* by generated types).

## Resolved (2026-08-05) — recording what's already true, fixing the one real gap

Most of this ticket's decisions were already made by what got built over
prior sessions, just never written down here. Recorded now rather than
re-litigated:

- **Monorepo shape**: `backend/` (Python package) and `src/` (TypeScript) at
  the repo root, siblings. `workflows/<slug>/` also at the repo root (ticket
  14), not inside `backend/` — authored workflow content and the Python
  *package* that runs it are different things with different owners.
- **No workspace tool** (no pnpm workspaces, no `uv` workspace) — there is
  exactly one Python package and one npm package; a workspace tool solves a
  multi-package problem this repo doesn't have.
- **Generated TS types**: not committed, because they don't exist yet —
  ticket 02 picked the toolchain (`json-schema-to-typescript`) but no
  generation script has been wired into a build step. Still open work,
  tracked there, not duplicated here.
- **Dev workflow**: two processes, two terminals, documented in the README.
  Not unified into one command — `Vite` and `uvicorn` share nothing a
  wrapper script would meaningfully own, and ticket 07 already settled that
  the browser must reach the backend over HTTP, not a shared process.
- **`core/` stays pure TypeScript.** Nothing in it is generated from Pydantic
  today, and ticket 08's own finding (`INodeExecutor` "survives in Python and
  dies in TypeScript") already flags `core/execution`/`core/providers` for
  eventual deletion rather than generation.

**The one real gap this ticket surfaced, now fixed**: there was **no Python
dependency manifest anywhere in the repo** — no `requirements.txt`, no
`pyproject.toml` — meaning a fresh clone had no way to know what to
`pip install`. Added `backend/pyproject.toml`, pinned to the actual installed
versions this session verified against (`langgraph>=1.0`, `langchain>=1.0`,
`deepagents>=0.7`, `fastapi`, `uvicorn`, `pydantic`, plus the three provider
packages `resolve_model` can select between). Test configuration stays in the
repo-root `pytest.ini` — not duplicated into `pyproject.toml`'s own
`[tool.pytest.ini_options]`, which would be exactly the kind of
hand-mirroring CLAUDE.md's DRY section forbids.
