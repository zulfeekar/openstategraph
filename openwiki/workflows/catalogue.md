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

`workflow.subgraph` is the one mount type: a slug as data, compiled by
[`NodeRuntime._subgraph`](../../backend/openstategraph/compile/node_runtime.py).

**`team.workflow` was a second type until schema v3, and this page used to
describe what distinguished a Team.** Nothing did that was a property of the
node: both ids dispatched to `_subgraph` with no branch and identical ports,
the `outcome` field never reached the compiler, and the "loops until its grader
passes" note is earned by the *mounted child document*. Production-ready
ticket 16 collapsed the two; `MIGRATIONS[2]` in
[`schema.py`](../../backend/openstategraph/schema.py) rewrites the old id,
keeping node id, slug, `overrides` and the authored `outcome` text.
`src/nodes/compose/TeamNode.ts` is gone —
[`SubgraphNode.ts`](../../src/nodes/compose/SubgraphNode.ts) is the only mount
definition. A **team** is now a package *shape* (supervisor + workers + a
grader closing a revision loop), scaffolded by `--template team` and mounted
like any other workflow.

**The expected outcome still never reaches the compiler.** `workflow.subgraph`
gained the field, labelled *Expected outcome (documentation)*, so the migration
would not destroy prose a person wrote. Enforcement is the child's own grader
criteria. Where a mount writes an outcome its child cannot enforce, the card
says so ("no grader — nothing checks the outcome", or "its grader never revises
— nothing sends a weak answer back") and the run emits a `runtime_warnings`
entry naming the node and the slug. Loud, never fatal.

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
