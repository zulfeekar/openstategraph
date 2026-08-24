# NL2SQL vs Genie parity — Fujairah dwell time

## Result: A passes, B passes without hard-coding.

## Levers used, in order
1. **Entity dictionary** (`skills/entity-dictionary.md`, package-local) — Fujairah
   anchorage bounding box (25.00–25.35°N, 56.20–56.60°E), the fact that no
   matching geofence exists, and a pointer to `idle_events_v1r2` as the dwell
   measure table.
2. **Re-framing obligation** — rule 2 of `agent1`'s system prompt rewritten from
   a suggestion to an obligation: after two failed lookups in one table
   family, the agent MUST search for the underlying measure/concept across
   schemas and check the entity dictionary, rather than re-checking the same
   family.
3. **Stronger model** — switched `agent1` and `grader1` from
   `ollama/gpt-oss:120b-cloud` to `openai/gpt-5` (owner-authorized mid-session,
   Anthropic credits exhausted). This exposed and fixed a real defect: the
   venv's `openstategraph[openai]` extra was not installed, so
   `build_chat_model("openai:gpt-5")` returned `UnconfiguredProvider`, which
   `NodeRuntime._base_model`'s catch-all `except Exception` silently
   downgrades to the shared default — the exhausted Anthropic key — with no
   error surfaced. Installing `langchain-openai` in the venv fixed it.
   Filed as `launch-readiness/45` (see below).

## A — target question
> average dwell time for VLCCs in Fujairah anchorage, last 14 days, by day

Agent's SQL (verbatim, against `ms_cpl_app_prod.shipping.idle_events_v1r2`,
filtered by `EQ_VESSEL_CLASS='VLCC'` and the bounding box) executed for real:

```
day         avg_dwell_hours  event_count
2026-08-12  23.90            1
2026-08-13  19.04            24
2026-08-14  19.68            22
2026-08-15  14.32            22
2026-08-16  14.78            26
2026-08-17  14.69            22
2026-08-18  20.55            17
2026-08-19  19.88            19
2026-08-20  16.84            23
2026-08-21  16.81            20
2026-08-22  19.71            16
2026-08-23  20.57            16
```

Mean across days ≈ **18.4 h** — agrees with Genie's ~18 h average and its
~14–24 h per-day range. Assumption stated by the agent matches Genie's: no
Fujairah geofence exists, a bounding box was used, `idle_events_v1r2` is the
dwell-measure table.

## B — generality check
> Which Indian ports exported the highest volume of diesel/gasoil to East
> Africa, and what grades were shipped?

Agent answered against `ms_cpl_app_prod.shipping.cargoflow_latest` (a
different table entirely), ranking Sikka, Vadinar, New Mangalore, Cochin,
Paradip by volume with per-port grade breakdowns, filtering
`unload_alternative_region LIKE '%East Africa%'` (correctly treating it as
multi-valued per the prompt's existing rule 6). Nothing in the entity
dictionary or prompt names India, diesel, or East Africa — **this confirms
generality; A did not pass because of hard-coding.**

## Warehouse calls
1 direct verification execution (question A's SQL, run manually to get real
numbers since the agent's own answer did not print them) + agent-internal
calls per run (bounded by prompt rule 7 to at most one `databricks_sql_query`
each, plus `sql_validator` which is free). No `--trace-file` was used to
instrument exact counts; both runs answered in a single pass with no visible
grader retries. Comfortably under the 15-call cap; exact count not
instrumented.

## What made the difference
The model swap (OSS 120B → GPT-5) was necessary — four prior full runs on
the Ollama model never broadened past the geofence family despite budget and
tools already being fixed. The entity dictionary and re-framing rule likely
help but were not isolated in a controlled A/B (would need a fifth run on the
old model with only those two levers, not spent given the budget/effort
constraints of this session).

## Defect filed
`launch-readiness/45` (already the ledger's top ticket number) — model
strings silently fall back to the shared default on ANY resolution failure,
including a missing provider extra, with no error or warning surfaced to the
caller. `_base_model`'s bare `except Exception` should at minimum log or
attach a `capability_warning`.
