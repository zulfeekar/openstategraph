Type: task
Status: resolved (2026-08-08) — 3 permanent fixes landed; 1 residual filed below

## Question

Run 5 mixed questions through Open API Explorer live; identify gaps/bugs; fix permanently.

## Resolution

Test: weather-compare, GDP+capital, Colosseum, quakes>M5, population+arithmetic — all against the real APIs and Ollama cloud.

Bugs found and fixed permanently:
1. **Blind archetype labelling** — workers had no `role` set, so the supervisor's labelling prompt showed bare names and routed GDP to Wikipedia and weather to a tool-less worker. Fix: runtime derives a worker's description from its bound tools when `role` is empty (test: `TestArchetypeDescriptionsAreNeverBlind`); the document also now sets explicit roles as the worked example.
2. **Retry policy silently inactive** — installed `langgraph` has no `set_node_defaults`, and the fallback comment claimed per-node coverage that didn't exist; one transient Ollama 500 emptied a fan-out worker or 502'd the run. Fix: default `RetryPolicy` applied per `add_node` when graph defaults are unavailable, explicit override still wins (test in `test_node_overrides.py`).
3. **Empty final message recorded as the answer** — `out[-1].content` is "" when an agent ends on a dangling tool call. Fix: `_final_text` walks back to the last non-empty AI text (agents + workers); report renders an explicit `(this member produced no result)` instead of a blank section.

Result: Q2–Q5 grounded and correct (World Bank GDP figure, Berlin, Colosseum, USGS quake table, Brazil population + arithmetic); Q1 returns real weather for both subtasks.

Residual (filed as follow-up on this ticket): the supervisor's *decomposition* sometimes emits near-duplicate subtasks ("Oslo" twice on compare-two-cities) — a planning-prompt quality issue, not wiring; candidate fix is asking the labelling pass to also de-duplicate/parameterise subtasks, and belongs with the orchestrator prompt work.
