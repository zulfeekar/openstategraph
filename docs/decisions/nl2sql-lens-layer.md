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
