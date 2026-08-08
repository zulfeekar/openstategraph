# Intent-routed (router + orchestrator + per-intent grader)

An OpenStateGraph workflow. `workflow.json` in this directory is the source of truth for its nodes and edges — edit it through the editor, not by hand, unless you know the canonical serialization rules (ticket 19: sorted nodes, content-addressed edges, no written edge ids).

- **Run it**: `POST /api/runs` or `/api/runs/stream` with this directory's `workflow.json` as the `workflow` field, or open `intent-routed-demo` in the editor and use Chat.
- **Tools / functions** this workflow's nodes can bind to live in `tools/` and `functions/` alongside this file, once added.
- **Tests** for any hand-written tool/function code belong in `tests/`.
