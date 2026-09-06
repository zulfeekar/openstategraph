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

Both are worked here against `workflows/chinook-assistant`'s database, which
ships with this repository, so every figure below is one you can re-run.

**One.** A run answers *"there are 8,715 tracks"*. The statement was

```sql
SELECT COUNT(*) AS track_count FROM main.PlaylistTrack
```

and that number really was returned — so a groundedness check passes it,
correctly. `main.PlaylistTrack` is not one row per track: it is a playlist ×
track junction, 8,715 rows over **3,503** distinct tracks in 14 playlists, and
the honest figure is `COUNT(DISTINCT TrackId)` = 3,503. The published number
was ~2.5× too large.

**Two.** The same workflow, asked about *last month*, answers **"0 invoices"**.
`main.Invoice`'s `InvoiceDate` runs `2009-01-01 → 2013-12-22`. Any recent
filter cannot match a row, so that zero is right by accident, and it is
**indistinguishable from a run that looked and found none.** A sibling table
answers questions about its own period with real rows, so nothing about the
workflow, the question or the lens hints that this one has stopped.

Without a declaration the platform can say only the weaker true thing:
*you counted rows — say so, or count the entity.* It cannot say *that number is
2.5× too large*, and it cannot say *the honest answer is zero and here is why*,
because both need a fact only the table holds.

## The declaration

Two keys, beside whatever a schema-describing tool already returns for the
table:

```yaml
row_key: [CustomerId, InvoiceDate]   # one row is one of these
coverage:
  column: InvoiceDate
  min: 2009-01-01
  max: 2013-12-22          # refreshed by the loader, never hand-typed
```

or, in the JSON a tool answers with:

```json
{"table": "main.Invoice",
 "row_key": ["CustomerId", "InvoiceDate"],
 "coverage": {"column": "InvoiceDate", "min": "2009-01-01", "max": "2013-12-22"}}
```

A flat spelling is accepted too, for a producer that cannot nest —
`coverage_column`, `coverage_min`, `coverage_max` — and the table may be named
by `table`, `canonical_table`, `table_name` or `name`. That is the whole of the
tolerance; everything else is refused rather than guessed at.

### `row_key` — the columns that identify one row

Not the grain, and not the date axis. `grain: daily` is a sentence about
*when*, and a table can declare it while a row turns out to be something else
entirely. `main.PlaylistTrack` is the worked case: `PlaylistId × TrackId` is
unique across all 8,715 rows, and `TrackId` alone is not (3,503 distinct
values).

Its **length** is what a workflow reads. More than one column and a row
provably is not one of anything, so `COUNT(*)` is a count of combinations —
which turns *"a row is a track only if this table holds one row per track, and
this run never established that"* into a statement of fact and names the
repair. A key of exactly one column says the opposite, and the softer sentence
is kept.

Nothing decides *which* member identifies the entity. That would be a second
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
last date the declaration states — `2013-12-22`, `December 22, 2013`,
`22 December 2013` — the check is satisfied and says nothing more. It has to be: this repair is
*prose*, so unlike a `COUNT(*)` that becomes a `COUNT(DISTINCT …)`, nothing
about the run changes when the model complies, and a gate that cannot see its
own repair objects until it runs out of attempts and then publishes anyway.
Measured on 2026-08-29 against a live server: the model answered *"The data
only goes up to <the declared end date>. Therefore there were none recorded in
the period you asked about…"* — a complete answer — and the gate rejected it
twice more. The exit is the declared
date and nothing near it; a hedge with no date in it is not compliance.

**A statement is judged by every table it names**, not the first one after
`FROM`. A live run put the table under suspicion inside an `EXISTS (SELECT 1
FROM …)`, second; a zero out of a join is only as conclusive as its weakest
side, so the most doubtful state among the tables wins.

**A window with no date literal is unknown, not covered.** `WHERE MONTH(InvoiceDate) =
MONTH(DATEADD(MONTH, -1, GETDATE()))` says nothing this check can read, and it
reports nothing rather than guessing what the server's clock says. Lenses that
already forbid `GETDATE`/`DATEADD` get this for free.

`row_counts_in_prose` reads `row_key` on the same rail, and needs no wiring
change to start saying the stronger sentence.

## What the platform will never do

- **Guess a window.** An undeclared table stays undeclared. A fabricated
  coverage window is worse than none: it lets a machine state as fact something
  nobody measured.
- **Read a window out of the rows a statement returned.** A live MCP envelope
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
