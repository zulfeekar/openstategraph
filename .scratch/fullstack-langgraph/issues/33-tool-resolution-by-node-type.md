Type: task
Status: resolved (2026-08-07) — f5f7076
Blocked by: 30

## Question

Tool implementations resolve through a dict keyed by canvas node type, but
that dict is hand-assembled (`chinook_tool_registry()`) and `/api/runs`
hardcodes it — the tabular workflow's tools never resolve. The reverted WIP
attempt keyed the registry by Python class name (`tool.querydatatool`), which
can never match a canvas type (`tool.tabular-query`), and imported the
hyphenated slug as a module name, which can never import.

Build the real mechanism:

- `BaseTool.manifest()` gains `node_type` (the canvas type id) so the tool
  itself declares its wiring identity — single source of truth, from which
  the TS node definition is eventually generated (ticket 02's direction).
- Discovery (`discover_tools`) loads each workflow's `tools/` under a
  synthetic module name via `spec_from_file_location` (as
  `workflows/tabular-analytics/tests` now does) and returns *instances*;
  the API builds the registry from `manifest()["node_type"]`.
- A `configure(data)` hook on `BaseTool` (no-op default) delivers the bound
  node's own config — replaces the `tool.chinook-execute-sql` row-cap
  special case in `_bound_tool`, and makes `maxRows`/`fileName`/`nRows`
  on the tabular nodes real.
- `/api/runs`, `/api/runs/stream`, `/api/runs/resume` all resolve the same
  way (the WIP left resume on the chinook registry — divergent tool sets
  between a run and its resume). `workflow_slug` returns to the request
  contract on ALL THREE models including ResumeRequest (the extra="forbid"
  422 lesson), with tests at exactly that seam.
- Failure is loud: an unresolvable tool stays in `unresolved_tools` warnings;
  discovery ImportErrors surface in the capabilities response, not a log.

## Resolution

`BaseTool.node_type` + `configure(data)`; `discover_tool_registry` keys by node_type; `build_tool_registry` layers workflow tools over defaults on all three endpoints; `workflow_slug` on BOTH request models with the 422 pinned; envelope unwrapped everywhere; unresolved bindings stay loud.
