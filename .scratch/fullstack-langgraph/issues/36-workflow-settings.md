Type: task
Status: open

## Question

`workflows/tabular-analytics/workflow.json` carries
`document.settings.model`, which backend model resolution wants (node →
workflow → default), but `SerializedWorkflow` has no `settings` key and
`WorkflowModel.toJSON()` emits `{version, name, nodes, edges}` — the editor
destroys the setting on save.

- Add `settings` to `SerializedWorkflow` + `WorkflowModel` with a schema
  migration; round-trip test on the real file.
- Contents: workflow-level model, recursion limit, checkpointer choice
  (ticket 47), flow direction override (ticket 45). Each optional; absent
  means inherit.
- Inspector surface: a workflow-level (no selection) inspector panel.
- Backend reads it uniformly across /api/runs, /stream, /resume — the WIP
  had three slightly different spellings.
