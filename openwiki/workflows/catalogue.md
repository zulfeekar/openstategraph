---
title: Shipped workflows
description: Every package under workflows/, what it demonstrates, and how to run it.
type: page
---

# Shipped workflows

All live under [`workflows/`](../../workflows). Run any of them by opening the
slug in the editor and using Chat, or by POSTing its `workflow.json` document
to `/api/runs/stream` with `workflow_slug: <slug>`.

| Slug | Demonstrates |
| --- | --- |
| [`chinook-nl-to-sql`](../../workflows/chinook-nl-to-sql) | the original NL→SQL loop: agent + three Chinook tools + grader. Also ships `graph.py`/`agents.py` — hand-written code beside a compiled document |
| [`intent-routed-demo`](../../workflows/intent-routed-demo) | router → orchestrator → workers → `format_report`, with a per-intent grader and a `human.approval` gate |
| [`tabular-analytics`](../../workflows/tabular-analytics) | prebuilt tabular tools over a CSV dataset + `skills/join-rules.md` as procedural memory |
| [`open-api-explorer`](../../workflows/open-api-explorer) | supervisor labelling subtasks with **worker archetypes** (Weather / Countries / Knowledge / Quakes) over keyless public APIs |
| [`code-workshop`](../../workflows/code-workshop) | a `tier: "deep"` agent with jailed filesystem tools, a grader loop, a subgraph review, `human.approval`, and a dry-run PR |
| [`code-workshop-review`](../../workflows/code-workshop-review) | the review stage as its own package, mounted above as a `workflow.subgraph` node |
| [`research-team`](../../workflows/research-team) | the minimum-viable **Team** package: supervisor + worker + outcome grader |
| [`data-analyst-team`](../../workflows/data-analyst-team) | a Team plus prebuilt SQL tools and `skills/sql-conventions.md` |
| [`concierge`](../../workflows/concierge) | **hidden** gateway: routes every /chat message to a specialist workflow, with read-only platform + web tools on its own branch |
| [`workflow-architect`](../../workflows/workflow-architect) | **hidden**: composes a new workflow document from a description, grading each draft with `tool.validate-workflow` |

Each package's own `AGENTS.md` is the authoritative per-workflow note; the
table above is an index, not a replacement.

## Composition

`workflow.subgraph` and `team.workflow` are the same slug-as-data mechanism
compiled by the same backend path
([`NodeRuntime._subgraph`](../../backend/openstategraph/compile/node_runtime.py)). What
distinguishes a **Team** is the contract its card states — its expected
outcome, whose enforcing copy is the child's grader criteria
([`src/nodes/compose/TeamNode.ts`](../../src/nodes/compose/TeamNode.ts)).

Self-inclusion is refused at build time via the runtime's `_ancestry` chain,
not discovered by recursing forever at run time.

## The concierge gateway

[`workflows/concierge/workflow.json`](../../workflows/concierge/workflow.json)
is what `/chat`'s "Auto" option opens. It routes on five branches —
`videogames`, `music_store`, `live_data`, `build_workflow`, `general` — the
first three into subgraph workflows, `build_workflow` into the Workflow
Architect, and `general` onto its own agent armed with the read-only
`tool.platform-*` and `tool.web-*` families behind a no-fabrication grader.
Write-capable workflows (`code-workshop`) are deliberately **not** routed:
file-mutating flows stay explicit-selection only.
