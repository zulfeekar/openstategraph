---
title: The atomic design model
description: Atoms, molecules, organisms, templates and pages — the official vocabulary for how OpenStateGraph composes, with the real examples.
type: page
---

# The atomic design model

OpenStateGraph's composition philosophy, named (adopted 2026-08-08; the structure
predates the vocabulary):

| Level | In OpenStateGraph | Real examples |
| --- | --- | --- |
| **Atoms** | One middleware, one tool, one reducer, one skill file | `SummarizationMiddleware`, `save_memory`, `tool.sql-get-schema`, `skills/join-rules.md` |
| **Molecules** | A tier's curated preset — atoms in a fixed, meaningful order | the ReAct agent stack, the deep-agent 12-slot preset, the Grader (+rubric), the Router |
| **Organisms** | Node patterns wired on the canvas | the Team node, supervisor→workers→grader, the evaluator-optimizer loop |
| **Templates** | Workflow packages | `workflows/chinook-assistant/`, and the three that ship inside the wheel (`minimal`, `routed-qa`, `team` — `openstategraph new --list-templates`) |
| **Pages** | The running surfaces | `/chat`, the concierge gateway, the editor |

Two rules make it hold:

- **Inherit the capability, never the composition** (`CLAUDE.md`): every
  agent inherits the *slot table* (the ability to compose any atoms); each
  molecule ships a curated preset; nothing welds an atom in place.
- **Extend by file, not by code**: a workflow adds atoms by dropping files —
  `tools/`, `functions/`, `middlewares/<slot>.py`, `skills/*.md` — discovered
  by convention.

Default policy per atom kind (middleware especially): correctness guards
locked on · cost trades opt-in with the price named · semantics-changers off
until deliberately chosen.
