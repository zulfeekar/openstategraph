---
title: Shipped workflows
description: Every package under workflows/, what it demonstrates, and how to run it.
type: page
---

# Shipped workflows

> **This page is generated, and the table below was corrected by hand.**
> OpenWiki last refreshed it while eight more packages existed; `workflows/`
> now holds exactly three. Rows naming deleted directories were removed rather
> than left to the next refresh, because a link to a directory that is not
> there is the failure this table exists to prevent. If a refresh reintroduces
> them, the tree is right and the page is wrong.

All live under [`workflows/`](../../workflows). Run any of them by opening the
slug in the editor and using Chat, or by POSTing its `workflow.json` document
to `/api/runs/stream` with `workflow_slug: <slug>`.

| Slug | Demonstrates |
| --- | --- |
| [`chinook-assistant`](../../workflows/chinook-assistant) | the one visible example: a five-intent router in front of a SQL analyst (three Chinook tools + a grader loop, rules from a wired skill file), a tool-less front desk, and a web researcher. Also ships `graph.py`/`agents.py` — hand-written code beside a compiled document |
| [`concierge`](../../workflows/concierge) | **hidden** gateway: routes every /chat message to a specialist workflow, with read-only platform + web tools on its own branch |
| [`workflow-architect`](../../workflows/workflow-architect) | **hidden**: composes a new workflow document from a description, grading each draft with `tool.validate-workflow` |

Each package's own `AGENTS.md` is the authoritative per-workflow note; the
table above is an index, not a replacement.

## Composition

`workflow.subgraph` and `team.workflow` are the same slug-as-data mechanism
compiled by the same backend path
([`NodeRuntime._subgraph`](../../backend/openstategraph/compile/node_runtime.py)). What
distinguishes a **Team** is the contract its card states, and only that: an
expected outcome, plus a "revises until it passes" badge the editor awards by
checking the mounted document for a grader wired back to its agent.

**The expected outcome never reaches the compiler.** It is a field on the card
([`src/nodes/compose/TeamNode.ts`](../../src/nodes/compose/TeamNode.ts)) that
`_subgraph` does not read; the enforcement is the child's own grader criteria,
and nothing checks that the two agree. Read it as documentation of intent.

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
