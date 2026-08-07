Type: task
Status: open
Blocked by: 29, 31, 33, 41

## Question

The video-game workflow compiles clean (14 nodes, 0 warnings) but was never
runnable: routing (fixed, ticket 29), tools unresolvable at runtime (ticket
33), inert systemPrompt (ticket 31), inert per-node tool config (ticket 33),
dishonest dataset (ticket 41). Once those land, this ticket is the
integration pass: drive all four branches + HITL approve/reject + the revise
loop live through Chat, verify answers cite real CSV values, add the
real-file E2E test mirroring test_intent_routed_demo_file.py, and write its
AGENTS.md.

Known remaining tabular.py cleanups: camelCase/snake_case arg mismatch
between canvas fields and tool args; per-query DuckDB re-ingest of every
file; silent `pass` on a file that fails to load; f-string file paths in SQL.
