---
title: Quickstart
type: page
description: What OpenStateGraph is, how to run both processes, and where to read next.
---

# OpenStateGraph — quickstart

OpenStateGraph is a **visual AI workflow builder plus a compiler**. A workflow is
authored on a canvas, stored as a vendor-neutral `workflow.json` file, and
compiled into a LangGraph `StateGraph` that runs in a Python backend.

Two processes, two languages:

| Process | Command | Port |
| --- | --- | --- |
| Editor (Vite + React + JointJS) | `npm run dev` | 5273 |
| Runtime (FastAPI + LangGraph) | `uvicorn openstategraph.api.main:app --port 8000 --app-dir backend` | 8000 |
| Both, supervised | [`scripts/dev.sh`](../scripts/dev.sh) (`stop`, plus [`scripts/status.sh`](../scripts/status.sh)) | — |

Full run instructions, prerequisites and environment variables live in
[`README.md`](../README.md); the architectural rules live in
[`CLAUDE.md`](../CLAUDE.md). This wiki explains the parts a coding agent has
to touch.

## The 60-second model

1. The canvas is a **one-way projection** of `WorkflowModel`
   (`gesture → controller → command → model → event → adapter → paper`).
2. Saving writes `workflows/<slug>/workflow.json`
   ([`backend/openstategraph/api/workflow_store.py`](../backend/openstategraph/api/workflow_store.py)).
3. Running posts that document to `/api/runs` or `/api/runs/stream`; the
   backend compiles it fresh every time
   ([`workflow_compiler.py`](../backend/openstategraph/compile/workflow_compiler.py)
   + [`node_runtime.py`](../backend/openstategraph/compile/node_runtime.py)).
4. Everything a workflow can *do* beyond the built-ins — tools, functions,
   middleware slots, skills — is **discovered from its own package
   directory**, never registered centrally.

## Where to go next

- [Architecture overview](architecture/overview.md)
- [The compile seam](architecture/compile-seam.md)
- [Entity ladders and the middleware slot table](architecture/entity-ladders.md)
- [The workflow package contract](workflows/package-contract.md)
- [Shipped workflows](workflows/catalogue.md)
- [The memory system](architecture/memory.md)
- [How to extend OpenStateGraph](how-to/extending.md)
- [Testing](testing.md)

## Tests

```bash
npm run verify   # tsc -b + eslint + prettier --check + vitest
npx playwright test

pip install -e "backend[all,dev]"   # from the repo root; [dev] brings pytest
python3 -m pytest -q                # from the repo root — backend AND workflows
```

Run pytest from the repo root. Only there does pytest read the root
`pytest.ini` (`testpaths = workflows backend`); `cd backend && pytest` skips
the whole `workflows/` half of the suite, which CI is configured to run (no CI
run has ever happened here — see [Testing](testing.md)).
