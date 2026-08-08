# Contributing to Dyflow

Two stacks, one repo: a TypeScript editor (`src/`) and a Python LangGraph
runtime (`backend/`). Architecture rules live in `CLAUDE.md` — read the
"Non-negotiables" section before designing anything.

## Setup

```bash
npm install && npm run dev                 # editor → http://localhost:5273
pip install -e backend[dev]                # runtime deps
PYTHONPATH=backend:workflows/chinook-nl-to-sql \
  uvicorn dyflow.api.main:app --port 8000 --app-dir backend
```

No API keys required: the editor runs on a deterministic Mock provider, the
backend defaults to Ollama cloud.

## Tests — the gate for every PR

```bash
npm run verify          # tsc + vitest
python -m pytest -q     # live-API tests are opt-in: pytest -m live
```

TDD is the house style: tests land with (ideally before) the change.

## Adding things

Everything is a registry; extending never edits `core/`. See README's
"Extension points" table. A new workflow is a package under
`workflows/<slug>/` — `workflow.json` + `AGENTS.md` required; `tools/`,
`functions/`, `middlewares/`, `tests/`, `data/` discovered by convention.
