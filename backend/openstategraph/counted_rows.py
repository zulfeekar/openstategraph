"""A bare `COUNT(*)` counts rows. Publishing it as a count of things is a claim.

`launch-readiness/165`. A run published a bare `COUNT(*)` under a plural
entity noun. The same defect is reachable against
`workflows/chinook-assistant`'s database, which ships with this repository, so
the worked example below is one anybody can re-run:

    SELECT COUNT(*) AS track_count FROM main.PlaylistTrack

answers **8,715**, and `main.PlaylistTrack` is a playlist x track junction —
8,715 rows over **3,503** distinct tracks in 14 playlists. Published as a
count of tracks that figure is about 2.5x too large, stated with a confident
gloss, and no gate on the path had anything to say about it.

## Why this is not `151`, in one sentence

`8,715` **was** retrieved — the query really returned it — so
`numbers_in_prose` finds it grounded and passes, correctly. `151` checks a
number's **provenance**; here the provenance is impeccable and the **meaning**
is wrong. Its compile-time half, `UNDECLARED_FALLBACK`, is silent for an
equally correct reason: the tools in question declare `open_world = False`
because they *are* the run's store.

## What this module knows, and what it refuses to guess

It knows one thing, and it is SQL semantics rather than schema knowledge, so it
needs no declaration from anybody: **`SELECT COUNT(*) FROM t` returns a number
of rows of `t`.** Whether a row of `t` happens to be one track is a property
only `t` can declare, and nothing in this repository can see that declaration
for a table behind an MCP server.

So the check never says *"that number is wrong"* — it could not know. It says
**"you counted rows; say so, or count the entity"**, and both repairs are one
revision lap away:

- `COUNT(DISTINCT TrackId)` — after which this module is silent, because the
  statement is no longer a row count;
- *"8,715 rows"* — after which this module is silent, because the answer
  now says what it counted.

That is the ticket's own *"either not published, or published with what it
actually counted"*.

## The narrowness, which is the half that decides whether anyone keeps it

`launch-readiness/133` is the counter-example this project already paid for: a
check that reported success on a wrong query, and a gate that fires on a
legitimate query teaches people to route around it. *"How many rows are in this
table"* is a real question with a real `COUNT(*)` behind it. Three conjuncts
must all hold before a word is said:

1. the run executed a statement that counts **only** rows — a bare `COUNT(*)`
   or `COUNT(1)`, with no `DISTINCT` **anywhere** in it and no `GROUP BY`;
2. a number that statement returned appears in the answer, as a quantity by
   `grounded_numbers.quantities_in`'s own candidate rule;
3. the answer attaches a **plural entity noun** to it that is not a row-noun.

Anything else is silent, including a number with no noun after it.

**What it cannot see, stated so nobody rediscovers it as a bug.** A table that
genuinely holds one row per entity — `main.Track` — is reported too,
because this module cannot tell it apart from the fan-out table without the
declaration that does not exist. That is a known cost, and it is bounded: the
repair it asks for (`COUNT(DISTINCT TrackId)`) is correct on such a table as well
and makes the answer strictly more defensible. Turning "reported" into "wrong"
needs the table to declare its row key, which is `docs-and-gaps/16`'s and
`125`'s territory and is filed as `launch-readiness/166`.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Iterable, Mapping

import json

from openstategraph.grounded_numbers import numbers_in, quantities_in

#: A count of rows and nothing else. `COUNT(*)` and `COUNT(1)` are one
#: statement spelled two ways; every engine treats them identically.
_BARE_COUNT = re.compile(r"\bcount\s*\(\s*(?:\*|1)\s*\)", re.IGNORECASE)

#: `DISTINCT` **anywhere** takes a statement out of reach — inside the count,
#: in the projection, or in a subquery this module will not parse. Tolerant in
#: reading, strict in trusting: the cost of being wrong here is a false report
#: on a correct query, which is the failure `133` names.
_DISTINCT = re.compile(r"\bdistinct\b", re.IGNORECASE)

#: A grouped count is a breakdown. Its numbers are per-group row counts and a
#: reader meets them as a table, not as a headline figure.
_GROUP_BY = re.compile(r"\bgroup\s+by\b", re.IGNORECASE)

_FROM = re.compile(r"\bfrom\s+([A-Za-z_][\w.]*)", re.IGNORECASE)

#: Words that already say "row". An answer using one of these has done exactly
#: what this check asks for, and must never be reported.
ROW_NOUNS: frozenset[str] = frozenset(
    {
        "row", "rows",
        "record", "records",
        "entry", "entries",
        "line", "lines",
        "observation", "observations",
        "measurement", "measurements",
        "reading", "readings",
        "datapoint", "datapoints",
        "count", "counts",
    }
)

#: English words that end in `s` and are not nouns. Without these, *"1,454,449
#: was the figure"* reports `was` as the entity being counted.
_NOT_A_NOUN: frozenset[str] = frozenset(
    {
        "was", "is", "has", "does", "as", "its", "this", "thus", "us", "plus",
        "less", "across", "whereas", "yes", "also", "always", "perhaps",
        "series", "various", "hers", "theirs", "ours", "yours", "gas",
    }
)

#: How far past the number to look for the noun it labels. Four words covers
#: *"8,715 distinct tracks"* and *"8,715 playlist track rows"* and stops
#: well before the next clause.
_WINDOW = 4

_WORD = re.compile(r"[A-Za-z][A-Za-z-]*")


def counts_rows_only(sql: str) -> bool:
    """Whether this statement's answer is a number of rows and nothing else."""
    text = str(sql or "")
    if not _BARE_COUNT.search(text):
        return False
    if _DISTINCT.search(text) or _GROUP_BY.search(text):
        return False
    return True


#: Keys a tool wraps its rows in, most specific first. Their siblings are the
#: **envelope** — `row_count`, `request_id`, `truncated`, a `digest` note — and
#: reading the envelope's own numbers as results is how the first wired live
#: run reported *"1 ports"* off a `row_count: 1` and a handful of small numbers
#: off a hex `request_id`. `133`'s trap exactly: three of that gate's five
#: lines were true and two were noise, and a reader stops at the second.
_ROW_KEYS: tuple[str, ...] = ("sample_rows", "rows", "records", "results")

#: A result envelope that says the call did not succeed. Its numbers are a
#: request id and an error code, and none of them is data. Read from the
#: payload rather than from `ToolMessage.status`, because an MCP tool reports
#: its own refusals as an ordinary successful message — every `lock_violation`
#: this run produced arrived with `status` unset.
_OK = "ok"

#: Past this, the content is not an envelope anybody is going to parse, and
#: `ast.literal_eval` on it is a cost with no answer at the end.
_PARSE_CAP = 200_000


def payloads_of(result: str) -> list[Any]:
    """Whatever structured objects this tool answer actually carries.

    Three layers are live in one string on the measured MCP path, and reading
    tolerantly means undoing all three rather than assuming any one of them:

    1. LangChain hands back a **Python repr** of its content blocks —
       `[{'type': 'text', 'text': '...', 'id': '...'}]` — which is not JSON
       and which `json.loads` refuses;
    2. each block's `text` is a JSON document;
    3. that document wraps its rows under `data`.

    Anything unrecognised is returned as itself, so a CSV block, a Markdown
    table or a bare scalar passes through untouched.
    """
    import ast

    text = str(result or "").strip()
    if not text or len(text) > _PARSE_CAP:
        return [text]
    blocks: list[str] = []
    if text[:1] in "[{":
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            parsed = None
        candidates = parsed if isinstance(parsed, list) else [parsed]
        for block in candidates:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                blocks.append(block["text"])
    if not blocks:
        blocks = [text]
    found: list[Any] = []
    for block in blocks:
        try:
            found.append(json.loads(block))
        except (ValueError, TypeError):
            found.append(block)
    return found


def cells_of(result: str) -> str:
    """The part of a tool's answer that is data rather than envelope.

    Tolerant in reading, strict in trusting: narrowing is applied only to a
    shape that was positively recognised, and a payload that declares itself
    unsuccessful contributes nothing at all.
    """
    parts: list[str] = []
    for payload in payloads_of(result):
        if not isinstance(payload, dict):
            parts.append(str(payload))
            continue
        if payload.get(_OK) is False:
            continue
        body = payload.get("data")
        body = body if isinstance(body, dict) else payload
        for key in _ROW_KEYS:
            if key in body:
                parts.append(json.dumps(body[key]))
                break
        else:
            parts.append(json.dumps(payload) if payload is not body else str(result or ""))
    return "\n".join(parts)


#: A failure envelope's own flag, matched **in the text** — the fallback half
#: of `statement_was_answered`. See there for why a parse is not enough.
_FAILED_FLAG = re.compile(r'"ok"\s*:\s*false', re.IGNORECASE)


def statement_was_answered(result: Any) -> bool:
    """Whether this exchange came back with data rather than a refusal.

    `launch-readiness/155`. *"A statement carrying the value was sent"* is not
    evidence that an answer is about that value; *"and it came back with
    something"* is. `cells_of` already states the rule — a payload that
    declares itself unsuccessful contributes nothing at all — so this is that
    reading asked as a question.

    **The textual fallback is not belt-and-braces, it is the live path.**
    `tool_report` caps a recorded result at `QUERY_RESULT_RECORD_CAP` (2 000
    characters), and an ODBC failure message is longer than that, so what the
    record holds is a Python repr cut mid-string: `ast.literal_eval` refuses
    it, `payloads_of` hands back the raw text, and `cells_of` — correctly, for
    a CSV or a Markdown table — passes it through as data. Measured on a live
    MCP run on 2026-08-29: three refusals in a row, every one of them carrying
    its own `"ok": false` in text that could not be parsed.

    Tolerant in reading, strict in trusting: the flag is the one
    `abc/tool_findings` already treats as the envelope's failure, matched
    nowhere else and never inferred from an `error` key that merely exists.
    """
    text = str(result or "")
    if not text.strip():
        return False
    if _FAILED_FLAG.search(text):
        return False
    return bool(cells_of(text).strip())


#: Every table a statement names, not only the first. A join reaches two, and
#: a check that read only `FROM` would judge a two-table statement by the one
#: that happened to be written first (`launch-readiness/166`, found on a live
#: run whose statement had the shape `FROM main.Track ... EXISTS (SELECT 1 FROM
#: main.PlaylistTrack ...)`, putting the table under suspicion in second
#: place).
_FROM_OR_JOIN = re.compile(r"\b(?:from|join)\s+([A-Za-z_][\w.]*)", re.IGNORECASE)


def tables_in(sql: str) -> list[str]:
    """Every table this statement reads, in the order it names them."""
    found: list[str] = []
    for match in _FROM_OR_JOIN.finditer(str(sql or "")):
        name = match.group(1)
        if name not in found:
            found.append(name)
    return found


def table_of(sql: str) -> str:
    match = _FROM.search(str(sql or ""))
    return match.group(1) if match else ""


def exchanges_in(state: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every `(statement, result)` pair this run actually executed.

    **Two rails, and the second is the one that carries a live run.** `_agent`
    returns no messages at all, so a guard downstream of an agent sees an empty
    `messages` and the whole of what the agent retrieved sits in
    `tool_use[node]["queries"]` instead (`launch-readiness` 165,
    `tool_report`). The message rail still matters for a graph whose SQL is run
    by a node rather than inside a loop.

    The SQL is found by **shape, not by tool name** (`looks_like_sql_query`,
    `production-ready/95`), so a tool called `warehouse` is read exactly as well
    as one called `mcp_execute_sql`, and the call is paired with its answer by
    `tool_call_id` because the answer arrives after the call it has to be
    judged by (`production-ready/100`'s pairing).

    Extracted from `row_counts_retrieved` when `launch-readiness/166` became
    its second reader. Two walks over one record drift; `165` already paid for
    that once, when the message rail was the only one and every gate behind an
    agent was blind.
    """
    from openstategraph.compile.workflow_compiler import looks_like_sql_query

    asked: dict[str, str] = {}
    for message in state.get("messages") or []:
        for call in getattr(message, "tool_calls", None) or []:
            args = call.get("args") if isinstance(call, dict) else None
            if not isinstance(args, dict):
                continue
            sql = next((str(v) for v in args.values() if looks_like_sql_query(v)), "")
            if not sql:
                continue
            call_id = str(call.get("id") or "")
            if call_id:
                asked[call_id] = sql

    pairs: list[tuple[str, str]] = []

    def add(sql: str, result: str) -> None:
        if sql and (sql, result) not in pairs:
            pairs.append((sql, result))

    for row in (state.get("tool_use") or {}).values():
        for exchange in (row or {}).get("queries") or []:
            add(
                str((exchange or {}).get("sql") or ""),
                str((exchange or {}).get("result") or ""),
            )

    for message in state.get("messages") or []:
        if getattr(message, "type", "") != "tool":
            continue
        # A refused or failed call returned nothing anybody could publish.
        if getattr(message, "status", None) == "error":
            continue
        recorded = asked.get(str(getattr(message, "tool_call_id", "") or ""))
        if recorded is None:
            continue
        add(recorded, str(getattr(message, "content", "")))
    return pairs


def row_counts_retrieved(state: Mapping[str, Any]) -> list[tuple[Decimal, str]]:
    """Every `(value, table)` this run obtained from a statement counting rows.

    Every number in the result is taken, not one. A bare `COUNT(*)` with no
    `GROUP BY` returns a single cell, but the envelope around it carries its
    own (`{"row_count": 1, "rows": [...]}`), and there is no way to tell the
    cell from the envelope without knowing the tool. The plural-noun rule
    below is what keeps that widening harmless: an envelope's `1` cannot be
    published as *"1 tracks"*.
    """
    found: list[tuple[Decimal, str]] = []
    for sql, result in exchanges_in(state):
        if not counts_rows_only(sql):
            continue
        table = table_of(sql)
        for value in numbers_in(cells_of(result)):
            if (value, table) not in found:
                found.append((value, table))
    return found


def label_after(prose: str, end: int) -> str:
    """The plural entity noun this number is presented as counting, or ``""``.

    A row-noun anywhere in the window answers the check's question, so it wins
    over an earlier entity word: *"1,454,449 daily geofence rows"* is honest.
    """
    words: list[str] = []
    for match in _WORD.finditer(prose, end):
        words.append(match.group())
        if len(words) >= _WINDOW:
            break
        # Stop at a sentence end — the next sentence is a different claim.
        tail = prose[match.end() : match.end() + 1]
        if tail in ".;:!?":
            break
    lowered = [word.lower() for word in words]
    if any(word in ROW_NOUNS for word in lowered):
        return ""
    for word in lowered:
        if len(word) >= 4 and word.endswith("s") and word not in _NOT_A_NOUN:
            return word
    return ""


def mislabelled_row_counts(
    prose: str, row_counts: Iterable[tuple[Decimal, str]]
) -> list[tuple[str, str]]:
    """`(literal, noun)` for each row count the answer presents as entities."""
    by_value: dict[Decimal, str] = {}
    for value, table in row_counts:
        by_value.setdefault(value, table)
    reported: list[tuple[str, str]] = []
    seen: set[str] = set()
    for literal, value, end in quantities_in(prose or ""):
        if literal in seen or value not in by_value:
            continue
        label = label_after(prose or "", end)
        if not label:
            continue
        seen.add(literal)
        reported.append((literal, label))
    return reported


def check_row_counts_in_prose(
    candidate: str, state: Mapping[str, Any], model_authored: Iterable[str]
) -> str:
    """`guard.check`'s row-grain gate: empty is a pass, text is the revise reason.

    `model_authored` is accepted and unused. It is part of the built-in check
    signature (`_BUILT_IN_CHECKS`) because `numbers_in_prose` needs to know
    whose text is evidence and whose is the thing being judged; this check
    reads only tool calls, which are nobody's draft.

    The reason is developer- and model-facing — it travels the `feedback`
    channel to the node being corrected — so `launch-readiness/143`'s
    sentence-shape rule for customer copy does not reach it.

    **Two sentences, and which one is said depends on a declaration**
    (`launch-readiness/166`). Without one this check says what it has always
    said and all it can honestly say: *a row is one of these only if the table
    holds one row per one of them, and this run never established that.* Where
    the table has declared a row key of more than one column, a row provably is
    **not** one of anything, so the doubt becomes a statement of fact and the
    repair stops being a suggestion. That is the whole of what `row_key` buys,
    and it buys it without this module ever deciding which column identifies the
    entity — a key of length > 1 settles the question on its own.
    """
    from openstategraph.table_coverage import declarations_in

    counts = row_counts_retrieved(state)
    if not counts:
        return ""
    by_value: dict[Decimal, str] = {}
    for value, table in counts:
        by_value.setdefault(value, table)
    reported = mislabelled_row_counts(candidate, counts)
    if not reported:
        return ""
    declarations = declarations_in(state)

    lines = []
    for literal, label in reported:
        table = by_value.get(Decimal(literal.replace(",", "")), "")
        singular = label[:-1] or label
        declaration = declarations.get(table.casefold()) if table else None
        if declaration is not None and declaration.a_row_is_not_one_thing():
            key = ", ".join(declaration.row_key)
            lines.append(
                f"The answer reports {literal} {label}. That figure came from a bare "
                f"COUNT(*) over {table or 'a table'}, and {table or 'that table'} declares "
                f"its row key as ({key}) — so one row is one of those combinations and not "
                f"one {singular}. {literal} is a count of rows, and the count of {label} is "
                "a different and smaller number."
            )
        else:
            lines.append(
                f"The answer reports {literal} {label}. That figure came from a bare "
                f"COUNT(*) over {table or 'a table'}, which counts rows of "
                f"{table or 'that table'} and nothing else. A row is a {singular} "
                f"only if {table or 'the table'} holds exactly one row per {singular}, "
                "and this run never established that."
            )
    lines.append(
        "Either count the entity itself — COUNT(DISTINCT <the column that identifies "
        "it>) — or say what was actually counted."
    )
    return "\n".join(lines)
