# Declaring a table: what one row is, and which period it covers

Written 2026-08-29 for whoever owns a data source an OpenStateGraph workflow
reads through a tool — a lens, an MCP server, a warehouse catalogue. It is two
fields long. It exists because two questions a workflow cannot answer for
itself turn a right-looking answer into a wrong one, and both are answerable
only by the table.

> **A count of rows is not a count of things, and a zero is not a measurement
> unless the data reaches the period you asked about.**

---

## The two failures this closes, both measured

**One.** A run answered *"there are 1,454,449 dark vessels"*. The statement was

```sql
SELECT COUNT(*) AS dark_vessels_count FROM sm.area_counts_dark_v1r0 WHERE dark = 1
```

and that number was really returned — so a groundedness check passes it,
correctly. `sm.area_counts_dark_v1r0` is not one row per vessel. Measured
2026-08-29: 2,208,572 rows over 10,096 distinct IMOs, and the honest figure is
`COUNT(DISTINCT imo)` = **6,119**. The published number was ~219× too large.

**Two.** The same workflow, asked about *last month*, answers **"0 dark
vessels"**. The table's `day` column runs `2026-01-01 → 2026-05-12`. A
July filter cannot match a row, so that zero is right by accident, and it is
**indistinguishable from a run that looked and found none.** Its sibling
`sm.area_counts_latest` runs to two days ago, so nothing about the workflow, the
question or the lens hints that one of them has stopped.

Without a declaration the platform can say only the weaker true thing:
*you counted rows — say so, or count the entity.* It cannot say *that number is
219× too large*, and it cannot say *the honest answer is zero and here is why*,
because both need a fact only the table holds.

## The declaration

Two keys, beside whatever a schema-describing tool already returns for the
table:

```yaml
row_key: [geofence, day, imo, dt_last, pos_last]   # one row is one of these
coverage:
  column: day
  min: 2026-01-01
  max: 2026-05-12          # refreshed by the loader, never hand-typed
```

or, in the JSON a tool answers with:

```json
{"table": "sm.area_counts_dark_v1r0",
 "row_key": ["geofence", "day", "imo", "dt_last", "pos_last"],
 "coverage": {"column": "day", "min": "2026-01-01", "max": "2026-05-12"}}
```

A flat spelling is accepted too, for a producer that cannot nest —
`coverage_column`, `coverage_min`, `coverage_max` — and the table may be named
by `table`, `canonical_table`, `table_name` or `name`. That is the whole of the
tolerance; everything else is refused rather than guessed at.

### `row_key` — the columns that identify one row

Not the grain, and not the date axis. `grain: daily` is a sentence about
*when*, and it was already declared for the table above while a row turned out
to be one **position report**: `geofence × day × imo × dt_last × pos_last` is
unique to within one duplicate across 2,208,572 rows, and `geofence × day ×
imo` is not (647,460 distinct combinations).

Its **length** is what a workflow reads. More than one column and a row
provably is not one of anything, so `COUNT(*)` is a count of combinations —
which turns *"a row is a vessel only if this table holds one row per vessel,
and this run never established that"* into a statement of fact and names the
repair. A key of exactly one column says the opposite, and the softer sentence
is kept.

Nothing decides *which* member identifies a vessel. That would be a second
declaration and nobody has made it; a key of length > 1 settles the question on
its own without one.

### `coverage` — the first and last date the table holds

**Both ends or nothing.** A half-declared window cannot answer *"could this
have matched?"* in one direction, and a check that is right about one edge and
silent about the other is the failure this page exists to remove. A window whose
`max` precedes its `min` is dropped rather than reversed.

**Refreshed by whatever loads the table.** A hand-typed date is a claim that
stops being true without telling anybody, which is the same defect one layer up.

## What a workflow does with it

Wire a `guard.check` node with `check: zero_outside_coverage` between the step
that answers and the step that publishes. Four states, and each renders
differently:

| The run filtered on dates, the answer reports none of something, and… | What happens |
| --- | --- |
| the window lies **entirely outside** the declared coverage | **revise** — nothing could have matched; the answer is sent back to say which of the two it means and to name the last date the data holds |
| the window **runs past one end** of the declared coverage | the reader is told the records stop on that date |
| the window sits **inside** the declared coverage | **nothing at all** — the zero is a measurement |
| the table **declares no coverage** | the reader is told that *"none"* here cannot be told apart from *"this data does not reach that period"* |

The third row is the one that decides whether anyone keeps the check. A gate
that fires on a correct answer is a gate people route around, so a zero over a
period the table demonstrably holds passes in silence.

The fourth row is what happens **today**, everywhere, because no table declares
anything yet. That is the point: the honest state is stated rather than
implied, and it stops being stated the moment a table declares.

**The first row has an exit, and it is one literal.** Once the answer names the
last date the declaration states — `2026-05-12`, `May 12, 2026`, `12 May 2026`
— the check is satisfied and says nothing more. It has to be: this repair is
*prose*, so unlike a `COUNT(*)` that becomes a `COUNT(DISTINCT …)`, nothing
about the run changes when the model complies, and a gate that cannot see its
own repair objects until it runs out of attempts and then publishes anyway.
Measured on 2026-08-29 against the live server: the model answered *"The data
for the dark fleet only goes up to May 12, 2026. Therefore there were no
distinct dark vessels recorded from July 1, 2026 to August 1, 2026…"* — a
complete answer — and the gate rejected it twice more. The exit is the declared
date and nothing near it; a hedge with no date in it is not compliance.

**A statement is judged by every table it names**, not the first one after
`FROM`. A live run put the table under suspicion inside an `EXISTS (SELECT 1
FROM …)`, second; a zero out of a join is only as conclusive as its weakest
side, so the most doubtful state among the tables wins.

**A window with no date literal is unknown, not covered.** `WHERE MONTH(day) =
MONTH(DATEADD(MONTH, -1, GETDATE()))` says nothing this check can read, and it
reports nothing rather than guessing what the server's clock says. Lenses that
already forbid `GETDATE`/`DATEADD` get this for free.

`row_counts_in_prose` reads `row_key` on the same rail, and needs no wiring
change to start saying the stronger sentence.

## What the platform will never do

- **Guess a window.** An undeclared table stays undeclared. A fabricated
  coverage window is worse than none: it lets a machine state as fact something
  nobody measured.
- **Read a window out of the rows a statement returned.** The live CPL envelope
  carries a `date_columns` block with `min`/`max` computed over *that result
  set* — a one-row `SELECT TOP 1 *` reports a one-day span. Reading it as
  coverage would turn *"the row I fetched is from one day"* into *"this table
  holds one day"*.
- **Print your declaration at a customer.** `row_key`, the table name and the
  statement are internal. What reaches a reader is a sentence about what the
  answer is worth.

## Where the declaration lives

With the table, in whatever the data source already publishes about it — a
lens's `SCHEMA.yaml`, a catalogue row, a `describe` tool's response. The
workflow reads it off the run's own record: any tool answer carrying the two
marker words is parsed, and a run whose tools declare nothing pays a substring
scan.

**The declaration is the source's and the enforcement is the platform's.** That
split is deliberate and has worked twice before on this codebase: the party that
knows the fact states it once, and the party that would otherwise publish a
wrong number is the one that checks.
