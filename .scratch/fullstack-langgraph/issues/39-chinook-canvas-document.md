Type: task
Status: open
Blocked by: 33

## Question

`chinook-nl-to-sql` — the flagship — has `agents.py`/`graph.py`/`tools/` and
**no `workflow.json`**, so it is invisible to `WorkflowStore.list()` and
cannot be opened on the canvas. Two API endpoints are hardcoded to its slug.

Author its canvas document: router → ReAct agent + the three SQL tools →
grader with the revise loop, matching what `graph.py` hand-builds; verify
the compiled graph and the hand-built one produce the same Mermaid; keep
`graph.py` as the "compiler output is just Python" demonstration or retire
it explicitly. De-hardcode `/api/workflows/chinook-nl-to-sql/*` endpoints
(moves with ticket 49).
