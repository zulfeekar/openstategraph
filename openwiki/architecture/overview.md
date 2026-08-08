---
title: Architecture overview
description: The two halves of OpenStateGraph, the artefact they meet at, and the module map.
type: page
---

# Architecture overview

Two halves that meet at exactly one artefact: `workflow.json`.

```
src/           TypeScript editor  ──writes──▶  workflows/<slug>/workflow.json
                                                        │
backend/openstategraph  Python runtime    ◀──reads────────────── ┘
                                   compiles → LangGraph StateGraph
```

The seam is **one-directional**: no runtime object is ever read back into the
editor's model ([`CLAUDE.md` → Portability guardrails](../../CLAUDE.md)).

## Frontend (`src/`)

| Layer | Directory | Rule |
| --- | --- | --- |
| Design system | [`src/design/`](../../src/design) | tokens/primitives, no app logic |
| Model + engine | [`src/core/`](../../src/core) | plain TypeScript — no React, no JointJS |
| Controller | [`src/controller/`](../../src/controller) | commands, selection, clipboard |
| Canvas view | [`src/canvas/`](../../src/canvas) | owns JointJS; installable `IPaperFeature`s |
| React view | [`src/view/`](../../src/view) | shell, panels, node cards |
| Node modules | [`src/nodes/`](../../src/nodes) | one file = model + fields + ports + executor |
| Composition root | [`src/app/Workbench.ts`](../../src/app/Workbench.ts) | wiring, demo seed |

Every extension point is a `Registry<T>`
([`src/core/kernel/Registry.ts`](../../src/core/kernel/Registry.ts)); the only
file that knows the whole node catalogue is
[`src/nodes/index.ts`](../../src/nodes/index.ts).

## Backend (`backend/openstategraph/`)

| Module | Responsibility |
| --- | --- |
| [`abc/`](../../backend/openstategraph/abc) | the entity ladders — agent, router, grader, orchestrator, tool, prompt, middleware slot table |
| [`compile/workflow_compiler.py`](../../backend/openstategraph/compile/workflow_compiler.py) | document → `CompiledPlan` → `StateGraph` |
| [`compile/node_runtime.py`](../../backend/openstategraph/compile/node_runtime.py) | `RunState` + a builder per node type |
| [`api/main.py`](../../backend/openstategraph/api/main.py) | FastAPI app: runs, streaming, resume, capabilities, `/chat` |
| [`api/workflow_store.py`](../../backend/openstategraph/api/workflow_store.py) | file-backed CRUD + `validate_package` |
| [`api/capability_discovery.py`](../../backend/openstategraph/api/capability_discovery.py) | tools / functions / skills / middlewares discovered per package |
| [`memory.py`](../../backend/openstategraph/memory.py) | Store, checkpointers, memory tools |
| `prebuilt_*.py` | shipped tool families (see below) |

### Prebuilt tool families

| Module | Node types | Purpose |
| --- | --- | --- |
| [`prebuilt_sql.py`](../../backend/openstategraph/prebuilt_sql.py) | `tool.sql-list-tables`, `tool.sql-get-schema`, `tool.sql-query` | read-only SQLite (`mode=ro`, path jailed to `workflows/`) |
| [`prebuilt_web.py`](../../backend/openstategraph/prebuilt_web.py) | `tool.web-search`, `tool.web-fetch` | keyless search + SSRF-guarded fetch |
| [`prebuilt_platform.py`](../../backend/openstategraph/prebuilt_platform.py) | `tool.platform-list-workflows`, `-describe-workflow`, `-ls`, `-read-file`, `-grep` | read-only platform introspection for the concierge |
| [`prebuilt_architect.py`](../../backend/openstategraph/prebuilt_architect.py) | `tool.validate-workflow` | the compiler exposed as a tool, so an agent can compose-validate-revise |

## HTTP surface

Defined in [`api/main.py`](../../backend/openstategraph/api/main.py):

`GET /api/health` · `GET /api/node-contracts` · `GET /api/workflows` ·
`GET|PUT|DELETE /api/workflows/{slug}`
· `GET /api/workflows/{slug}/capabilities` · `GET /api/workflows/{slug}/graph`
(compiled Mermaid, `xray=True`) · `POST /api/runs` · `POST /api/runs/stream`
(SSE) · `POST /api/runs/resume` · `GET /chat`.

Graph previews are **Mermaid text only** — `draw_mermaid_png()` would post the
user's graph to a third-party API.
