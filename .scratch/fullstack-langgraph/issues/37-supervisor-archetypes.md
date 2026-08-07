Type: grilling
Status: open
Blocked by: 30

## Question

The orchestrator is a `Send` fan-out to exactly one worker archetype
(`workers` port, maxConnections: 1). A supervisor pattern needs dispatch by
*kind*: research-worker vs sql-worker vs writer, each its own node with its
own tools/prompt, chosen per subtask.

- Port shape: N `worker` ports (ports vary with config — the preferred
  mechanism) vs one port with maxConnections lifted? CLAUDE.md: prefer
  varying the number of ports.
- `Orchestrator.split()` gains archetype selection: deterministic (round
  robin / rule) and model-driven both meaningful — where does that choice
  live in config?
- State: `worker_results` already keys by task id; a task now also carries
  its archetype. Reducer audit for the new key(s) — every multi-writer key
  gets a named reducer (standing rule).
- Compiler: `fan_out` becomes `dict[str, list[str]]`; `_fan_out_router`
  returns `Send(archetype_node, payload)` per subtask.
