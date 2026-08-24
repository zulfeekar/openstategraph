# NL2SQL fast path — prefetch, execute, summarise (2026-08-24)

Package under test: `/tmp/nl2sql/workflows/cpl-nl2sql/` (never the installed
`openstategraph` package — nothing there changed).

## What was built

1. **`functions/prefetch_context.py`** — a package-local `function.*` node
   (`prefetch1`), wired `in1 → prefetch1 → agent1`. No model call. Derives up
   to 5 search phrases from the question with plain heuristics (the whole
   question; quoted terms; capitalised term sequences; a hit against a fixed
   14-word measure/metric vocabulary — "dwell time", "idle", "volume", etc.),
   fires them at the metadata vector index **concurrently**
   (`ThreadPoolExecutor`), also greps `skills/entity-dictionary.md` for a
   matching section, merges/dedupes rows by id, and returns the question plus
   a compact `table / column / description / usage_hint / sample values`
   block appended to the prompt.
2. **Execute, then summarise.** `agent1`'s system prompt now requires it to
   call `sql_validator` then `databricks_sql_query` exactly once and quote
   the raw rows verbatim under `Raw results:`. A new `summarize1` (`agent.llm`,
   no tools) turns that into the final answer: numbers, a per-day Markdown
   table, the SQL kept for auditability, and any stated assumption.
3. **`grader1` removed from the fast path.** The mechanical `sql_validator`
   tool stays; the 54s grader model call is gone. Edges:
   `agent1.result → summarize1.prompt → out1.result`.
4. **Model cost cut.** `agent1.reasoningEffort = "low"`. All model-bearing
   nodes use the `provider/model` slash form.
   `summarize1.reasoningEffort` was left `""` after the first run reported,
   via `capability_warnings`, that `gpt-4o-mini` rejects `reasoningEffort`
   entirely — confirming the CLAUDE.md rule that a refused effort surfaces
   rather than being swallowed. `openstategraph validate` also surfaced (and
   this document does not attempt to fix, as out of scope) six pre-existing
   `unknown node type` warnings for the package's own `cpl-nl2sql/tools.*`
   classes — a `validate`-only capability-loading gap, not something this
   change introduced; `run` loads them correctly.

## Model comparison (owner addition): gpt-5 vs gpt-5-mini on the same prefetch

| Question | gpt-5 | gpt-5-mini | Same SQL/tables/figures? |
|---|---|---|---|
| A (dwell time) | 120s | 110s | Yes — identical per-day `avg_dwell_hours` values |
| B (diesel/gasoil) | 80s | 59s | Yes — Sikka top at 216,255,732 bbls on both, same grade breakdown |

With prefetch supplying tables/columns/hints up front, gpt-5-mini wrote
correct SQL both times — same tables, same columns, same numbers as gpt-5.
**Shipped as the default** (`agent1` and `summarize1` both
`openai/gpt-5-mini`) on the strength of this result. This was tested only
on prefetch-hit questions; the owner's caveat stands unverified here — a
prefetch-miss / pure-exploration case was not run, so whether mini is safe
as a general default or only as a prefetch-hit specialisation is still
open. The system prompt still allows falling back to
`databricks_metadata_search` when prefetch is insufficient, but nothing in
this change routes that case to a stronger model automatically.

## Measured result (deliverable)

Baseline (measured previously, quoted in the brief): **250s**, SQL text
only, 8 agent model calls (176s) + 1 grader call (54.5s), nothing executed.

| | A (dwell time) | B (diesel/gasoil) |
|---|---|---|
| Before | 250s, SQL only, no numbers | not previously run |
| After — gpt-5 | 120s, numbers present | 80s, numbers present |
| After — gpt-5-mini (shipped default) | 110s, numbers present | 59s, numbers present |

**A's figures vs Genie:** Genie reported mean ≈18h, range 14–24h. This
workflow's per-day average (gpt-5 and gpt-5-mini agree): range 14.32–23.90h,
mean of the 12 daily averages ≈18.4h. **Matches.**

**Target was not met.** ~250s → ~110s (mini) / ~120s (gpt-5) is a real
~2–2.3x speedup and the answer now contains numbers instead of only SQL, but
neither run is under the 30s target. Two model round-trips remain
irreducible in this shape (agent1's ReAct loop — prefetch does not eliminate
the validate-then-execute turns — plus the summarizer), and `low`/default
reasoning effort on a `react`-tier tool-calling agent still costs tens of
seconds per turn. Reporting this as a negative result on the 30s target,
with the timings above, per the brief's own instruction.

**Warehouse calls spent:** 4 (`databricks_sql_query`, one per full run: A
gpt-5, A mini, B mini, B gpt-5). Metadata vector-index searches (prefetch,
`sql_validator`'s facet lookups) are not warehouse calls. Well under the
10-call cap.

## Commit

`Ticket: launch-readiness/12`
