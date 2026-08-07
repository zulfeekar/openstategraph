Type: grilling
Status: resolved (2026-08-07) — hybrid routing, decided by the user
Blocked by: 30 (resolved)

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

## Resolution (user decision, 2026-08-07)

**Hybrid routing.** The supervisor's planning prompt lists the wired worker
archetypes (name + description) and the model labels every subtask with one.
A label that names no wired archetype is **not trusted**: it falls back to
the default worker, so a misroute degrades to today's single-archetype
behaviour instead of a silent wrong answer from a tool-less worker.

Implementation decisions that follow (routine calls, recorded here):
- The label matches the worker node's **archetype name** — its node title,
  slugified — not its id; the supervisor prompt and the path map use the
  same string, one source.
- **Default worker**: a `default` toggle on the worker card; when none is
  set, the first wired archetype (canonical edge order). Exactly one
  default — the validator warns on two.
- Compiler: `fan_out` becomes `dict[str, list[str]]` (orchestrator → its
  archetype nodes); `_fan_out_router` emits `Send(archetype_node, payload)`
  per labelled subtask; `Subtask` gains an `archetype` field; state keys it
  touches keep their existing reducers (`worker_results` is task-id-keyed
  and already merge-safe).

The wider principle the user stated with this decision — **every prebuilt
node ships minimum viable code with basic behaviour, extended by dropping
files into the workflow's own directory** — is recorded on
[middleware slot table](32-middleware-slot-table.md) and in the map's fog,
because it reaches beyond this ticket.
