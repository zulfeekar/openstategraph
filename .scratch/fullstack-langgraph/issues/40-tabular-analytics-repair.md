Type: task
Status: mostly resolved (2026-08-07) — live-verified end to end; remaining items below
Blocked by: 41

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


## Resolution (2026-08-07)

Live-verified against the real backend and Ollama cloud, after tickets
29/31/33 landed:

- **Greeting branch**: routed `b4-greeting` (the v2 id), grader passed,
  correct friendly reply. Zero tool warnings — slug discovery bound all four
  tabular tools.
- **Data branch, streamed**: router → orchestrator `Send` fan-out (task-1,
  task-2) → workers calling the real DuckDB tools → report join → deep
  grader **rejected the first attempt** (replan visible as task-1-1/task-1-2)
  → second attempt paused at `human1`.
- **HITL approve**: resumed the checkpointed thread, finished
  `human1: approved`. Answer (Wii, 209.43M) **independently verified** by
  running the same aggregation in DuckDB directly against vgsales.csv.
- **HITL reject with feedback** ("state the publisher"): fed back through the
  orchestrator replan; the revised candidate named Nintendo and re-paused.

Still open here: the vgsales data itself is ticket 41's fabricated 50-row
sample (the *sums* are internally consistent, the provenance is not); the
tabular.py cleanups listed above (camelCase args, per-query re-ingest,
silent load `pass`); an AGENTS.md; a real-file E2E pytest suite mirroring
test_intent_routed_demo_file.py.

One UI finding from the browser pass, unfixed: during a backend-streamed
run the Inspector transiently showed "Node not found" — the stream reports
LangGraph-sanitized names (`agent.llm-1` etc.) that the selection layer
briefly fed to the inspector. Cosmetic, worth a look with ticket 48.
