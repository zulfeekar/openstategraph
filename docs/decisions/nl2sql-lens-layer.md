# NL2SQL lens skill layer (`cpl-nl2sql`)

Ticket: launch-readiness/69

Added a lens skill layer to `~/osg-demo/workflows/cpl-nl2sql/` following the
one-directory-per-lens pattern Databricks recommends over prompt-only rules
and Equinor CPL independently converged on.

## Lenses derived (7, covering all 9 catalog tables)

- `cargoflow` — cargo movements — `shipping.cargoflow_latest`
- `geofence_dwell` — dwell time in a named geofence — `shipping.geofence_events_latest`, joining `shipping.geofences_v3r1` as a dimension
- `vessel_positions` — raw AIS pings — `shipping.ais_sampled`
- `vessel_idle_periods` — idle/loiter periods by voyage — `shipping.idle_events_v1r2`
- `forward_curves` — pricing curve values — `pricing.silver_forward_curves_ts_v1`, joining `pricing.silver_forward_curves_metadata_v1` as a dimension
- `refinery_outages` — plant outage events — `balances.plant_tracker_events`
- `plant_capacity_changes` — plant capacity baseline changes — `balances.plant_tracker_capacity`

Unplaced: `intelligence.nl2sql_metadata_index` — this is the search index
the package's own tools already query; infrastructure, not a fact table.

Grouped by the question a user asks, not schema tidiness — `geofence_dwell`
and `vessel_idle_periods` look similar (both produce a duration) but are
different tables answering different questions, and `refinery_outages` /
`plant_capacity_changes` are two distinct event tables over the same plant
dimension rather than one lens.

## Cross-cutting skills added

`skills/sql-dialect.md`, `skills/entity-resolution.md`,
`skills/time-windows.md`, `skills/answering.md` — method, not domain lore.

## Wiring

12 `input.markdown` nodes (7 lenses + INDEX + 4 cross-cutting), each wired
`skill` → `agent1.skill`, added directly to `workflow.json` (not through the
editor — see launch-readiness/72, the catalogue caps that port at 1
connection while the compiler supports many). Router's 4 branches and
`gate1.revise → agent1.feedback` verified unchanged after the edit.

## Verification

- Control question (Fujairah anchorage dwell): **39.12h across 4,447
  visits**, above the known-good band (14.3–23.9h). The agent picked the
  `vessel_idle_periods` lens with a hand-written lat/lon bounding box
  instead of `geofence_dwell` resolved against `geofences_v3r1` — an
  entity-resolution miss the new skill exists to prevent but a prompt rule
  can still be declined, exactly as the brief's own rationale predicts.
  Reported as observed, not tuned.
- Cargo volume question (Mongstad): 41s, no `LIKE`, used the pinned
  `SUM(CAST(quantity AS BIGINT))` aggregation from the `cargoflow` lens;
  resolved "Mongstad" to `'Mongstad [NO]'` via the existing distinct-values
  tool.

## Gap filed

`.scratch/launch-readiness/tickets/72-skill-port-max-connections-mismatch.md`

## Update 2026-08-25: the coordinate box was not removable

Ticket 67 asked to kill the hand-typed Fujairah bounding box in
`skills/entity-dictionary.md` and make named places resolve against
`geofences_v3r1`. Queried the real table directly first (58 distinct
`geofence_name` values; searched for `fujairah`, `fuj`, `uae`, `emirates`,
`anchorage`): **no Fujairah geofence exists.** The box is a genuine data-gap
workaround, not an unnecessary shortcut, so it stays — now annotated in
`entity-dictionary.md` as verified against the live table rather than
asserted from world knowledge.

Strengthened `skills/lenses/INDEX.md` and `skills/entity-resolution.md`
instead: a named-place dwell-time question routes to `geofence_dwell` by
rule, with the coordinate box reserved for a confirmed gap. Verified live
via `/api/runs`: `router1` now picks the `geofence_dwell` branch for the
Fujairah question (previously `vessel_idle_periods`).

The control number is still unresolved. This run's agent never invoked its
SQL-execution tool and guessed a literal `GEOFENCE = 'Fujairah anchorage'`
value instead — a separate tool-availability gap in this run path, not new
evidence about the 14.3–23.9h vs 39.12h/39.67h discrepancy. Ticket 67 stays
open with this evidence added; ticket 69 stays `partially resolved` — lens
routing is better but still a declinable prompt rule, no validator enforces
it. All required invariants (router 4-branch, revision loop, 12 skill
edges) verified intact in `workflow.json` before and after. Server restarted
and healthy at the end.

## Update 2026-08-25 (2): entity resolution turned into a guarantee — ticket 70

**Part 1 verdict: tools ARE reachable via the API/SSE path.** Posted
`/api/runs` with a question forcing a lookup ("exact spelling of the port
name that includes Fujairah"); `agent1`'s output showed `DistinctValuesTool`
actually ran (`SELECT DISTINCT geofence_name ... WHERE geofence_name LIKE
'%Fujairah%'`, zero rows, correctly reported as absent). So yesterday's
guessed literal was the model declining to use an available tool, not a
wiring gap — Part 2 was the right lever, no new "tools unreachable" ticket
filed.

**Live failure surfaced mid-session (real question, lowercase `mongstad`)
found three defects, all fixed:**

1. `DistinctValuesTool`'s `like` handling (`tools/databricks_explore.py`)
   built `WHERE {column} LIKE '{like}'` — case-sensitive, so lowercase
   `mongstad` missed `'Mongstad [NO]'`. Changed to
   `LOWER(column) LIKE LOWER('{like}')`.
2. A deliberate refusal (no fenced SQL) was rendered `VALIDATION FAILED` by
   `functions/validate_sql.py`, indistinguishable from a real validator
   rejection. Renamed that branch's header to `CLARIFICATION NEEDED`;
   `functions/execute_sql.py` now gates on either header.
3. `agent1`'s refusal prose offered "allow a substring/LIKE filter" as a
   workaround — exactly the defect this ticket removes. Added rule B5 to
   `agent1`'s systemPrompt in `workflow.json`: phrase a refusal as a question
   about the user's intent, never offer LIKE/wildcard as an out.

**Part 2 — `tools/sql_validator.py` `validate()` gained a
`resolve_before_filter` check**, TDD'd in `tests/test_sql_validator.py`
(7 new cases, fake distinct-values provider, no network):

- Reads `resolve_before_filter` from every `skills/lenses/*.md` YAML block
  at runtime (`_load_resolve_before_filter`), unioned, never hardcoded.
- Case-insensitive match, tolerant of the `'Mongstad [NO]'` bracket-suffix
  convention (`_literal_matches_known_value`).
- No match → hard violation naming column, literal, and `difflib`-nearest
  real values.
- Lookup failure (exception from the distinct-values call) → warning only,
  proceeds — same doctrine as `Grader.normalise` and the sqlglot
  parse-failure path.
- `LIKE` on a `resolve_before_filter` column → hard violation unconditionally,
  independent of the existing cardinality facet.
- A column absent from every lens's list is untouched.
- In-process cache keyed by `(table, column)` (`_distinct_values_cache`),
  module-level, so repeated attempts in one process cost at most one lookup
  per column.

**Verification, live, both against the running server:**

- *Owner's exact question*, lowercase, verbatim — "How many vessels departed
  from mongstad last week broken down by product and product group":
  resolved `mongstad` → `load_port = 'Mongstad [NO]'` on the first attempt
  (`gate1: pass`, no revision loop needed), returned a real product/product-group
  breakdown (Crude 9, Gasoline/Blending Components 8, Diesel/Gasoil 5, ... —
  `SELECT ... FROM ms_cpl_app_prod.shipping.cargoflow_latest WHERE
  load_port = 'Mongstad [NO]' AND load_date >= DATE_SUB(CURRENT_DATE, 7)
  GROUP BY \`group\`, group_product`).
- *Made-up port* — "How many vessels departed from Port Vandelay last week":
  no invented answer. Response is `CLARIFICATION NEEDED`, agent draft asks
  "Which exact port value did you mean... or would you like me to show a
  short list of nearby load_port distinct values" — a question about intent,
  no LIKE offered.

Invariants reverified in `workflow.json` before and after: 31 edges, 12
`agent1.skill` edges, `in1 -> router1`, `gate1.revise -> agent1.feedback`
intact. Server restarted at the end, healthy.

Ticket 70 closed — both the tool-availability suspicion (ruled out) and the
validator enforcement now hold under the owner's own real failing question,
not just synthetic ones.

## 2026-08-25 — lens files made load-bearing for the validator (launch-readiness/69)

Extended `tools/sql_validator.py` with four AST-vs-lens checks, following the
`resolve_before_filter` pattern (launch-readiness/70) exactly: read the same
`skills/lenses/*.md` YAML blocks at runtime via a new `_load_lenses()`, no
hardcoded table/column/lens name.

1. **Known table** (`unknown_table_for_lens`, reject) — every table in the
   SQL must be some lens's `canonical_table` or a declared join dimension.
2. **Declared joins only** (`undeclared_join`, reject) — two lens tables
   referenced together must be a pair some lens's `joins` list declares.
3. **Declared date column** (`date_column`) — a date predicate's column must
   be in its lens's `date_columns`; not the lens's `default_date_column` is a
   warning naming the default; not in the lens's `date_columns` at all is a
   rejection.
4. **Pinned aggregation** (`quantity_aggregation`, reject) — when a lens
   pins `quantity_aggregation` for its `quantity_column`, the SQL's
   aggregation function of that column must match the declared one.

All four are additive to the existing table/column-existence and
`resolve_before_filter` checks; none change existing behavior on SQL that
never touches a lens table. A missing/unreadable lens directory, or a lens
file whose YAML fence fails to parse, WARNS (`lens_layer` facet) and skips
checks 1-4 — never rejects, matching the parse-failure doctrine the rest of
this validator already follows.

Check 5 (reject coordinate filters on a named place unless no geofence
exists for it) was **not** built this session — it needs a live lookup
against `geofences_v3r1` plus the entity dictionary's documented-workaround
list, which is a different shape of check than 1-4's pure AST-vs-YAML
comparison, and forcing it in risked a shaky five instead of a clean four.
Filed as `launch-readiness/73`.

14 new unit tests added to `tests/test_sql_validator.py` (fixture lenses,
no filesystem/warehouse access), covering each check passing and failing,
a missing-lens-directory warn-and-skip, and a query touching one lens
correctly left untouched by all four. `python3 -m pytest tests/ -q`: 32/32
pass in `test_sql_validator.py`; the pre-existing `test_shape.py` failure
(scaffold's `node_types` list is stale against the current document, which
has grown routers/gates/skill nodes since scaffold) is unrelated to this
change and predates it.

### Live verification — blocked by an environment capability failure, not this change

All three verification questions returned `CAPABILITY_NOTICE` ("part of
this workflow was unavailable for this answer") with `outputs.prefetch1`
empty on every run — the metadata-prefetch/search tool never reached the
warehouse, in all three runs, before the agent ever drafted SQL. Since
`sql_validator.py` is only called after SQL is drafted, none of today's
four checks were exercised by any of the three live runs; this is not a
regression this change could have caused.

- **Mongstad control question**: no product/product-group breakdown
  produced — the agent asked for the exact `load_port` casing instead of
  resolving `mongstad -> 'Mongstad [NO]'` as it did on 2026-08-24. Same
  capability-unavailable note. **Regression gate result: did not pass**,
  but attributed to the tool-unavailable condition above, not to this
  session's edit — reverting `tools/sql_validator.py` would not restore
  the capability, since the failure occurs upstream of it.
- **"Port Vandelay"**: no invented answer — the agent listed three possible
  interpretations and asked which was meant. Acceptable, matches the
  no-invented-answer requirement even without a literal `CLARIFICATION
  NEEDED` string.
- **Fujairah anchorage dwell time**: router still selected the
  `geofence_dwell` branch (`decisions.router1 == "b1"`), confirming
  2026-08-25's earlier routing-rule fix held — but no number was produced;
  the agent asked to look up the exact `GEOFENCE` literal instead, same
  capability-unavailable condition.

`workflow.json` invariants reverified before and after: 31 edges, 12
`-> agent1.skill` edges, `in1 -> router1` (4 branches), `gate1.revise ->
agent1.feedback` intact. Server restarted at the end, healthy
(`/api/health` returned `{"ok":true,...,"model_configured":true}`).

Ticket 69 stays `partially resolved`: checks 1-4 are built, tested, and
believed sound by code review against the lens YAML, but the live
regression gate could not be re-confirmed this session due to an
environment issue outside this change's scope.

## 2026-08-25 — three false-rejection bugs in `sql_validator.py`, fixed live

Owner reported a correct query rejected four times in a row, with the
rejection text leaking to the user as the final answer. Three bugs found
and fixed in `~/osg-demo/workflows/cpl-nl2sql/tools/sql_validator.py`
(`~/osg-demo/` is not a git repo, so no commit exists there — the fix lives
only on disk; this entry is the record).

1. **`_default_distinct_values` read a failed lookup as "value absent".**
   `execute_statement`'s response `status.state` was never checked, so a
   non-`SUCCEEDED` statement (the known token-race failure) returned an
   empty `data_array` with no exception — `_resolve_check` then treated
   "empty list" as "literal not found" and rejected. Now raises on any
   non-`SUCCEEDED`/`None` result, which routes into the existing
   warn-and-pass path (`_resolve_check`'s `except Exception` clause), never
   a rejection. That warn-and-pass path itself, and the `[enumerable]`
   sample-based check staying warning-only, were already correct — this
   was the one gap.
2. **The lens "declared date column" check ran on every `WHERE`
   predicate, not just date ones.** It iterated `_DATE_PREDICATE_TYPES`
   (every comparison operator: `=`, `!=`, `<`, `IN`, ...) without checking
   whether the column was actually date/time-typed first, so
   `load_port = 'Mongstad [NO]'` was judged against `date_columns` and
   rejected as "not a declared date column". Added the same
   `_is_date_typed` guard the `date_predicate_seen` scan above it already
   used.
3. **The T-SQL dialect check was a blind regex over the raw SQL text**,
   matching backtick-quoted identifiers as "[bracketed]" — correct
   Databricks quoting flagged as T-SQL. Replaced with AST-anchored
   detection: `ISNULL(...)` parses as `exp.Anonymous` and is matched
   structurally by call name; `GETDATE()` is normalised away by sqlglot's
   databricks dialect into `exp.CurrentTimestamp`, so it is matched only
   when that AST node is present *and* the literal text still says
   `GETDATE(` — never on backticks/brackets alone. `TOP n` was already
   handled upstream as a parse failure and needed no change.

All three stay warnings-only where the doctrine requires it
(`resolve_before_filter` rejects only on a *confirmed* absence,
`dialect` never gates). `tests/test_sql_validator.py` (32 tests) passes,
including the pre-existing GETDATE/ISNULL dialect test, unmodified in
assertions. `workflow.json` was not touched — 31 edges, 12
`-> agent1.skill`, router 4 branches, `gate1.revise -> agent1` reverified
unchanged.

Live regression gate, server restarted:
- **Mongstad control question** ("how many vessels departed from mongstad
  last week broken down by product and product group") now returns the
  full product/product-group breakdown (e.g. Crude/Condensates — Crude: 9,
  ... 8 rows total) on the run that reached `gate1: pass`, with only the
  soft `[enumerable]` sample-miss warning attached, never a rejection.
  `attempts: 4` is normal ReAct tool-calling (distinct-values lookup,
  describe_table, draft, validate), not four validator rejections — the
  validator's own trace shows a single `VALIDATION: PASS`.
- **"Port Vandelay"** still produces a clarification, not an invented
  answer — the resolution guarantee survived the fix.

Filed `launch-readiness/74` for the separate, graph-shape issue: on a
genuinely exhausted revision loop, `summarize1` still returns the
validator's internal check/facet/lens text verbatim as the user-visible
answer, rather than a plain "could not answer reliably" message. Not fixed
here — out of scope for a validator-only change and touching `workflow.json`
prompt composition was judged too risky for this session's budget.

Ticket: launch-readiness/69
