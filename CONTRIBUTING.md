# Contributing to OpenStateGraph

Two stacks, one repo: a TypeScript editor (`src/`) and a Python LangGraph
runtime (`backend/`). Architecture rules live in `CLAUDE.md` — read the
"Non-negotiables" section before designing anything.

## Setup

```bash
npm install && npm run dev                 # editor → http://localhost:5273
pip install -e "backend[all,dev]"          # runtime deps — see below
PYTHONPATH=backend:workflows/chinook-nl-to-sql \
  uvicorn openstategraph.api.main:app --port 8000 --app-dir backend
```

No API keys required: the editor runs on a deterministic Mock provider, the
backend defaults to Ollama cloud.

`[all]` is a *contributor's* install. A consumer installs the lean core —
`langgraph`, `langchain`, `langchain-core`, `pydantic` — plus whichever extras
their workflow actually uses (`[anthropic]`, `[openai]`, `[ollama]`, `[deep]`,
`[sqlite]`, `[server]`, `[mcp]`). Adding a dependency to the core table
without the accompanying case for it fails
`backend/tests/test_distribution_metadata.py`, which is the point.

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

## Generated artifacts — regenerate, never hand-edit

`backend/openstategraph/compile/port_specs.json` is **generated** from the
TypeScript node catalogue and committed. Change a node type, a port, a port's
cardinality or a port type, and you must run:

```bash
npm run generate:ports
```

The TypeScript side is authoritative here (the opposite direction to
Pydantic → TypeScript, which is the rule for *runtime* types): `src/nodes/**`
is where a node type is declared and where `ports` is a function of node data;
Python only reads the shape. The artifact is committed because an installed
wheel has no Node.js — a consumer running `load_workflow` cannot regenerate it.

Two gates catch a stale copy: `src/nodes/portSpecs.test.ts` compares the built
catalogue to the committed bytes inside `npm run verify`, and CI's
`generated-port-specs` job regenerates and diffs the working tree. Both name
the command in the failure. Do not edit the JSON by hand.

## Adding things

Everything is a registry; extending never edits `core/`. See README's
"Extension points" table. A new workflow is a package under
`workflows/<slug>/` — `workflow.json` + `AGENTS.md` required; `tools/`,
`functions/`, `middlewares/`, `tests/`, `data/` discovered by convention.
