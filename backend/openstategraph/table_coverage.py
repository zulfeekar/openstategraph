"""What one row is, and which period a table covers — read from a declaration.

`launch-readiness/166`, the half `165` could not build.

`165` shipped everything the platform can know **without a declaration**: a
bare `COUNT(*)` counts rows, so publishing that figure under a plural entity
noun is asked to say what it counted. Two things stayed out of reach, and both
are facts only the table can state:

1. **What one row is.** A declaration saying `grain: daily` is a word about
   the *date* axis and not a key. `main.PlaylistTrack` is the worked case: its
   row is `(PlaylistId, TrackId)`, so a row is one track *in one playlist* and
   never one track.
2. **What the table covers.** `workflows/chinook-assistant`'s database ships
   with this repository, so the second fact is one anybody can re-measure:
   `main.Invoice` runs `2009-01-01 -> 2013-12-22`, and `main.PlaylistTrack`
   carries no date column at all.

So *"last month"* over `main.Invoice` is guaranteed empty, and every run that
answers *"0 invoices"* is right by accident and reads **identically** to a run
that looked and found none. That is this project's most expensive shape, and
it is the whole of the ticket.

## The declaration is the lens's, and the enforcement is ours

The same split `87` and `98` took and both worked. This module does not guess a
coverage window and never will: a fabricated one is worse than none, because it
would let the platform state as fact something nobody measured. What it does is
**read** one when a table publishes it, and **say so when a table does not**.

The wire format is deliberately the shape a schema-describing tool already
returns — a payload that names a table, carrying `row_key` and `coverage`
beside the columns:

```json
{"table": "main.Invoice",
 "row_key": ["CustomerId", "InvoiceDate"],
 "coverage": {"column": "InvoiceDate", "min": "2009-01-01", "max": "2013-12-22"}}
```

`docs/declaring-a-table.md` is the publication of that contract.

## Four states, and no toggle between them

`launch-readiness/135`'s resolver established the shape and this reuses it: the
failure being closed is *two situations rendering identically*, so every state
gets its own rendering and none of them is silence-by-omission.

| The run filtered on dates and the answer reports none, and… | State | What happens |
| --- | --- | --- |
| the window lies entirely outside the declared coverage | `outside` | **revise** — nothing could have matched, and the answer must say so |
| the window runs past one end of the declared coverage | `partial` | a reader disclosure naming the last date the data holds |
| the window sits inside the declared coverage | `covered` | **silence** — the zero is a measurement, and saying anything here is the `133` failure |
| the table declares no coverage at all | `undeclared` | a reader disclosure: *"none" cannot be told apart from "not covered"* |

The **`covered` row is the one that decides whether anyone keeps this gate.**
`launch-readiness/133` is the counter-example already paid for: a check that
fires on correct work teaches people to route around it. A zero over a window
the table demonstrably holds is a real answer and this module has nothing to
say about it.

## Why `outside` revises and the other two disclose

`outside` is **correctable in one lap and by the model only**: the sentence a
reader needs — *"none, and none was possible: this data stops on 2013-12-22"* —
is prose about the question that was asked, and the model is the thing holding
that question. `165`'s repair has the same shape.

`undeclared` and `partial` are **not correctable at all.** No revision lap can
make a table declare something, so routing them to `revise` would build a guard
that objects forever and then publishes anyway — which is `launch-readiness/167`
in person. They travel the reader rail instead
(`abc/tool_notes.UncoveredWindow`), which renders whether or not the model
mentions them.

## What this module will not do

- **It will not fabricate a window.** An undeclared table is reported as
  undeclared, forever, until somebody measures it and writes it down.
- **It will not read a coverage window out of returned rows.** A live MCP
  envelope carries a `date_columns` block with `min`/`max` — computed over the
  rows *this statement returned*, not over the table. Reading it as coverage
  would turn *"the sample I fetched spans one day"* into *"this table holds one
  day"*, which is a confident wrong answer where the honest one is "undeclared".
- **It will not decide which column identifies the entity.** A `row_key` of more
  than one column is enough to know a row is not one of anything; naming which
  member is the entity is a second declaration nobody has made.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping

from openstategraph.counted_rows import ROW_NOUNS, exchanges_in, payloads_of

#: An ISO date, the only spelling this module reads. A declaration is written
#: by a loader rather than typed by a person, so tolerating `12/05/2026` would
#: buy an ambiguity (`launch-readiness/125`'s axis problem in miniature: two
#: readings, one string) for no reader.
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")

#: A quoted date literal inside a statement — how a run says which period it
#: asked about. Anything else (a bound parameter, `DATEADD`, a relative
#: expression) leaves the window unknown, and unknown is reported as such
#: rather than assumed to be covered.
_DATE_LITERAL = re.compile(r"'(\d{4}-\d{2}-\d{2})(?:[T ][\d:.]+)?'")

#: Plural words that stand between *"no"* and the thing actually being counted.
#: *"no recorded **instances** of dark vessels"* is about vessels, and a
#: disclosure naming `instances` reads as though the machine did not follow the
#: sentence. Walked **past**, not stopped at — unlike `ROW_NOUNS` below.
_VAGUE: frozenset[str] = frozenset(
    {
        "results", "matches", "hits", "instances", "occurrences", "values",
        "changes", "issues", "problems", "errors", "details", "others",
        "dates", "days", "months", "years", "times", "cases", "columns",
        "tables", "sightings",
    }
)

#: How far past *"no"* to look for the noun it denies. Six rather than `165`'s
#: four, because the vague words above sit **between** the two: *"no recorded
#: instances of dark vessels"* is five words from `no` to `vessels`.
_ENTITY_WINDOW = 6

_WORD = re.compile(r"[A-Za-z][A-Za-z-]*")

#: English words ending in `s` that are not nouns. `165` keeps its own copy for
#: its own window; this one is reached by a different walk and the two lists
#: answer different questions, so they are not shared.
_NOT_A_NOUN: frozenset[str] = frozenset(
    {
        "was", "is", "has", "does", "as", "its", "this", "thus", "us", "plus",
        "less", "across", "whereas", "yes", "also", "always", "perhaps",
        "series", "various", "hers", "theirs", "ours", "yours", "gas",
    }
)

#: The words that open a claim of nothing. `none` is here and earns almost
#: nothing on its own — *"I found none."* attaches no noun, so it is read and
#: then dropped by the plural-noun rule below. That is a known miss, recorded
#: rather than patched: widening it to a bare `none` would fire on *"none of
#: the ports is in Norway"*, which is a claim about a subset and not a zero.
_NOTHING = re.compile(r"\b(?:no|zero|none|0)\b", re.IGNORECASE)

#: How deep to look for a declaration inside a nested payload. A lens's
#: schema dump nests one or two levels (`data.tables[]`); past this it is not a
#: declaration, it is somebody's data.
_MAX_DEPTH = 6

#: The cheapest possible way to not parse a result. A tool answer that contains
#: neither word cannot carry a declaration, and every run pays this scan.
_MARKERS: tuple[str, ...] = ("row_key", "coverage")


@dataclass(frozen=True)
class TableDeclaration:
    """What a table says about itself. Everything here is somebody's statement.

    Nothing on this record is inferred, measured or defaulted by the platform.
    A field that was not declared is empty, and empty is reported as
    *undeclared* rather than filled in — which is the single property that
    stops this module from ever being the source of a confident wrong answer.
    """

    #: The table this is about, as the statement spells it. Compared casefolded.
    table: str
    #: The columns that together identify one row. Its **length** is what the
    #: platform reads: more than one column and a row is not one of anything.
    row_key: tuple[str, ...] = field(default=())
    #: The date column the window below is measured on.
    coverage_column: str = ""
    #: The first and last date the table holds. `None` is *not declared* — never
    #: "unbounded", which would be a claim.
    coverage_min: date | None = None
    coverage_max: date | None = None

    def declares_row_key(self) -> bool:
        return bool(self.row_key)

    def declares_coverage(self) -> bool:
        """Both ends, or nothing.

        A half-declared window cannot answer *"could this have matched"* in one
        direction, and a check that is right about one edge and silent about the
        other is the shape this ticket exists to remove.
        """
        return self.coverage_min is not None and self.coverage_max is not None

    def a_row_is_not_one_thing(self) -> bool:
        """Whether the declaration itself says `COUNT(*)` is not a count of entities."""
        return len(self.row_key) > 1


def _iso(value: Any) -> date | None:
    text = str(value or "").strip()
    if not _ISO.match(text):
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _row_key(value: Any) -> tuple[str, ...]:
    """A declared row key, read tolerantly.

    A list is the wire format; a comma-separated string is what a YAML author
    writes by hand often enough that refusing it would lose a real declaration
    to punctuation.
    """
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = [str(part).strip() for part in value]
    else:
        return ()
    return tuple(part for part in parts if part)


def declaration_in(payload: Any) -> TableDeclaration | None:
    """One mapping read as a declaration, or `None`.

    **Tolerant in reading, strict in trusting** — CLAUDE.md's rule, and both
    halves are load-bearing here. Three spellings of the table's name are
    accepted because a schema payload, a lens registry and a hand-written YAML
    each pick a different one. But a payload contributes a declaration only
    when it names a table **and** carries at least one of the two declarations
    in a shape that parses: a mapping with a `coverage` key holding prose, or
    dates that are not dates, declares nothing, and *declares nothing* is a
    state this module renders rather than swallows.
    """
    if not isinstance(payload, Mapping):
        return None
    table = ""
    for key in ("table", "canonical_table", "table_name", "name"):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            table = candidate.strip()
            break
    if not table:
        return None

    row_key = _row_key(payload.get("row_key"))

    coverage = payload.get("coverage")
    column, low, high = "", None, None
    if isinstance(coverage, Mapping):
        column = str(coverage.get("column") or "").strip()
        low = _iso(coverage.get("min"))
        high = _iso(coverage.get("max"))
    else:
        # The flat spelling, for a producer that cannot nest — a CSV catalogue,
        # a registry row. Same three fields, same meaning, no second contract.
        column = str(payload.get("coverage_column") or "").strip()
        low = _iso(payload.get("coverage_min"))
        high = _iso(payload.get("coverage_max"))

    if low is not None and high is not None and low > high:
        # A window that ends before it starts is not a narrower claim, it is a
        # broken one. Dropped rather than reversed: reversing would publish a
        # window nobody declared.
        low, high = None, None

    if not row_key and (low is None or high is None):
        return None
    return TableDeclaration(
        table=table,
        row_key=row_key,
        coverage_column=column,
        coverage_min=low,
        coverage_max=high,
    )


def declarations_in_result(result: Any) -> list[TableDeclaration]:
    """Every declaration carried anywhere in one tool answer.

    The three envelope layers `165` measured are undone by `payloads_of`; from
    there this walks the structure, because a lens's bulk schema dump puts one
    entry per table under a list and a single-table describe puts it at the
    top. Bounded in depth, and prefiltered on the two marker words so a run
    whose tools declare nothing pays a substring scan and not a parse.
    """
    text = str(result or "")
    if not any(marker in text for marker in _MARKERS):
        return []
    found: list[TableDeclaration] = []
    seen: set[str] = set()

    def walk(node: Any, depth: int) -> None:
        if depth > _MAX_DEPTH:
            return
        if isinstance(node, Mapping):
            declaration = declaration_in(node)
            if declaration is not None and declaration.table.casefold() not in seen:
                seen.add(declaration.table.casefold())
                found.append(declaration)
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, depth + 1)

    for payload in payloads_of(text):
        walk(payload, 0)
    return found


def declarations_in(state: Mapping[str, Any]) -> dict[str, TableDeclaration]:
    """Every table declaration this run was given, keyed by casefolded table name.

    Two rails, the same pair `counted_rows.exchanges_in` reads and for the same
    reason: `_agent` returns no messages, so what an agent's loop was told sits
    on `tool_use[node]["declares"]` (written by `tool_report`) and nowhere else.
    """
    found: dict[str, TableDeclaration] = {}

    def add(declaration: TableDeclaration | None) -> None:
        if declaration is None:
            return
        found.setdefault(declaration.table.casefold(), declaration)

    for row in (state.get("tool_use") or {}).values():
        for payload in (row or {}).get("declares") or []:
            add(declaration_in(payload))

    for message in state.get("messages") or []:
        if getattr(message, "type", "") != "tool":
            continue
        if getattr(message, "status", None) == "error":
            continue
        for declaration in declarations_in_result(getattr(message, "content", "")):
            add(declaration)
    return found


def window_of(sql: str) -> tuple[date | None, date | None]:
    """The period one statement asked about, or `(None, None)`.

    Read from the quoted date literals in the statement, lowest and highest —
    not from which column they were compared against, and not from the operator.
    Parsing `>=` against `<` correctly would need a SQL parser, and the two
    facts this module needs (*does the window start after the data stops*,
    *does it end before the data starts*) are answerable from the extremes
    alone.

    A statement with no date literal has an **unknown** window, not an
    unfiltered one — a bound parameter and a relative expression both land
    here — and unknown is reported as such by every caller.
    """
    dates: set[date] = set()
    for match in _DATE_LITERAL.finditer(str(sql or "")):
        parsed = _iso(match.group(1))
        if parsed is not None:
            dates.add(parsed)
    if not dates:
        return (None, None)
    found = sorted(dates)
    return (found[0], found[-1])


#: The four states, named once so a test, a caller and a document enumerate the
#: same set. `unknown` is the fifth thing that can happen and is deliberately
#: not one of them: it means this module was never in a position to ask.
COVERAGE_STATES: tuple[str, ...] = ("covered", "partial", "outside", "undeclared")

#: How much doubt each state carries, for a statement that names several
#: tables. `undeclared` outranks `covered` deliberately: one table covering the
#: window says nothing about the one beside it that has never said what it
#: holds, and a zero out of a join is only as conclusive as its weakest side.
_SEVERITY: dict[str, int] = {"covered": 0, "undeclared": 1, "partial": 2, "outside": 3}


def assess(
    window: tuple[date | None, date | None], declaration: TableDeclaration | None
) -> str:
    """Which of the four states this statement's window is in, or `""`.

    `""` — *unknown* — whenever there is no window to judge. A statement with
    no date literal is not evidence of anything either way, and reporting it as
    `undeclared` would put a disclosure on every run that never asked about a
    period at all.
    """
    start, end = window
    if start is None or end is None:
        return ""
    if declaration is None or not declaration.declares_coverage():
        return "undeclared"
    low = declaration.coverage_min
    high = declaration.coverage_max
    assert low is not None and high is not None  # declares_coverage
    if start > high or end < low:
        return "outside"
    if start < low or end > high:
        return "partial"
    return "covered"


def _is_a_code(prose: str, start: int, end: int) -> bool:
    """Whether this `no` is a bracketed token rather than the English word.

    **Found live, on the first real run** (2026-08-29, the owner's own
    question): the answer listed *"Biodiesel: 32,759 barrels to Floro [NO]"*,
    and `[NO]` is Norway. Three country codes matched, and the disclosure named
    *"no barrels and instances"* — a sentence about nothing, attached to a
    breakdown that was correct. `133` exactly, and it took one live run to
    find and no fixture to have missed.

    A token wrapped in brackets or parentheses is a code, never prose.
    """
    before = prose[:start].rstrip()
    after = prose[end:].lstrip()
    return bool(before[-1:] in "[(" and after[:1] in ")]")


def entity_after(prose: str, end: int) -> str:
    """The plural entity noun a *"no"* denies, or `""`.

    `165`'s `label_after` answers a neighbouring question — *what noun is this
    number presented as counting* — and stops at the first plural word. This
    one **walks past** the vague count-words that sit between a denial and its
    subject, which is the difference between disclosing about `instances` and
    disclosing about `vessels`.

    A row-noun still wins outright and silences the whole claim, for `165`'s
    reason: *"the query returned no rows"* is a sentence about the record, and
    a disclosure about what the data covers is not what a reader of it needs.
    """
    words: list[str] = []
    for match in _WORD.finditer(prose, end):
        words.append(match.group())
        if len(words) >= _ENTITY_WINDOW:
            break
        if prose[match.end() : match.end() + 1] in ".;:!?":
            break
    for word in (candidate.lower() for candidate in words):
        if word in ROW_NOUNS:
            return ""
        if word in _VAGUE or word in _NOT_A_NOUN:
            continue
        if len(word) >= 4 and word.endswith("s"):
            return word
    return ""


def nothing_claims_in(prose: str) -> list[str]:
    """The plural entity nouns this answer reports **none** of."""
    found: list[str] = []
    for match in _NOTHING.finditer(prose or ""):
        if _is_a_code(prose or "", match.start(), match.end()):
            continue
        label = entity_after(prose or "", match.end())
        if not label or label in found:
            continue
        found.append(label)
    return found


#: Month names, for the spellings a model actually writes. `165`'s lesson about
#: parsers applies here in reverse: the prompt asked for *"the last date the
#: data holds"* and the model answered *"May 12, 2026"*, which no ISO matcher
#: would have recognised. Suspect the parser.
_MONTHS: tuple[str, ...] = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def states_the_date(prose: str, day: date) -> bool:
    """Whether this answer names that exact date, in any ordinary spelling.

    **The check's own exit, and it is deterministic.** `165`'s repair changes
    the SQL or the noun, so its check simply goes quiet; this one asks for
    *prose*, and a gate that cannot see its own repair objects forever — which
    is `launch-readiness/167` built on purpose rather than met by accident.
    Observed live on 2026-08-29: the model complied fully — *"The data for the
    dark fleet only goes up to May 12, 2026"* — and the guard rejected it twice
    more and exhausted.

    This is not *"did the model comply"* read as sentiment, which is what
    `Grader.normalise` warns against. It is one literal the check itself
    supplied, matched exactly: the last date the declaration states. An answer
    naming it has said the one thing that distinguishes *"none"* from *"this
    data does not reach that period"*, which is the whole of what was asked.

    Ambiguous numeric spellings (`12/05/2026`) are deliberately not read: two
    readings of one string is the defect this map is named for.
    """
    text = str(prose or "").lower()
    if day.isoformat() in text:
        return True
    month = _MONTHS[day.month - 1]
    year = day.year
    return any(
        pattern in text
        for pattern in (
            f"{month} {day.day}, {year}",
            f"{month} {day.day} {year}",
            f"{day.day} {month} {year}",
            f"{day.day} {month}, {year}",
        )
    )


def coverage_findings(
    candidate: str, state: Mapping[str, Any]
) -> tuple[list[tuple[str, str, TableDeclaration | None, tuple[date | None, date | None]]], list[str]]:
    """`(findings, subjects)` — what each date-filtered statement was, and of what the answer reports none.

    Split out from the check so both the revise reason and the reader
    disclosure are computed from one reading of the run, rather than from two
    that can disagree about which statement they mean.
    """
    from openstategraph.counted_rows import tables_in

    subjects = nothing_claims_in(candidate)
    if not subjects:
        return ([], [])
    declarations = declarations_in(state)
    findings: list[tuple[str, str, TableDeclaration | None, tuple[date | None, date | None]]] = []
    for sql, _result in exchanges_in(state):
        window = window_of(sql)
        if window == (None, None):
            continue
        # **Every table the statement names**, and the worst answer wins. A
        # join reaches two tables and a zero could have come from either, so
        # reading only the first `FROM` would clear a statement on the strength
        # of the table that happened to be written first — observed on a live
        # run (2026-08-29) whose statement had the shape `FROM main.Invoice
        # ... EXISTS (SELECT 1 FROM main.PlaylistTrack …)`, putting the suspect
        # table second.
        best: tuple[str, str, TableDeclaration | None] | None = None
        for table in tables_in(sql) or [""]:
            declaration = declarations.get(table.casefold())
            state_name = assess(window, declaration)
            if not state_name:
                continue
            if best is None or _SEVERITY[state_name] > _SEVERITY[best[0]]:
                best = (state_name, table, declaration)
        if best is None:
            continue
        findings.append((best[0], best[1], best[2], window))
    return (findings, subjects)


def _english(values: Iterable[str]) -> str:
    items = [value for value in values if value]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def check_zero_outside_coverage(
    candidate: str, state: Mapping[str, Any], model_authored: Iterable[str]
) -> str:
    """`guard.check`'s coverage gate: empty is a pass, text is the revise reason.

    Fires on one situation only — the answer reports **none** of something, and
    a statement this run executed asked about a period the table it read
    **declares** it does not hold. Then a zero is not a measurement and the
    answer must say which of the two it means.

    Everything else is a pass, and two of those passes are not silent: an
    undeclared table and a window running past the end of a declared one both
    put a sentence on the reader rail (`abc/tool_notes.UncoveredWindow`),
    because no revision lap can repair either and a guard that objects forever
    and then publishes is `launch-readiness/167`.

    `model_authored` is accepted and unused, as it is on
    `check_row_counts_in_prose`: it is part of the built-in check signature
    because `numbers_in_prose` needs to know whose text is evidence, and this
    check reads tool calls, which are nobody's draft.
    """
    from openstategraph.abc.tool_notes import UncoveredWindow, record_notes

    findings, subjects = coverage_findings(candidate, state)
    if not findings:
        return ""
    subject = _english(subjects)

    outside = [entry for entry in findings if entry[0] == "outside"]
    if outside:
        _state_name, table, declaration, window = outside[0]
        assert declaration is not None and declaration.coverage_max is not None
        if states_the_date(candidate, declaration.coverage_max):
            # The answer has said it. See `states_the_date` — this is the
            # check's own exit, and without it the gate objects forever.
            return ""
        return (
            f"The answer reports no {subject}. Every date this run filtered on lies "
            f"outside what {table or 'that table'} declares it holds: the statement asked "
            f"about {window[0]} to {window[1]}, and the table's declared coverage is "
            f"{declaration.coverage_min} to {declaration.coverage_max}. No row could have "
            "matched, so this zero is not a measurement. Say which of the two it is — "
            "that nothing was found, or that this data does not reach the period asked "
            "about — and name the last date the data holds."
        )

    notes: list[Any] = []
    for state_name, table, declaration, window in findings:
        if state_name == "partial" and declaration is not None:
            notes.append(
                UncoveredWindow(
                    subject=subject,
                    table=table,
                    declared_max=str(declaration.coverage_max or ""),
                )
            )
        elif state_name == "undeclared":
            notes.append(UncoveredWindow(subject=subject, table=table))
    if notes:
        record_notes(notes)
    return ""


__all__ = [
    "COVERAGE_STATES",
    "TableDeclaration",
    "assess",
    "check_zero_outside_coverage",
    "coverage_findings",
    "declaration_in",
    "declarations_in",
    "declarations_in_result",
    "nothing_claims_in",
    "states_the_date",
    "window_of",
]
