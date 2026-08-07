Type: task
Status: open
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
