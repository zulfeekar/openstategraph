# Contributing to OpenStateGraph

Two stacks, one repo: a TypeScript editor (`src/`) and a Python LangGraph
runtime (`backend/`). Architecture rules live in `CLAUDE.md` — read the
"Non-negotiables" section before designing anything.

## Setup

```bash
npm install && npm run dev                 # editor → http://localhost:5273
pip install -e backend[dev]                # runtime deps
PYTHONPATH=backend:workflows/chinook-nl-to-sql \
  uvicorn openstategraph.api.main:app --port 8000 --app-dir backend
```

No API keys required: the editor runs on a deterministic Mock provider, the
backend defaults to Ollama cloud.

## Tests — the gate for every PR

```bash
npm run verify          # tsc + vitest
python -m pytest -q     # live-API tests are opt-in: pytest -m live
```

TDD is the house style: tests land with (ideally before) the change.

**Docs land with the code.** CI's `docs-freshness` job fails a PR that touches
`src/` or `backend/` without touching `README.md`, `docs/` or `openwiki/`. If
the change genuinely needs no documentation, put `docs: not-needed` in any
commit message in the PR and the job passes.

## Adding things

Everything is a registry; extending never edits `core/`. See README's
"Extension points" table. A new workflow is a package under
`workflows/<slug>/` — `workflow.json` + `AGENTS.md` required; `tools/`,
`functions/`, `middlewares/`, `tests/`, `data/` discovered by convention.
