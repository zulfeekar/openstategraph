Type: task
Status: resolved (2026-08-08) — live-verified
Blocked by: 33, 35, 37

## Question

A workflow proving the supervisor pattern against live keyless public APIs
(Open-Meteo, REST Countries, Wikipedia REST, USGS earthquakes): router →
supervisor dispatching typed subtasks to per-API worker archetypes →
function node joining results → grader. Structured output where the API
answer must be tabular.

Constraints: tools are honest about network failure (errors as data);
tests run offline against recorded fixtures with a live marker for the
real thing; no API keys anywhere; rate-limit friendliness documented in
the workflow's AGENTS.md.

## Resolution

Built (session + integration): 6 keyless-API tools (`tools/openapis.py`, offline fixtures + opt-in `-m live`), supervisor archetypes implemented per ticket 37 (hybrid labelling, default worker, `fan_out` multi-map), canvas document with 4 worker archetypes joining into `function.format_report` → grader → out. Live E2E: Tokyo weather + Japan population dispatched to two different archetypes, grader revise re-planned once (`attempts: 2`), answer grounded in real API rows.
