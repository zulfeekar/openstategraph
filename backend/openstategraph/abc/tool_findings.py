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

import ast
import json
import re
from collections.abc import Callable
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

# ===================================================================== #
# The deep-agent harness's own file tools (`launch-readiness/144`)
# ===================================================================== #
#
# `create_deep_agent` pre-assembles `FilesystemMiddleware`, so `ls`,
# `read_file`, `write_file`, `edit_file`, `glob` and `grep` are on every
# `DeepAgentNode` whether or not its author wired a tool — and on a deep-tier
# run they are the most frequent lines in the panel. `tool_sentences.py`
# already says what each one *is doing*; until this section none of them said
# what it found, so the owner's screen read `"Reading a file it has open."`
# a dozen times with nothing between.
#
# `launch-readiness/102` is why it matters more than it looks: a large tool
# result is offloaded to a file and read back, so `read_file` **is** how the
# run gets its data. Three identical "Reading a file it has open." lines were
# the account of the part that mattered.
#
# ## These results are prose, not an envelope
#
# The table above reads a JSON envelope and counts a declared key. The harness
# returns **plain text** — `"['/a.txt', '/sub/']"`, `"1  hello\n2  world"`,
# `"Successfully replaced 3 instance(s) of the string in '/m.txt'"`. So this is
# a second mechanism rather than a wider `_Finding`: a reader per tool, keyed
# on a shape somebody has actually seen. Same seam, same safety rule, same
# published shapes.
#
# ## Every shape here was read off the installed harness, not guessed
#
# `deepagents==0.7.5`, driven through `FilesystemMiddleware(...).tools` against
# a real `FilesystemBackend` (the same `virtual_mode=True` backend
# `abc/deep_tier_offload.py` builds), one call per case, on 2026-08-28. The
# captured strings are the fixtures in `tests/test_tool_findings.py`. A guessed
# shape resolves to nothing, produces no line, and looks exactly like a tool
# with nothing to report.
#
# ## A path is never spoken here, and this is the rule
#
# Every one of these results carries a path — `ls` returns nothing else, and
# `write_file` answers `"Updated file /new.txt"`. None crosses. The rule is
# **who chose the string**, not whether it looks like a path:
#
# - **Speakable**: a name a person authored. The reader's own words
#   (`web_search`'s query), a repository file a developer asked about
#   (`code_read`, `platform_read_file`), or a document published under a name
#   its author chose — `mcp_skill_read`'s `cargoflow/SKILL.md`, which
#   `tool_sentences.py` speaks for exactly that reason.
# - **Not speakable**: a string the machinery minted. `/offload/<tool>/<call
#   id>.txt` is this platform's own envelope (`abc/deep_tier_offload.py`), and
#   a harness scratch file is the harness's. `launch-readiness/112` caught
#   `Reading /offload/mcp_list_lenses/call_eeR8/3LoOli2BeA5Cqk4p6ik.txt.` in a
#   customer chat, which is what that costs.
#
# The harness tools fail the rule for a reason sharper than "these are
# internal": **one tool reads both kinds.** The same `read_file` fetches a
# published skill and an offload envelope, and at the call site there is
# nothing in the string that tells them apart — the discrimination would have
# to be a guess about a path prefix. Undecidable, therefore not spoken. That
# is also why `tool_sentences.py` declares no argument for them while
# `mcp_skill_read` declares one: the difference is not the tool's tier, it is
# whether the identity of the value is knowable.
#
# So a finding here is what it is everywhere else — integers and a published
# template, nothing else.

#: The harness's own failure shape. Every filesystem tool answers a refusal as
#: `"Error: …"` prose — `"Error: File '/nope.txt' not found"`,
#: `"Error: Path '/empty': path_not_found"` — never `{"ok": false}`. The
#: message names the path, so the message never crosses; the *fact* of the
#: failure does, which is `143`'s point about two states rendering identically.
_HARNESS_ERROR_PREFIX = "Error: "

#: The harness's own marker for "this file exists and has no contents",
#: rendered as line 1 of an otherwise empty read. Read off `deepagents==0.7.5`.
_EMPTY_FILE_NOTE = "System reminder: File exists but has empty contents"

#: `read_file`'s pagination trailer — the one place the harness states both
#: halves of what `144` asked for, *lines read* and *whether it is the whole
#: file*: `[Read 100 lines (lines 1-100 of 250 total). 150 lines remaining …]`
_READ_PAGINATION = re.compile(r"\[Read (\d+) lines? \(lines \d+-\d+ of (\d+) total\)")

#: How a rendered line is numbered: right-aligned number, two spaces, content.
_NUMBERED_LINE = re.compile(r"^ *(\d+)  ", re.MULTILINE)

#: `edit_file`'s count, the one number it reports.
_REPLACED = re.compile(r"replaced (\d+) instance")

#: Substrings, not the full sentences, because the full sentences are a
#: third-party library's wording and would go stale silently. Both mean the
#: same thing to a reader: the number below is a prefix, not the whole answer.
_STOPPED_EARLY = "stopped early"
_RESULTS_TRUNCATED = "[results truncated"
_SIZE_TRUNCATED = "[Output was truncated due to size limits."


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _harness_read_file(text: str) -> str | None:
    """Lines read, and whether that is the whole file.

    **A line count is not a row count, and that is the trap this closes.**
    `launch-readiness/102` offloads a large result to a file and the agent
    reads it back — one 48,000-character JSON line. `"Read 1 line."` would be
    `143`'s `"1 result."` defect in a new place: a number that looks real and
    is not. So a single-line read reports *characters*, which is the unit that
    carries the information when lines do not.
    """
    if _EMPTY_FILE_NOTE in text:
        return "That file is empty."
    paginated = _READ_PAGINATION.search(text)
    if paginated is not None:
        read, total = int(paginated.group(1)), int(paginated.group(2))
        if read < total:
            return f"Read {read} of {total} lines in the file."
        return f"Read {read} {_plural(read, 'line', 'lines')}."
    truncated = _SIZE_TRUNCATED in text
    body = text.split(_SIZE_TRUNCATED, 1)[0] if truncated else text
    numbers = _NUMBERED_LINE.findall(body)
    if not numbers:
        return None
    count = len(numbers)
    if count == 1:
        characters = len(_NUMBERED_LINE.sub("", body, count=1).rstrip("\n"))
        if truncated:
            return f"Read the first {characters} characters of one very long line."
        return f"Read {characters} characters on one line."
    if truncated:
        return f"Read the first {count} lines of the file."
    return f"Read {count} {_plural(count, 'line', 'lines')}."


def _path_list(text: str) -> tuple[int, bool] | None:
    """How many paths this listing holds, and whether it is a prefix.

    `ls` and `glob` both answer with `str(list_of_paths)` — a Python repr, not
    JSON — optionally followed by a blank line and the library's own
    "stopped early" note, and optionally with its truncation marker as the
    final element. Parsed with `ast.literal_eval`, which reads a list of
    strings and nothing else: a repr this cannot parse yields no line rather
    than a number split off a comma.
    """
    blocks = text.split("\n\n")
    truncated = any(_STOPPED_EARLY in block for block in blocks[1:])
    try:
        paths = ast.literal_eval(blocks[0])
    except (ValueError, SyntaxError):
        return None
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        return None
    if paths and _RESULTS_TRUNCATED in paths[-1]:
        paths = paths[:-1]
        truncated = True
    return len(paths), truncated


def _harness_ls(text: str) -> str | None:
    """How many entries the folder holds.

    "Files and folders" rather than "files": `ls` returns directories too,
    with a trailing slash, and calling a folder a file is a small lie that
    costs nothing to avoid.
    """
    if text.strip() == "No files found":
        return "Nothing in that folder."
    counted = _path_list(text)
    if counted is None:
        return None
    count, truncated = counted
    noun = _plural(count, "file or folder", "files and folders")
    if truncated:
        return f"Found the first {count} {noun} of a longer list."
    if count == 0:
        return "Nothing in that folder."
    return f"Found {count} {noun}."


def _harness_glob(text: str) -> str | None:
    if text.strip() == "No files found":
        return "No matching files."
    counted = _path_list(text)
    if counted is None:
        return None
    count, truncated = counted
    noun = _plural(count, "matching file", "matching files")
    if truncated:
        return f"Found the first {count} {noun} of a longer list."
    if count == 0:
        return "No matching files."
    return f"Found {count} {noun}."


def _harness_grep(text: str) -> str | None:
    """Matches, and the files they are in — from whichever shape was asked for.

    `grep` has three output modes and each renders differently:
    `files_with_matches` (the default) is one path per line and carries no
    match count at all; `count` is `path: n`; `content` is a `path:` header
    followed by two-space-indented `n: line` rows. The count is exact in two
    of them and genuinely unknown in the third, and the sentences differ
    accordingly rather than inventing the missing half.
    """
    blocks = text.split("\n\n")
    body = blocks[0]
    if body.strip() == "No matches found":
        return "No matches found."
    if "Partial matches:" in text:
        # The backend errored part-way and appended what it had. What it had
        # is real, but "how many" is no longer a number anybody can stand
        # behind, so this reports the failure and not a count.
        return _FAILED_TEXT
    truncated = any(_STOPPED_EARLY in block for block in blocks[1:])
    lines = [line for line in body.split("\n") if line]
    if not lines:
        return None
    counted = [re.fullmatch(r"(?P<path>.+): (?P<n>\d+)", line) for line in lines]
    if all(match is not None for match in counted):
        files = len(lines)
        matches = sum(int(m.group("n")) for m in counted if m is not None)
    elif any(re.match(r"^ {2}\d+: ", line) for line in lines):
        files = sum(1 for line in lines if line.endswith(":") and not line.startswith("  "))
        matches = sum(1 for line in lines if re.match(r"^ {2}\d+: ", line))
    else:
        files = len(lines)
        matches = None
    if matches is None:
        noun = _plural(files, "file", "files")
        if truncated:
            return f"Found matches in {files} {noun} before stopping early."
        return f"Found matches in {files} {noun}."
    m_noun = _plural(matches, "match", "matches")
    f_noun = _plural(files, "file", "files")
    if truncated:
        return f"Found the first {matches} {m_noun} in {files} {f_noun}."
    return f"Found {matches} {m_noun} in {files} {f_noun}."


def _harness_write_file(text: str) -> str | None:
    """That the write landed — the only fact in the result, and a real one.

    There is no count here to report: `write_file` answers `"Updated file
    <path>"` and nothing else, and the number of lines written lives in the
    *arguments*, which this seam is not handed and should not be. What it
    does close is the state `143` named: a failed write and a successful one
    used to render identically, as silence.
    """
    return "Saved the file." if text.startswith("Updated file") else None


def _harness_edit_file(text: str) -> str | None:
    found = _REPLACED.search(text)
    if found is None:
        return None
    count = int(found.group(1))
    return f"Changed {count} {_plural(count, 'place', 'places')} in the file."


#: `name -> how to read its plain-text result`. `task` is deliberately absent:
#: a subagent's report is free prose with nothing countable in it, and
#: `144`'s own rule is that a shape which cannot be counted honestly stays out
#: of the table rather than being approximated.
_TEXT_TABLE: dict[str, Callable[[str], str | None]] = {
    "read_file": _harness_read_file,
    "write_file": _harness_write_file,
    "edit_file": _harness_edit_file,
    "ls": _harness_ls,
    "glob": _harness_glob,
    "grep": _harness_grep,
}

#: Every template the readers above can produce, with each integer as `#` —
#: published for the same walk `_shapes()` does over `_TABLE`, and listed here
#: because these sentences are written inline rather than assembled from a
#: dataclass. A reader that emits anything not on this list fails
#: `tests/test_tool_findings.py`.
_HARNESS_SHAPES: tuple[str, ...] = (
    "That file is empty.",
    "Read # of # lines in the file.",
    "Read # line.",
    "Read # lines.",
    "Read the first # lines of the file.",
    "Read # characters on one line.",
    "Read the first # characters of one very long line.",
    "Nothing in that folder.",
    "Found # file or folder.",
    "Found # files and folders.",
    "Found the first # file or folder of a longer list.",
    "Found the first # files and folders of a longer list.",
    "No matching files.",
    "Found # matching file.",
    "Found # matching files.",
    "Found the first # matching file of a longer list.",
    "Found the first # matching files of a longer list.",
    "No matches found.",
    "Found matches in # file.",
    "Found matches in # files.",
    "Found matches in # file before stopping early.",
    "Found matches in # files before stopping early.",
    "Found # match in # file.",
    "Found # match in # files.",
    "Found # matches in # file.",
    "Found # matches in # files.",
    "Found the first # match in # file.",
    "Found the first # match in # files.",
    "Found the first # matches in # file.",
    "Found the first # matches in # files.",
    "Saved the file.",
    "Changed # place in the file.",
    "Changed # places in the file.",
)


#: `{"ok": false}` — the CPL MCP envelope's own failure flag. Read only for a
#: tool this table already knows, so an unrelated payload that happens to
#: carry an `ok` key is never spoken for.
_FAILED_TEXT = "That did not work."

#: Every tool this module can report a finding for — both mechanisms, one
#: list, because a caller asking "does this tool have a finding?" does not
#: care whether the answer came out of an envelope or a line of prose.
FINDING_TOOL_NAMES: tuple[str, ...] = tuple(sorted(set(_TABLE) | set(_TEXT_TABLE)))


def _shapes() -> tuple[str, ...]:
    """Every sentence this module can emit, with each integer as `#`.

    Built from the table rather than listed beside it, so a new entry cannot
    add a template nobody reviewed. This is what makes "only numbers are ever
    spoken" a checkable claim instead of a promise.
    """
    shapes: set[str] = {_FAILED_TEXT, *_HARNESS_SHAPES}
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
    name = (name or "").strip()
    reader = _TEXT_TABLE.get(name)
    if reader is not None:
        # `launch-readiness/144`: the deep-agent harness answers in prose, not
        # in an envelope, so its findings are read by a per-tool function
        # rather than by a key path. Same rule at the exit: integers only, and
        # every sentence a published shape.
        text = _plain_text(content)
        if text is None:
            return None
        if text.startswith(_HARNESS_ERROR_PREFIX):
            return _FAILED_TEXT
        sentence = reader(text)
        return _fits(sentence) if sentence else None
    finding = _TABLE.get(name)
    if finding is None:
        return None
    envelope = result_envelope(content)
    if envelope is None:
        return None
    if envelope.get("ok") is False:
        return _FAILED_TEXT
    data = envelope.get("data")
    if not isinstance(data, dict):
        data = envelope
    return _sentence(finding, data)


def _plain_text(content: Any) -> str | None:
    """The result as text, for a tool whose result *is* text.

    A `ToolMessage` from an in-process tool carries a plain string; the same
    result crossing an MCP boundary arrives as content blocks. Both are read,
    for `result_envelope`'s reason and by the same helper — anything else is not
    something this module claims to understand.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return _text_of_blocks(content)
    return None


def result_envelope(content: Any) -> dict[str, Any] | None:
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

    **Public within `abc/` rather than private** (`launch-readiness/157`).
    "What shape does a tool result arrive in" is one piece of knowledge, and
    `prebuilt_mcp` needs the identical answer to find the notes a server
    declared. Two decoders for one wire format is the duplication DRY actually
    forbids — and the third shape above was only learned by running the thing,
    so the second copy would have been the one that never learned it.
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
