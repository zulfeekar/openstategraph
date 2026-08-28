"""What a tool call *found*, in one sentence — derived, never restated.

`launch-readiness/143`. `launch-readiness/112` gave every tool call a sentence
saying what it *is doing*, and the moment after it kept saying nothing:
`after_model` emitted `"Finished thinking."` — a line authored for a
replace-in-place surface, which in `launch-readiness/140`'s stack alternated
with the real ones and carried no account — and `wrap_tool_call`'s after-line
described only the shape of a Python object, so the JSON *string* every MCP
tool actually returns produced no line at all.

`wrap_tool_call` is the one hook in the whole loop that knows something true:
it holds the tool, its arguments **and its result**. `before_model` genuinely
knows nothing yet, and `after_model` knows only that a model returned. So the
honest arrangement is silence where nothing is known and a finding where
something is — which is what this module supplies, as a contribution into the
`"narration"` slot exactly like `tool_sentences.py`, injected by
`build_narration_middleware` as `summarise=` and never imported by
`NarrationMiddleware` itself.

## Derived, not restated — and why that is the point

The live `cpl-mcp` run of 2026-08-27 answered the Persian Gulf question
correctly three times running and *described itself wrongly twice*: one run's
prose said "69 distinct ports" while listing 68, another's findings note
claimed 83. A count the model writes can drift from the result; a count read
off `row_count` cannot. Every number below comes from the payload the tool
returned on this call.

Note which number that is, too. `mcp_execute_sql` carries both `row_count`
(the engine's own count over the whole result) and `sample_rows` (one row).
Counting the sample would be a derivation that is *reliably wrong* — the exact
failure mode this module exists to close — so `row_count` is declared first.

## Only numbers are ever spoken

This is the safety property, and it is by construction rather than by
filtering. `launch-readiness/112` caught two leaks live that no test found: an
internal URL and an offload path, both reaching a customer chat because a
*value* was interpolated into a sentence. A result payload is a far richer leak
surface than a call's arguments — the fixtures in
`tests/test_tool_findings.py` carry table names, an ODBC driver message, a
request id and a user's own search term — so nothing from a result is ever
interpolated. A sentence is a template from the table below plus integers.
`SENTENCE_SHAPES` publishes every template this module can produce, and the
test walks it: strip the digits from any output and what remains must be a
line authored in this file.

That also settles what a *failure* may say. `{"ok": false, "message": …}` is a
real finding — today a failed call and a free-text success both produce no
line, which is this map's own theme of two situations rendering identically —
but the message is the driver's own words and never crosses. `"That did not
work."` is the whole of it; the model still receives the full error and still
retries, because narration reads the result and does not touch it.

## Every key is verified against a running server

The keys below were read off the live CPL MCP server at
`http://localhost:8080/mcp/` on 2026-08-28, one call per entry, and the
captured payloads are the test fixtures. That is deliberate: a guessed key
resolves to nothing, produces no line, and looks exactly like a tool that has
nothing to report. A tool whose result shape has not been verified is simply
absent from the table and falls to `NarrationMiddleware`'s own shape floor —
the same arrangement `tool_sentences.py` has with its keyword floor.

## Why this is not `tool_sentences.py`

Same seam, different knowledge, different reason to change. A sentence is
keyed on the tool's **name and arguments** and is authored with no result in
hand; a finding is keyed on the **result's own envelope** and changes when a
server changes its payload. Folding them into one table would put a table of
English phrases and a table of JSON key paths behind one entry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

#: The panel's own ceiling. One home, imported by `narration.py` and used by
#: `tool_sentences.py`, rather than the three separate `80`s this file's
#: arrival would otherwise have made.
MAX_SENTENCE_LEN = 80


@dataclass(frozen=True)
class _Finding:
    """How to read one tool's result, declared by somebody who has seen one.

    `keys` are candidate paths inside the envelope's `data`, in preference
    order — first one that yields a count wins. A count is an integer field or
    the length of a list or map; anything else is not a count and is skipped.
    """

    #: The reader's word for one of whatever was found, and for several. These
    #: are the *reader's* words, never the server's: `tool_sentences.py` calls
    #: a lens "a view of the data", and a finding that said "lens" would teach
    #: the server's vocabulary on the way out of the very sentence that avoids
    #: it on the way in.
    singular: str
    plural: str
    #: Where the count lives. `row_count` before `sample_rows` on purpose.
    keys: tuple[str, ...]
    #: The second dimension, when the result honestly has one.
    across: tuple[str, str, tuple[str, ...]] | None = None
    #: A boolean whose truth is the finding, checked before any count.
    when_true: tuple[str, str] | None = None
    #: What "none" means here, when "no X found" is the wrong sentence.
    zero: str = ""
    #: The flag that says this count is a prefix of a longer result.
    truncated_key: str = ""


#: `name -> how to read its result`. Every key verified live, 2026-08-28.
_TABLE: dict[str, _Finding] = {
    # --- the CPL MCP surface -------------------------------------------
    "mcp_list_lenses": _Finding("view of the data", "views of the data", ("lenses",)),
    "mcp_describe_lens_tables": _Finding("table", "tables", ("tables",)),
    "mcp_describe_table": _Finding("column", "columns", ("columns",)),
    "mcp_search_tables": _Finding("matching table", "matching tables", ("tables",)),
    "mcp_execute_sql": _Finding(
        "row",
        "rows",
        ("row_count", "rows"),
        across=("column", "columns", ("columns",)),
        truncated_key="truncated",
    ),
    "mcp_fetch_result_page": _Finding(
        "row",
        "rows",
        ("row_count", "rows"),
        across=("column", "columns", ("columns",)),
        truncated_key="truncated",
    ),
    "mcp_skill_list": _Finding("skill", "skills", ("paths",)),
    "mcp_skill_grep": _Finding("match", "matches", ("hits",), truncated_key="truncated"),
    "mcp_lookup_few_shot": _Finding("worked example", "worked examples", ("examples",)),
    # The one entry whose finding is a verdict before it is a count. The
    # handoff of 2026-08-27 records why it matters: this tool answered
    # `is_canonical: false, candidates: [], needs_clarification: false`, so
    # *"there is no such thing"* and *"I could not find it"* reached the agent
    # identically and the model filled the gap itself. Three states, three
    # sentences.
    "mcp_lookup_canonical_value": _Finding(
        "close spelling",
        "close spellings",
        ("candidates",),
        when_true=("is_canonical", "That value is used in the data as written."),
        zero="No match for that value in the data.",
    ),
}

#: `{"ok": false}` — the CPL MCP envelope's own failure flag. Read only for a
#: tool this table already knows, so an unrelated payload that happens to
#: carry an `ok` key is never spoken for.
_FAILED_TEXT = "That did not work."

#: Every tool this module can report a finding for.
FINDING_TOOL_NAMES: tuple[str, ...] = tuple(sorted(_TABLE))


def _shapes() -> tuple[str, ...]:
    """Every sentence this module can emit, with each integer as `#`.

    Built from the table rather than listed beside it, so a new entry cannot
    add a template nobody reviewed. This is what makes "only numbers are ever
    spoken" a checkable claim instead of a promise.
    """
    shapes: set[str] = {_FAILED_TEXT}
    for finding in _TABLE.values():
        if finding.when_true is not None:
            shapes.add(finding.when_true[1])
        shapes.add(finding.zero or f"No {finding.plural} found.")
        for noun in (finding.singular, finding.plural):
            head = f"Found # {noun}"
            shapes.add(head + ".")
            if finding.truncated_key:
                shapes.add(f"Found the first # {noun} of a longer result.")
            if finding.across is not None:
                a_sing, a_plural, _ = finding.across
                for a_noun in (a_sing, a_plural):
                    shapes.add(f"{head} across # {a_noun}.")
    return tuple(sorted(shapes))


#: Published for the test that walks it. See the module header.
SENTENCE_SHAPES: tuple[str, ...] = _shapes()


def summarise_tool_result(name: str, content: Any) -> str | None:
    """One sentence for what this call found, or `None` when nothing is known.

    `None` rather than a guess, for `describe_tool_call`'s reason: the
    caller's own shape floor is a better answer than a sentence this table
    would be inventing, and "this result says nothing I can read" is a state
    worth keeping distinguishable from "this result was empty".
    """
    finding = _TABLE.get((name or "").strip())
    if finding is None:
        return None
    envelope = _envelope(content)
    if envelope is None:
        return None
    if envelope.get("ok") is False:
        return _FAILED_TEXT
    data = envelope.get("data")
    if not isinstance(data, dict):
        data = envelope
    return _sentence(finding, data)


def _envelope(content: Any) -> dict[str, Any] | None:
    """The result as a mapping, or `None`.

    Tolerant in reading, strict in trusting (CLAUDE.md). Three shapes arrive
    in practice and all three are read:

    - a **mapping**, when a tool is called in-process;
    - a **JSON string**, the plain `response_format="content"` case;
    - a **list of content blocks**, which is what an MCP tool actually
      produces here — `prebuilt_mcp._wrap_async_tool` carries
      `content_and_artifact` across, so the text lands inside
      `[{"type": "text", "text": "{…}"}]`.

    The third was found on the live `cpl-mcp` run this ticket was verified
    against, and it is why the shape floor read a 121-row query as
    `"1 result."`: one text block is one list item. A parser and the thing it
    parses disagreeing is the case CLAUDE.md says to suspect the parser for.

    Anything else — free prose, an object carrying no JSON — is not something
    this module claims to understand, and the caller's floor gets its turn.
    """
    if isinstance(content, dict):
        return content
    if isinstance(content, (list, tuple)):
        content = _text_of_blocks(content)
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _text_of_blocks(content: Any) -> str | None:
    """The text a list of content blocks carries, or `None` if it is not one.

    Strict about what counts as a block list: every item must be a text block
    or a bare string. A list of *records* — which is what a tool returning
    rows in-process produces — is deliberately not a block list, and stays
    the shape floor's to count.
    """
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
        else:
            return None
    return "".join(parts) if parts else None


def _sentence(finding: _Finding, data: dict[str, Any]) -> str | None:
    if finding.when_true is not None:
        key, text = finding.when_true
        if data.get(key) is True:
            return _fits(text)
    count = _count(data, finding.keys)
    if count is None:
        return None
    if count == 0:
        return _fits(finding.zero or f"No {finding.plural} found.")
    noun = finding.singular if count == 1 else finding.plural
    if finding.truncated_key and data.get(finding.truncated_key) is True:
        # A count that is a prefix is a different fact from a count that is
        # the whole answer, and saying the first as if it were the second is
        # `launch-readiness/129`'s defect in one line of prose.
        return _fits(f"Found the first {count} {noun} of a longer result.")
    sentence = f"Found {count} {noun}"
    if finding.across is not None:
        a_sing, a_plural, a_keys = finding.across
        second = _count(data, a_keys)
        if second is not None:
            a_noun = a_sing if second == 1 else a_plural
            wide = f"{sentence} across {second} {a_noun}."
            # The wider sentence when it fits, the narrower one when it does
            # not — both true, never a truncation of either.
            if len(wide) <= MAX_SENTENCE_LEN:
                return wide
    return _fits(sentence + ".")


def _count(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    """How many, from the first declared key that holds a countable thing.

    A `bool` is deliberately not an integer here: Python says `True == 1` and
    a flag counted as one result is a number that looks real and is not.
    """
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, (list, tuple, dict)):
            return len(value)
    return None


def _fits(sentence: str) -> str | None:
    """The sentence, or nothing — never a shortened one.

    Every template here is well within the ceiling; this exists so that the
    ceiling is enforced at the exit rather than assumed, and so a future entry
    with a longer noun fails loudly in the test that walks `SENTENCE_SHAPES`
    rather than quietly overflowing a card.
    """
    return sentence if len(sentence) <= MAX_SENTENCE_LEN else None
