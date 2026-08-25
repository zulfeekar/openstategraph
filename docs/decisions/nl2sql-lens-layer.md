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
