# The `ms_cpl_app_prod` warehouse — a map for deciding which table answers a question

Written 2026-08-25 for an engineer who has never seen this warehouse and has to
pick a table. It is organised around the questions people ask, not around the
schema.

**Every claim below carries its source.** The four sources, in descending
authority:

| Tag | Means |
| --- | --- |
| **UC** | Unity Catalog metadata (`w.tables.get`) — what actually exists |
| **index** | a row in `ms_cpl_app_prod.intelligence.nl2sql_metadata` — what the agent is *told* |
| **verified** | a SELECT run against the warehouse on 2026-08-25, with the number |
| **lens** | a file under the NL2SQL package's `skills/lenses/` — a working system's conclusion |
| **inferred** | reasoning, not checked. Treat as a hypothesis |

Where sources disagree the disagreement is stated and one is named. There are
five such disagreements; the first one is the most expensive thing in this
document.

---

## 0. Read this first: the vessel dimension fans out ~9×

**`shipping.dim_vessel_latest` is not one row per vessel.** Joining it on `imo`
multiplies rows, and any `SUM`, `AVG` or `COUNT(*)` downstream of that join is
wrong by roughly an order of magnitude.

Verified 2026-08-25:

| Measure | Value |
| --- | --- |
| rows | 479,464 |
| distinct `imo` | 57,893 |
| rows with `imo IS NULL` | 61,367 |
| rows with `imo = 0` | 81,910 |
| median rows per non-null `imo` | 6 |
| max rows for one `imo` | 81,910 (that is `imo = 0`) |
| IMOs carrying **more than one** `eq_vessel_class` | 17,193 |

And the join measured end to end (verified):

```
cargoflow_latest WHERE load_date >= 2026-08-01                  16,277 rows
    JOIN dim_vessel_latest ON v.imo = c.vessel_imo             145,263 rows   -- 8.9x
```

It is a slowly-changing dimension: UC shows `valid_from`, `valid_to`,
`checksum`, `updated_at`. `valid_to` is **never null** — the open-row sentinel
is `9999-12-31 23:59:59` (verified: 0 rows with `valid_to IS NULL`). But
filtering to the sentinel is **not enough**:

```
... AND v.valid_to = TIMESTAMP'9999-12-31 23:59:59'             21,755 rows   -- still 1.34x
```
12,619 IMOs have more than one open row (verified).

**The only safe shape is a deduplicated subquery, and it must exclude `imo = 0`
and null:**

```sql
JOIN (
  SELECT imo,
         any_value(eq_vessel_class)     AS eq_vessel_class,
         any_value(eq_vessel_class_alt) AS eq_vessel_class_alt,
         any_value(eq_vessel_type)      AS eq_vessel_type
  FROM ms_cpl_app_prod.shipping.dim_vessel_latest
  WHERE imo IS NOT NULL AND imo <> 0
    AND valid_to = TIMESTAMP'9999-12-31 23:59:59'
  GROUP BY imo
) v ON v.imo = c.vessel_imo
```
(`any_value` is a choice, not a truth: 12,619 IMOs genuinely disagree with
themselves about class. If the answer depends on the class, say which row you
took — **inferred** that any_value is acceptable for coarse class reporting;
**not verified** that the duplicate rows are semantically equivalent.)

### Disagreement 1 — everyone says "one row per vessel" and nobody checked

- **index**, `nl2sql_metadata` table row for `dim_vessel_latest`: *"Vessel
  dimension table — one row per vessel (by IMO)"*, `usage_hint: JOIN
  ms_cpl_app_prod.shipping.dim_vessel_latest v ON v.imo = <table>.imo`.
- **lens**: `cargoflow.md`, `geofence_dwell.md`, `vessel_positions.md` and
  `vessel_idle_periods.md` each declare the same join with the comment
  `# one row per vessel; class and type`.
- **verified**: false, by the numbers above.

**Believe the numbers.** Four lens files and the search index all publish the
same wrong join. This is the mechanism by which a `SUM(quantity)` is silently
9× too large, and the most plausible cause of the doubled dwell time recorded
as `launch-readiness/67` — that ticket blames the geofence dimension, and
section 4 shows the geofence dimension is innocent.

Filed as **`launch-readiness/82`**.

The name is also misleading: **UC** shows `dim_vessel_latest` is a `VIEW`, and
it has exactly the same row count as `shipping.dim_vessel_v2r0` (479,464,
verified). "latest" deduplicates nothing.

### Traces: this is already costing answers

`~/Downloads/openstategraph-trace_2.json` and `_3.json` (real runs, question
*"what loaded at Mongstad in the last 7 days"*) show the agent joining
`dim_vessel_latest ON v.imo = c.vessel_imo` with no dedup, then in a later
attempt abandoning the join entirely with the note *"I did not join to
dim_vessel_latest because that table is not declared as a joined dimension for
the cargoflow lens (it caused validation to fail previously)"* — while
`cargoflow.md` **does** declare it. So the agent has been getting it wrong in
both directions: fanned out when it joins, and refusing a declared join when it
does not. The same trace also invents a column `vessel_flag`, which does not
exist in **UC**.

---

## 1. Which table answers which question

| The question | Table | Section |
| --- | --- | --- |
| How much of X moved from A to B? Who carried it? | `shipping.cargoflow_latest` | 2 |
| How many vessels went through Hormuz / Suez / Panama? How long did they sit there? | `shipping.geofence_events_latest` | 3 |
| How long did a vessel idle (not at a named place)? | `shipping.idle_events_v1r2` | 5 |
| Where is / was a vessel? Speed, draught history | `shipping.ais_sampled` | 6 |
| Where is a vessel *right now* (one row per vessel) | `shipping.current_vessel_positions_v2r0` | 6 |
| Which refinery units are down, and how much capacity is offline? | `balances.plant_tracker_events` | 7 |
| How has a plant's rated capacity changed? | `balances.plant_tracker_capacity` | 8 |
| What is the forward price of X? | `pricing.silver_forward_curves_ts_v1` + metadata | 9 |
| What does a charter cost? What is the freight rate? | **nothing** — see section 12 | 12 |

Sizes, all **verified** 2026-08-25 (`COUNT(*)`):

| Table | Rows | Freshest row | Kind (**UC**) |
| --- | --- | --- | --- |
| `shipping.ais_sampled` | 193,752,911 | `YEAR_MONTH_DAY = 20260825` (today) | MANAGED, partitioned |
| `balances.plant_tracker_events` | 31,858,443 | `start_date` max **2029-12-17** (future) | MANAGED |
| `shipping.cargoflow_latest` | 2,657,261 | `load_date` max **2026-11-01** (future) | VIEW over `cargoflow_v2r0` |
| `shipping.geofence_events_latest` | 2,183,424 | `ENTRY_TIME` 2026-08-25 17:34 | VIEW |
| `balances.plant_tracker_capacity` | 1,643,670 | `change_date` max 2029-12-15 (future) | MANAGED |
| `pricing.silver_forward_curves_ts_v1` | 1,013,404 | `date` max 2028-11-01 (forward dates) | MANAGED |
| `shipping.dim_vessel_latest` | 479,464 | — | VIEW |
| `shipping.idle_events_v1r2` | 225,844 | `IDLE_START` 2026-08-24 19:49 | MANAGED |
| `pricing.silver_forward_curves_metadata_v1` | 57,280 | `applicable_at` 2026-08-24 | MANAGED |
| `shipping.geofences_v3r1` | 58 | — | MANAGED |

---

## 2. `shipping.cargoflow_latest` — cargo movements

**One row is one cargo movement.** Verified: 2,657,261 rows, 2,657,261 distinct
`cargo_movement_id`. The grain in `cargoflow.md` is correct and checkable.

**Dates.** Two, and they mean different things (**UC**: both `DATE`, a real
date type — unlike almost every other date in this warehouse).
- `load_date` — loaded at origin. The default. Range **2015-06-01 →
  2026-11-01** (verified).
- `unload_date` — discharged. Null for in-transit cargo; **0.5% null**
  (verified), so this is a small effect, not the dominant one.

**Trap — the future.** `load_date` runs 68 days past today: **1,865 rows have
`load_date > CURRENT_DATE`** (verified). These are scheduled/expected cargoes.
A "how much moved this year" answer that omits `load_date <= CURRENT_DATE`
counts cargo that has not happened. No lens and no index row mentions this.
Filed as **`launch-readiness/83`**.

### Disagreement 2 — lag

`cargoflow.md` declares `typical_lag_days: 5`. The data **leads** by 68 days
rather than lagging. There is presumably still a settlement lag on *completed*
movements — **not verified**, and it cannot be read off a max date. Treat
`typical_lag_days: 5` as unsourced.

**Quantity.** `quantity` is **UC** `LONG`, no unit column on the table, no UC
comment. **index** says outright: `unit: "UNKNOWN — do not report without a
source"`, with the note *"Inferred barrels from domain analysis (cargo sizes vs
vessel DWT). No UC comment confirms this."* `cargoflow.md` reaches the same
conclusion independently and correctly says to report "quantity" rather than a
unit.

**The inference is weaker than the index makes it sound.** The index row
justifies barrels with *"typical VLCC ~550k, LR2 ~530-630k, MR ~300k"*.
Verified medians of `quantity` by `vessel_class_alternative`:

| Class | Median `quantity` | Index's claimed typical |
| --- | --- | --- |
| VLCC | 493,669 | ~550k |
| Handysize/MR1 | 43,903 | ~300k |
| all rows | 41,863 | — |

VLCC is roughly in the claimed range; **MR1 is off by a factor of seven**. So
the arithmetic that produced the "barrels" inference does not reproduce.
**Disagreement 3**, and the honest statement is: *the unit of `quantity` is
unknown; barrels is a guess whose supporting evidence does not hold up.* Never
print a unit. Filed as **`launch-readiness/84`**.

**The product hierarchy** — four levels, all **index**-sourced with real
values:

- `group` (3 values): `Clean Petroleum Products`, `Crude/Condensates`,
  `Dirty Petroleum Products`. **`group` is a reserved word — backtick it:**
  `` `group` ``.
- `group_product`: `Crude`, `Naphtha`, `Diesel/Gasoil`,
  `Gasoline/Blending Components`, `Jet/Kero`, `Fuel Oil`, `LPG+`, `Biodiesel`,
  `Other Clean Products`, `Asphalt/Bitumen`, `Other Dirty Products`,
  `Condensate`.
- `category`: `ULSD (Ultra Low Sulphur Diesel)`, `Gasoil`, `Finished Gasoline`,
  `Blending Components`, `Propane`, `High Sulphur Fuel Oil`, `Medium-Sour`,
  `Light-Sweet`, `Full Range`, `Light Naphtha`, `Heavy Naphtha`, `Chemicals`,
  `Olefins/Other Chemicals`.
- `grade`: `Arab Light`, `Arab Heavy`, `West Texas Intermediate (WTI)`,
  `ULSD / 0.001 / 10ppm`, `Jet A-1`, `RON 88-92 (Regular)`,
  `RON 93-96 (Premium)`, `Methanol`, `FAME`, `Ammonia`, `Palm Oil`.
  **Nullable** — many cargoes have no grade (**index**).

**Why this matters: a user says "diesel" and means one of three levels.**
`group_product = 'Diesel/Gasoil'` is the whole barrel of middle distillate;
`category = 'ULSD (Ultra Low Sulphur Diesel)'` and `category = 'Gasoil'` are
different products inside it; `grade = 'ULSD / 0.001 / 10ppm'` is one spec.
Ask which, or state the level you chose. Likewise "naphtha" spans
`group_product = 'Naphtha'` and four categories (`Full Range`, `Light
Naphtha`, `Heavy Naphtha`, `Other Naphthas`).

**Geography — six columns per end, and they are not synonyms** (**index**):
`load_region` (macro: Asia, Europe, ...), `load_country` (proper-cased),
`load_port` (format `"Port Name [XX]"` — so `Rotterdam` alone will not `=`
match), `load_terminal`, `load_shipping_region_v2` (industry regions:
`Northwest Europe (NWE)`, `Middle East Gulf (MEG)`, `Northeast Asia (NEA)`,
`Gulf of Mexico (GoM)`, ...), and `load_alternative_region` — see traps.
Every one of them exists in an `unload_` twin. A filter on "country" that does
not say which end silently picks one (`cargoflow.md` says this, correctly).

---

## 3. `shipping.geofence_events_latest` — geofence visits

**One row is one complete visit**, carrying both `ENTRY_TIME` and `EXIT_TIME`
on the same row (**UC**: both `TIMESTAMP`, real types). Verified: 2,183,424
rows = 2,183,424 distinct `ID`. Dwell is `EXIT_TIME - ENTRY_TIME` on one row —
never a self-join, never a window pairing separate entry and exit rows.
`geofence_dwell.md` states this correctly and is the place to look for the
exact expression.

Coverage **2024-01-24 → 2026-08-25 17:34** (verified). Effectively real-time.

`EXIT_TIME` null (vessel still inside): **0.38%** (verified). Small, but it
turns a dwell subtraction into a null that vanishes from an `AVG` without
comment — exclude it explicitly.

Duration is skewed; `geofence_dwell.md` pins median with the mean reported
alongside, per `launch-readiness/78`.

---

## 4. `shipping.geofences_v3r1` — the geofence dimension (58 rows)

**One row per geofence. It does not fan out.** Verified: 58 rows, 58 distinct
`geofence_name`, 58 distinct `port_name`, **zero** duplicated `port_name`.
Every row has `max_open_arrival_valid_from = 2024-01-24` and
`max_open_arrival_valid_to` **null**.

### Disagreement 4 — the versioned-dimension trap does not exist

`geofence_dwell.md` warns that `geofences_v3r1` is *"a versioned/time-sliced
dimension, not one row per geofence"* and that a join on `geofence_name` *"can
match more than one row"*, and forbids joining on `port_name` as a fan-out.
**Both are false as of 2026-08-25**: name and port are each unique across all
58 rows, and no row is time-sliced. Believe the query.

That matters because the lens offers this as the likely cause of
`launch-readiness/67`'s doubled dwell. It is not. Section 0 is. Filed as
**`launch-readiness/85`**.

The join `geofence_events_latest.GEOFENCE = geofences_v3r1.geofence_name` is
safe and only needed for the human-readable `port_name` or the WKT polygon;
a plain `WHERE GEOFENCE = '...'` needs no join at all.

**All 58 geofence names** (verified — this is the entire resolvable vocabulary
for "a named place"):

`Binzhou`, `Dalian`, `Lianyungang`, `Longkou`, `Qingdao`, `Tianjin`, `Yantai`,
`antwerp_basf`, `antwerp_borealis`, `bab-el-mandeb`, `baltic`,
`bay_of_bengal_cp`, `bay_of_bengal_fei`, `beaumont_enterprise_t`,
`beaumont_sunoco_dock`, `borco`, `bosporus_strait`, `braefoot_bay`,
`cape_of_good_hope`, `cogh_to_all_west`, `cogh_to_americas`, `cogh_to_brazil`,
`cogh_to_central_north_americas`, `cogh_to_europe`, `cogh_to_west_africa`,
`corpus_christi_port_polygon`, `cove_point`, `cuba_florida`, `cuba_mexico`,
`europe_north_west`, `freeport_port_polygon`, `gibraltar`, `grangemouth`,
`gulf_of_aden`, `gulf_of_mexico`, `gulf_of_oman`, `houston_port_polygon`,
`india_srilanka_east_large`, `jamnagar_refinery`, `karsto`, `marcus_hook`,
`mongstad`, `nederland_port_polygon`, `nwp_east`, `nwp_west`,
`panama_atlantic_port_polygon`, `panama_pacific_port_polygon`,
`panama_transit_polygon`, `persian-gulf-entry`, `persian_gulf`, `red_sea`,
`sabang`, `savannah`, `singapore`, `steenbank_anchorage`,
`suez_canal_complete`, `terneuzen_dow`, `terneuzen_west`.

Naming is inconsistent and case-sensitive: seven Chinese ports are
`Capitalised`, everything else is lowercase; some use hyphens
(`bab-el-mandeb`, `persian-gulf-entry`) and some underscores
(`cape_of_good_hope`). Resolve, never type from memory.

Two rows are not places at all: `cuba_florida` has `port_name`
*"USGC flow Eur/Med"* and `cuba_mexico` *"USGC flow non west"* — these are
directional flow gates named after geography they are not about. **inferred**
that using them as "Cuba" would be wrong; **not verified** what they enclose.

**The user's word is not the geofence's word** (**index** glossary rows):

| User says | Value |
| --- | --- |
| Hormuz, Strait of Hormuz, Gulf chokepoint | `persian-gulf-entry` (there is **no** "hormuz" literal anywhere) |
| Suez, Suez Canal | `suez_canal_complete` |
| Bab el Mandeb, Bab al-Mandab, Mandeb | `bab-el-mandeb` |
| Cape, COGH, round the Cape | `cape_of_good_hope` (plus six `cogh_to_*` directional zones) |
| Panama | three: `panama_transit_polygon`, `panama_atlantic_port_polygon` (Cristobal), `panama_pacific_port_polygon` (Balboa) |
| Gibraltar, Med exit | `gibraltar` |

### There is no Fujairah geofence

Confirmed twice, independently. **verified** by this map: the 58 names above
contain no Fujairah, no UAE port, and the only `anchorage` is
`steenbank_anchorage` (Netherlands). Independently **verified** by the
package's `entity-dictionary.md` on 2026-08-25 by direct query.

That is why Fujairah is handled as a coordinate box (lat 25.00–25.35 N, lon
56.20–56.60 E) — a recorded workaround for a real data gap, not a routing
style. It is applied against `idle_events_v1r2.START_LATITUDE` /
`START_LONGITUDE`; that table has **no** bare `LATITUDE`/`LONGITUDE` columns
(**UC** confirms: `START_*` and `END_*` pairs only), and a previous version of
that dictionary entry named columns that do not exist and produced
`UNRESOLVED_COLUMN`. **Re-check the 58 names before using the box** — if a
Fujairah geofence is ever added, the box becomes wrong rather than merely
approximate.

---

## 5. `shipping.idle_events_v1r2` — idle periods, not places

**One row is one idle period for one vessel.** 225,844 rows, freshest
`IDLE_START` 2026-08-24 (verified). `IDLE_END` is **never null** — 0.00%
(verified), which differs from the lens's warning that it can be null for an
in-progress period; harmless, but the null-guard is currently a no-op.

Has `VOYAGE_ID` / `VOYAGE_STATUS`, `DRAUGHT_START` / `DRAUGHT_END` /
`DRAUGHT_RATIO` (**UC**), and its **own** vessel classification columns —
`EQ_VESSEL_CLASS`, `EQ_VESSEL_TYPE`, `EQ_VESSEL_TYPE_ALT` — so it needs no
`dim_vessel_latest` join for class at all. Use them; that avoids section 0
entirely. `vessel_idle_periods.md` declares the dangerous join anyway.

**No `GEOFENCE` column.** A "how long did vessels wait at <named place>"
question belongs to section 3, not here. This is the routing rule the lens
INDEX states.

### Disagreement 5 — the index has never heard of this table

**`idle_events_v1r2` is absent from `intelligence.nl2sql_metadata` entirely.**
The index holds **60 rows** covering exactly **10 tables** (verified):
`ais_sampled`, `cargoflow_latest`, `current_vessel_positions_v2r0`,
`dim_vessel_latest`, `geofence_events_latest`, `geofences_v3r1`,
`plant_tracker_capacity`, `plant_tracker_events`,
`silver_forward_curves_metadata_v1`, `silver_forward_curves_ts_v1`.

The `shipping` schema alone has **47** tables (**UC**). So a retrieval-first
agent cannot find `idle_events_v1r2` — the lens file is the only thing that
knows it exists. Filed as **`launch-readiness/86`**.

---

## 6. `shipping.ais_sampled` — raw positions (193.7M rows)

Fresh to today (`YEAR_MONTH_DAY = 20260825`, verified).

**Everything time-like here is a STRING** (**UC**): `DT_POS_UTC`,
`DT_POS_UTC_2H`, `YEAR`, `YEAR_MONTH`, `YEAR_MONTH_DAY` are all `STRING`.
`YEAR`/`YEAR_MONTH`/`YEAR_MONTH_DAY` are the **partition columns** (partition
0/1/2, **UC**). `YEAR_MONTH_DAY` is `yyyyMMdd` — a date comparison against it
is a *lexical* comparison that happens to work because the format sorts, and a
`CAST(... AS DATE)` on it silently fails. The **index** gives the correct
predicate:

```sql
WHERE YEAR_MONTH_DAY >= date_format(current_date() - INTERVAL 30 DAY, 'yyyyMMdd')
```

Filtering on the partition columns is the difference between reading a day and
reading 193 million rows. `vessel_positions.md` states both facts correctly.

It is a **sample**: "how many times did vessel X pass through Y" cannot be
answered exactly from pings. Use section 3 for crossings.

For "where is this vessel now", `current_vessel_positions_v2r0` is the right
table — **index**: *"Latest known position for each vessel ... One row per
vessel."* Given section 0, treat "one row per vessel" as **not verified**.

---

## 7. `balances.plant_tracker_events` — refinery outages

**One row is one *version* of one outage record**, not one outage. 31,858,443
rows; **13,828,267** survive `last_version = true AND invalid = false`
(verified) — **57% of rows are superseded or invalid**. An aggregate without
that filter is more than double-counted. `refinery_outages.md` gets this right
and forbids aggregating without it; it is the single most important line in
that file.

`start_date` and `end_date` are **STRING** (**UC**), and the values carry a
timezone offset: max `start_date` is `2029-12-17 00:00:00.0000000 +00:00`
(verified). So they are neither dates nor plain timestamps — cast explicitly,
and note that string ordering on that format is still lexicographically sound
for `yyyy-MM-dd` prefixes.

**Outages run years into the future** (2029) because planned turnarounds are
scheduled ahead. "Current outages" needs an explicit
`start_date <= now AND (end_date >= now OR end_date IS NULL)`, not a `MAX`.

Two capacity columns, never mixed (**index** + lens): `cap_offline` (absolute)
and `cap_offline_relative` (fraction of plant capacity).

`outage_type` (**index**, real values): `PLANNED` (scheduled turnaround),
`UNPLANNED`, `ECONOMIC` (voluntary, poor margins), `ECONOMIC_LONG_TERM`,
`DE_RATE` (partial), `MAJOR_WORKS`, `NON_OUTAGE_RUN_CUT_DATA` (not an outage at
all — exclude it from outage counts).

`unit_type` (**index**): `CRUDE` is primary distillation; `VACUUM`,
`FLUID CAT-CRACKING`, `HYDROCRACKING-DISTILLATE`, `HYDRODESULF-NAPHTHA`,
`HYDRODESULF-MID-DISTILLATES`, `REFORMING-SR`, `REFORMING-CC`,
`COKING-DELAYED`, `ASPHALT` are secondary/conversion. "Refinery capacity" in
the ordinary sense means `CRUDE`.

**Column case differs from its sibling table**: here it is `Country`,
`Country_Area`, `Plant_Unit_Short_Name` (**UC**); in `plant_tracker_capacity`
it is `country`, `country_area`, `plant_unit_short_name`. Do not copy a
`WHERE` clause between them.

---

## 8. `balances.plant_tracker_capacity` — capacity baseline changes

**One row is one capacity-change record.** 1,643,670 rows; `change_date` is a
real `TIMESTAMP` (**UC**) and runs to 2029-12-15 (verified) — planned
expansions, again future-dated.

`change_status` (**index**): `COMPLETE`, `FIRM`, `UNDER CONSTRUCTION`,
`PROBABLE`, `UNLIKELY`. **An unfiltered `SUM(capacity_change)` adds up
speculative capacity.** The index's own hint is
`WHERE change_status = 'COMPLETE'`. `plant_capacity_changes.md` flags this as
something to check but does not pin the values; they are the five above.

`change_type` (**index**): `OPEN`, `START-UP`, `DECOMMISSION`, `EXPANSION`,
`MOTHBALLED`, `RAMP-UP`, `REDUCTION`, `DEBOTTLENECK`.

Not the same as section 7: this table has no `outage_type` and no
`cap_offline`. It has no `last_version`/`invalid` versioning either (**UC**) —
so the section 7 filter must **not** be copied here; it would fail on missing
columns.

---

## 9. `pricing.silver_forward_curves_*` — prices

Two tables, and the time series is useless alone: `silver_forward_curves_ts_v1`
has exactly three columns — `metadata_id`, `date`, `value` (**UC**). All
context comes from the metadata join on `metadata_id`.

**The `metadata_id` grain is the trap.** `silver_forward_curves_metadata_v1`
has 57,280 rows and **57,280 distinct `metadata_id`** — but only **151 distinct
`curve_name`** (verified). The extra dimension is `applicable_at`, the snapshot
date the curve was *published*: one curve has hundreds of snapshots, each its
own `metadata_id`. Filtering by `curve_name` alone pulls **every historical
snapshot** and averages a curve against its own past revisions.

The **index** is explicit and correct: *"Always filter to `MAX(applicable_at)`
to get the latest curve snapshot. CRITICAL: without this filter you get every
historical curve snapshot."*

```sql
JOIN ...metadata_v1 m ON m.metadata_id = t.metadata_id
WHERE m.curve_name = '...'
  AND m.applicable_at = (SELECT MAX(applicable_at) FROM ...metadata_v1)
```

### Disagreement — `forward_curves.md` is missing `applicable_at` entirely

The lens declares `join_axes: [metadata_id]`, names `is_main_curve` and `unit`,
and says nothing about `applicable_at`. Its stated `resolve_before_filter:
[curve_name, curve_type]` is right as far as it goes, but a query built from
that lens and nothing else returns a multi-snapshot average. Believe the index.
Filed as **`launch-readiness/87`**.

Latest snapshot is `applicable_at = 2026-08-24` (verified) — a one-day lag,
which is what the lens claims. `date` in the ts table runs to 2028-11-01
(verified) and is a **forward delivery date**, not a publication date; future
dates there are correct and expected.

`value` is a level, not a flow — **never `SUM` across dates**
(`forward_curves.md`, correct). `unit` ($/bbl or $/MT) lives only on metadata;
carry it into the answer. `is_main_curve` picks the canonical variant when a
name has several.

**index** count says "~143 curves"; **verified** is 151 distinct `curve_name`.
Minor, but the index's numbers are a snapshot from 2026-08-21, not a live
count.

Curve families (**index**): crude benchmarks (`ICE Brent Fut London`,
`ICE Brent Fut Sing`, `CME WTI`, `Dubai Sing`), freight (`TD3 Forward
Freight`, `TD20`, `TD22`, `TD25`), naphtha (`TFS Naptha London`,
`TFS Naptha MOPJ`, `Naptha vs Dubai`), differentials (`ESPO vs Brent FOB`,
`Mars land China vs Brent`), fuel oil (`TP FO 180`, `FO180 vs Dubai`).

**Spelling trap** (**index** glossary): cargoflow spells it **Naphtha**;
pricing curve names spell it **Naptha**. Same product, two spellings, and a
`=` filter written from the wrong table finds nothing.

---

## 10. Vessel classification — four schemes, and which to use

This is where a reader guesses. There are four, on three tables (**UC** for
existence, **index** for values):

| Scheme | Lives on | Values | Use when |
| --- | --- | --- | --- |
| `eq_vessel_class` | `dim_vessel_latest` | VLCC, Suezmax, Aframax, Panamax, MR2, MR1, LGC, MGC, Tanker, Cargo, Passenger, Coastal (Oil), Fishing, Other, Spare | **The canonical one.** Any analytical question about size class |
| `eq_vessel_class_alt` | `dim_vessel_latest` | Handymax/MR2, Handysize/MR1, Aframax/LR2, Panamax/LR1, Suezmax/LR3, VLCC, Specialised, Other | The user says "LR2" or "MR" and means the clean-product name |
| `vessel_class` / `vessel_class_alternative` / `vessel_type` | `cargoflow_latest` | `vessel_class_alternative`: Handymax/MR2, Handysize/MR1, Aframax/LR2, VLCC, Panamax/LR1, Suezmax/LR3, Specialised, Other. `vessel_type`: Oil Tankers, LPG Carriers, LNG Carriers | **Prefer these for any cargoflow question** — same vocabulary as `_alt`, already on the row, no join, no section-0 fan-out |
| `VESSEL_TYPE` / `VESSEL_TYPE_MAIN` / `VESSEL_TYPE_SUB` | `geofence_events_latest` | Tanker, Crude Oil Tanker, Oil/Chemical Tanker, LPG Tanker, LNG Tanker, Container Ship, Bulk Carrier, Cargo, Passenger | Raw AIS type. Finer than the Equinor scheme but **different axis** — a *type*, not a size class. Already on the row |
| `EQ_VESSEL_CLASS` / `EQ_VESSEL_TYPE` / `EQ_VESSEL_TYPE_ALT` | `idle_events_v1r2` | as `dim_vessel_latest` | Already on the row — use these, not a join |

**The rule that follows from section 0: if the fact table already carries a
class column, use it and do not join `dim_vessel_latest`.** Three of the four
fact tables do. Only `ais_sampled` lacks one, and it carries `VESSEL_NAME`.

`eq_vessel_class` and `eq_vessel_class_alt` are not interchangeable — `VLCC` is
`VLCC` in both, but `MR1` is `Handysize/MR1` in the alt scheme, so an `IN` list
written for one returns nothing against the other. `eq_vessel_class_alt` is
**empty string, not null**, for unclassified vessels (**index**).

**There is no ULCC.** (**index**, stated twice, emphatically.) A question about
Ultra Large Crude Carriers must be answered "this data has VLCC as its largest
class", not silently mapped to VLCC.

Size glossary (**index**): VLCC ~300,000 DWT (~2M bbl); Suezmax ~160,000 DWT
(= LR3); Aframax ~100–120,000 DWT (= LR2).

---

## 11. Traps, with their evidence

1. **`load_alternative_region` / `unload_alternative_region` are
   semicolon-separated multi-value strings.** (**index**, marked CRITICAL, with
   `predicate_shape: LIKE`.) A real value: `"OPEC+; West of Hormuz; East of
   Suez; OPEC; OPEC + Russia"`. `=` is always wrong; use `LIKE '%West of
   Hormuz%'`. Tags include OPEC/Non-OPEC, East/West of Suez, East/West of
   Hormuz, Far East, OECD, PADD 1–5, ARA Region, EU. This is the *only*
   cargoflow column where `LIKE` is correct rather than a resolution failure —
   and the lens files' blanket `forbidden: LIKE on a resolvable column` does
   not carve out the exception. Filed as **`launch-readiness/88`**.
2. **`YEAR_MONTH_DAY` is a `yyyyMMdd` STRING, not a date** (**UC**), and so are
   `DT_POS_UTC`, `YEAR`, `YEAR_MONTH`. Section 6.
3. **`quantity` has no unit.** Barrels is **inferred** and the supporting
   arithmetic does not reproduce (section 2). Do not print a unit.
4. **No Fujairah geofence** (section 4) — hence the coordinate box, which is a
   documented workaround for one confirmed gap and not a general technique.
5. **`group` is a reserved word** — `` `group` `` (**index**).
6. **`load_port` values carry a country-code suffix** — `'Rotterdam'` does not
   equal `'Rotterdam [NL]'` (**index**). And the index's sample values are a
   top-N sample, so a legitimate port such as `Mongstad [NO]` is absent from
   the samples and triggers a false "not among known values" warning — visible
   in `~/Downloads/openstategraph-trace_3.json`.
7. **String comparison is case-sensitive** in Databricks SQL. Geofence names
   are lowercase except seven Chinese ports; `unit_type` is UPPERCASE;
   countries are Proper-Cased (skills note this; **verified** for geofences).
8. **Both `plant_tracker_*` tables and `cargoflow_latest` contain the future.**
   Sections 2, 7, 8.
9. **This is Databricks SQL** — `LIMIT` not `TOP`, `CURRENT_DATE` not
   `GETDATE()`, backticks not brackets, `datediff(end, start)`. The package's
   `sql-dialect.md` is the reference and is correct.

---

## 12. What is **not** in this warehouse

A question about any of these must be refused or scoped down, never
approximated:

- **Charter rates, freight rates paid, demurrage, TCE, bunker prices.** The
  *only* freight-adjacent data is **forward freight curves** in the pricing
  schema — `TD3 Forward Freight`, `TD20`, `TD22`, `TD25` (**index**). Those are
  forward *route benchmarks*, not what anyone paid. There is no fixture table,
  no charterer, no rate on a cargo movement. Verified by inspecting all 47
  `shipping` and 17 `pricing` table names (**UC**) and by the traces: `charter`
  and `freight` appear zero times across all four.
- **Cargo ownership, counterparty, charterer, operator, shipper, receiver.**
  `cargoflow_latest`'s 34 columns (**UC**) carry no commercial party at all.
- **Vessel physical particulars** — DWT, capacity, build year, flag, owner.
  `dim_vessel_latest` carries only `min_draught` / `max_draught` plus nested
  Vortexa/Kpler/Spire structs (**UC**); their contents are **not verified**.
  A trace shows the agent inventing `vessel_flag`; it does not exist.
- **Spot/assessed prices and realised trades.** Pricing holds *forward curves*
  only. There is no assessment history table and no trade table. The `bronze_*`
  tables (Argus, Platts, ICE, CME, DME, PVM, Baltic, TP ICAP, Tradition) are
  raw vendor feeds — **not verified** what they contain; do not route to them
  without describing them first.
- **Inventory / storage levels.** Nothing in `balances` holds stocks; it holds
  plant capacity, outages, and a US-gasoline EIA balance/forecast family.
- **Emissions, CO2, voyage fuel consumption.**
- **Anything outside the covered commodities** — the warehouse is crude,
  refined products and LPG/LNG shipping. No gas pipelines, no power, no coal,
  no metals.
- **Geographic coverage of `balances`** is US-gasoline-centric outside the two
  `plant_tracker_*` tables, which are global (**index**: sample countries China,
  US, Russia, Japan, India, ...). **inferred** from table names, **not
  verified**.

There is also a **discovery gap** rather than a data gap: the search index
covers 10 tables out of the 85 in the three business schemas. `load_events`,
`v_voyage_events_v1r1`, `trajectories_v2r0`, `draught_stats`,
`average_speed_by_class_by_day`, `area_counts_v1r1`, `hotspot`,
`master_location_v2r0`, `master_vessel_type_v1r1` and the historical
forward-curve pair all exist in **UC** and are invisible to retrieval. None has
been described here — **not verified** what any of them contains. Section 5's
ticket covers this.

---

## 13. How the lens files stand against this map

| Lens | Verdict |
| --- | --- |
| `cargoflow.md` | Grain, dates, the load/unload symmetry and the "no unit" caution are all correct and checkable. **Wrong** on the `dim_vessel_latest` join (§0). Silent on future `load_date` (§2) and on `load_alternative_region` needing `LIKE` (§11.1). `typical_lag_days: 5` is unsourced |
| `geofence_dwell.md` | The same-row dwell rule and the median-with-mean rule are correct and are the best-written parts of the lens set. **Wrong** on `geofences_v3r1` being versioned and on `port_name` fanning out (§4). **Wrong** on the `dim_vessel_latest` join (§0) |
| `vessel_positions.md` | Correct throughout — string dates, partition pruning, sampled-not-complete. Only the `dim_vessel_latest` join is wrong (§0) |
| `vessel_idle_periods.md` | Correct on routing away from named places. The `IDLE_END` null guard is a no-op (0% null). Declares the `dim_vessel_latest` join it does not need, since the table carries its own class columns (§5, §10) |
| `refinery_outages.md` | The strongest file. The `last_version = true AND invalid = false` rule is worth 57% of the rows. Silent on future-dated outages |
| `plant_capacity_changes.md` | Correct to flag `change_status`; does not pin the five values, so the check is easy to skip (§8) |
| `forward_curves.md` | Correct on never summing a price and on `is_main_curve`/`unit`. **Missing `applicable_at`**, which is the actual grain trap (§9) |
| `INDEX.md` | The named-place routing rule is right and is the reason the Fujairah box is scoped as an exception rather than a habit |
| `entity-dictionary.md` | The Fujairah entry is the model to copy: it states what was queried, when, what was found, and that the column names were wrong once |
| `entity-resolution.md`, `sql-dialect.md`, `time-windows.md`, `answering.md` | No disagreement found with anything verified here |
