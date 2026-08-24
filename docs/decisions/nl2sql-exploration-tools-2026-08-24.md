# NL2SQL exploration tools — before/after (2026-08-24)

## What changed, in `/tmp/nl2sql/workflows/cpl-nl2sql/`

- `agent1.data.tokenBudget`: `500` → `12000`.
- `grader1.data.model`: `""` (fell back to the shared Anthropic default,
  which is exhausted) → `ollama/gpt-oss:120b-cloud`, matching `agent1`. The
  first test run failed outright with `AnthropicInvalidRequestError:
  Your credit balance is too low` at the grader step — this was fixed before
  any real before/after comparison was possible.
- New package-local tool file `tools/databricks_explore.py`:
  - `DescribeTableTool` (`describe_table`) — `w.tables.get()`, free.
  - `ListTablesTool` (`list_tables`) — `w.tables.list()`, free.
  - `DistinctValuesTool` (`distinct_values`) — one bounded
    `SELECT DISTINCT col FROM table [WHERE col LIKE '%x%'] LIMIT n`, wakes
    the warehouse, read-only, LIMIT enforced, scoped to `ms_cpl_app_prod`.
  - All three wired into `agent1`'s `tools` port in `workflow.json`.
- `tools/databricks_nl2sql.py`, `DatabricksSqlQueryTool`: table-existence
  check widened from a hardcoded 7-table allowlist to any
  `ms_cpl_app_prod.*` reference, so the new tables the agent can now find
  (e.g. `idle_events_v1r2`) are not blocked from execution.
- `tools/sql_validator.py`: the `enumerable` facet rule was a hard `FAIL`
  when a literal wasn't among the index's top-N sample values (this is what
  produced the false refusal on "Mongstad" noted in the task). Changed to a
  separate `warnings` list, rendered as `WARNING`, not `FAIL` — the run can
  still proceed. Every other rule (table/column existence, cardinality,
  time-window) is untouched and still a hard failure.
- `agent1.data.systemPrompt`: rewritten to explicitly license exploration —
  call `list_tables`/`describe_table`/`distinct_values` when metadata search
  doesn't name the entity, world knowledge allowed for facts about the world
  but never for schema names, state assumptions when proceeding on one,
  refuse only after genuinely exploring.

## The test

Question: *"What's the average dwell time for VLCCs specifically in the
Fujairah anchorage over the last 14 days, broken down by day?"*

Confirmed independently (`w.tables.get`) that
`ms_cpl_app_prod.shipping.idle_events_v1r2` exists (20 columns) and that
`ms_cpl_app_prod.shipping` has 47 tables total, most of which the metadata
search index does not surface for "Fujairah".

**Before**: *"The dataset does not contain a geofence entry for 'Fujairah
anchorage'… I cannot provide…"* (per the task's own diagnosis, produced by a
budget too small to iterate).

**After** (4 CLI runs against the changed package, via
`./venv/bin/openstategraph run ./workflows/cpl-nl2sql "<question>"`):

All four runs completed (no budget/grader errors), each doing substantially
more work than before — token usage per run: 171,786 / 249,042 / 282,927 /
333,798 total tokens (vs. ~500-token budget before, which couldn't even
complete one tool round trip). This confirms the agent is iterating many
times, not stopping after one search. Each run still ended in a refusal, and
the refusal got progressively more specific as the prompt was strengthened:

1. "does not contain a geofence entry... for 'Fujairah anchorage'"
2. "does not contain a geofence or anchorage identifier for Fujairah"
3. "no matching entries in `ms_cpl_app_prod.shipping.geofences_*` or
   `geofence_events_latest`" (named the specific tables it checked)
4. (after prompt rule 2 was strengthened to explicitly say "there may be a
   dedicated events/idle/dwell table you have not tried" and to try
   `list_tables` on `shipping`) — still: "no table includes that location"

Grader passed every attempt in 1 attempt (a plain refusal always passes per
its own rubric), so the revision loop never triggered.

**Honest result: the agent still refuses.** It clearly explores far more
than before — the token growth across turns shows dozens of tool calls
inspecting geofence-family tables — but it never called `list_tables` widely
enough (or `distinct_values` with a widened term like `%fujai%`/`%uae%`/
`%gulf%`) to surface `idle_events_v1r2`, the table Genie eventually found on
its 14th+ call. The bottleneck the task diagnosed (budget, missing tools,
prompt licensing) was real and is fixed — budget and tools are no longer the
limiting factor — but matching Genie's actual search persistence (trying
`idle`, `anchorage`, `dwell` as `list_tables`/search terms, not just
geofence-adjacent ones) needs either a stronger nudge or more turns than four
manual runs could establish. This is a genuine negative result, not a success
being written up as one.

## Warehouse calls

Not independently invoked outside the agent loop. I could not introspect
exactly how many `distinct_values`/`databricks_sql_query` calls (vs. free
`describe_table`/`list_tables`/metadata-search calls) each of the 4 agent
runs made — no per-tool-call trace was exposed by `--trace-file` or `--json`.
Given the task's 6-warehouse-call cap and the uncertainty here, this is
flagged rather than a hard number is claimed. No `distinct_values` runs were
made directly by me; all warehouse-touching activity was inside the agent's
own tool loop across 4 full runs.

## Ledger

`Ticket: launch-readiness/12` — this is a log commit only, not a ticket
resolution; ticket 12 (the stranger-install test) is unrelated to this work
and untouched. No new ticket was filed: the negative result (agent still
refuses) is recorded here rather than as a new "bug", since the task framed
either outcome as a valid report.
