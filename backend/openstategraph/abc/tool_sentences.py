"""What a tool call *is doing*, in one sentence — a table, never a model.

`launch-readiness/112`. `abc/narration.py` narrated every tool call with a
keyword guess off the tool's *name* (`"Searching the data."`,
`"Calling a tool."`), and said so in its own header: a sharper line is *"a
contribution into the same `narration` slot"*, not a change to the base.
Nobody had ever contributed one, so every step of every run narrated in the
same dozen words.

This is that contribution. `describe_tool_call` is a pure
`(name, args) -> sentence | None` function over a table of this project's own
tool surface — the 13 tools a lens-serving MCP server advertises and the 19
built-ins
`prebuilt_*.py` / `knowledge_explorer.py` ship. No state, no I/O, no round
trip.

## Why the table lives here and not on `NarrationMiddleware`

The base's header is explicit that it "has no domain knowledge — it wraps
`before_model`/`after_model` for *any* agent, so it never has a tool id, a
lens name, or a token count to report honestly". That is still true, and the
base still ships its keyword floor for a tool this table has never met.
`build_narration_middleware` — the one place the `"narration"` slot is filled
— injects this describer, so the base inherits the *capability* to be told
what a call is doing and never the composition. A workflow that wants its own
sentences passes its own describer into the same slot.

## The two rules that are not negotiable

- **Deterministic, and no model call.** The header records the defect that
  closes: a model asked to narrate leaked its scratchpad into a
  customer-facing answer, and `BaseAgentNode.PROMPT`'s `output_contract` now
  explicitly forbids an agent narrating its own tool loop. A table cannot
  leak and cannot decline.
- **A tool is never named aloud.** Not one sentence below contains a tool id,
  a function name or an `mcp_` prefix. They describe the *action*.

## Arguments: declared per tool, never guessed

The base refuses to interpolate any argument, and gives the reason: an
argument can be a lens id the user has never met, and there is no *generic*
way to tell that from a value they typed. That reasoning is about a function
with no tool identity in hand. This one has it — so the safe argument is
**declared per tool**, by name, by somebody who knows what that tool's
parameters mean. `send_email` declares none on purpose: a recipient address is
not progress information.

Reading stays tolerant and trusting stays strict (CLAUDE.md). Several MCP
parameter *names* are not published in the 13-tool advertisement, so each
entry lists candidate keys in preference order and every sentence has a
working bare form. A missing key, a non-string, an empty string, a newline or
anything over `_MAX_VALUE_LEN` costs the interpolation and nothing else — the
sentence still reads. Nothing is ever truncated into something misleading
(CLAUDE.md's own rule), because a shortened value is dropped rather than
elided.

## Why this is not `abc/tool_notes.py`

`tool_notes.py` refused `112` deliberately and the argument holds: a note is
keyed on **this call's result**, held by the tool, authored at call time, and
consumed by the run's record. A narration sentence is keyed on the tool's
**name**, held by the platform, authored in advance with no result in hand,
and consumed by a live progress panel. Folding this into `ToolResult.notes`
would force a static table into a per-call envelope. Two tables, two reasons
to change — which is duplication of *shape*, not of knowledge.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Longer than this and the value is dropped rather than shortened. A value
#: cut mid-word reads as a different value, and this line is shown to people
#: who cannot open a trace to check (CLAUDE.md, "never truncate a value into
#: something misleading").
_MAX_VALUE_LEN = 60

#: `name -> (with_value, bare, arg_keys)`.
#:
#: `with_value` carries exactly one `{value}` and is used only when one of
#: `arg_keys` yields a usable string; `bare` is the sentence when it does not,
#: and is what a tool with no declared argument always says. `arg_keys` is in
#: preference order, first hit wins.
_Sentence = tuple[str, str, tuple[str, ...]]

_TABLE: dict[str, _Sentence] = {
    # --- the lens-serving MCP surface (13) -------------------------------
    # Read off a running server, one call per entry. "Lens" is the
    # server's word, not a reader's, so every sentence says *view of the data*.
    "mcp_list_lenses": (
        "",
        "Looking up which views of the data are available.",
        (),
    ),
    "mcp_resolve_lens": (
        'Finding the right view of the data for "{value}".',
        "Finding the right view of the data.",
        ("name", "lens", "query", "text", "term"),
    ),
    "mcp_describe_lens_tables": (
        "",
        "Listing the tables behind this view of the data.",
        (),
    ),
    "mcp_describe_table": (
        "Reading the structure of the {value} table.",
        "Reading a table's structure.",
        ("table", "table_name", "name"),
    ),
    "mcp_search_tables": (
        'Searching the catalogue for tables about "{value}".',
        "Searching the catalogue for a matching table.",
        ("query", "q", "search", "term", "text"),
    ),
    "mcp_lookup_canonical_value": (
        'Checking how "{value}" is spelled in the data.',
        "Checking how a value is spelled in the data.",
        ("value", "term", "text", "query", "name"),
    ),
    "mcp_skill_list": (
        "",
        "Looking up which written guidance is available.",
        (),
    ),
    "mcp_skill_read": (
        "Reading the written guidance on {value}.",
        "Reading the written guidance.",
        ("skill", "name", "path", "topic"),
    ),
    "mcp_skill_grep": (
        'Searching the written guidance for "{value}".',
        "Searching the written guidance.",
        ("pattern", "query", "q", "term", "text"),
    ),
    "mcp_lookup_few_shot": (
        'Looking for a worked example of "{value}".',
        "Looking for a worked example to follow.",
        ("query", "q", "question", "text"),
    ),
    "mcp_execute_sql": (
        "",
        "Running a query against the data.",
        (),
    ),
    "mcp_fetch_result_page": (
        "",
        "Fetching the next page of results.",
        (),
    ),
    "mcp_prepare": (
        "",
        "Getting the data connection ready.",
        (),
    ),
    # --- the built-in tool surface (19) ----------------------------------
    "sql_list_tables": ("", "Looking up which tables exist.", ()),
    "sql_get_table_schema": (
        "Reading the structure of the {value} table.",
        "Reading a table's structure.",
        ("table_name", "table", "name"),
    ),
    "sql_query": ("", "Running a query against the database.", ()),
    "web_search": (
        'Searching the web for "{value}".',
        "Searching the web.",
        ("query", "q", "search", "text"),
    ),
    "web_fetch": (
        "Reading the page at {value}.",
        "Reading a page from the web.",
        ("url", "link", "href"),
    ),
    "youtube_transcript": (
        "Reading the transcript of {value}.",
        "Reading a video's transcript.",
        ("url", "video_url", "video_id"),
    ),
    "knowledge_lookup": (
        'Looking through what this workflow knows about "{value}".',
        "Looking through what this workflow knows.",
        ("query", "q", "question", "topic", "text"),
    ),
    "write_topic": (
        "Writing up what it found on {value}.",
        "Writing up what it found.",
        ("topic", "title", "name"),
    ),
    "code_ls": (
        "Listing the files under {value}.",
        "Listing the files in the code.",
        ("path", "directory", "dir"),
    ),
    "code_read": (
        "Reading {value}.",
        "Reading a file.",
        ("path", "file", "filename"),
    ),
    "code_grep": (
        'Searching the code for "{value}".',
        "Searching the code.",
        ("pattern", "query", "q", "text"),
    ),
    "platform_list_workflows": ("", "Looking up which workflows are installed.", ()),
    "platform_describe_workflow": (
        "Reading how the {value} workflow is put together.",
        "Reading how a workflow is put together.",
        ("slug", "workflow", "name"),
    ),
    "platform_ls": (
        "Listing the files under {value}.",
        "Listing a workflow's files.",
        ("path", "directory", "dir"),
    ),
    "platform_read_file": (
        "Reading {value}.",
        "Reading a workflow's file.",
        ("path", "file", "filename"),
    ),
    "platform_grep": (
        'Searching the workflow\'s files for "{value}".',
        "Searching the workflow's files.",
        ("pattern", "query", "q", "text"),
    ),
    # No argument is declared, and that is the decision rather than an
    # omission: a recipient address is personal data, and a live progress
    # panel is a surface a customer can be looking at.
    "send_email": ("", "Sending the email.", ()),
    "session_identity": ("", "Checking who is asking.", ()),
    "validate_workflow": ("", "Checking the workflow document for problems.", ()),
    # --- the memory tools (`memory.py`) -----------------------------------
    # The fact itself is never shown: it is the user's own words being filed,
    # and a progress panel is not where somebody should first learn what was
    # remembered about them. `search_memory` earns its entry twice over — the
    # keyword floor reads "search" and says "Searching the data.", which is
    # the wrong claim about where it looked.
    "save_memory": ("", "Remembering that for next time.", ()),
    "search_memory": (
        'Looking through what it remembers about "{value}".',
        "Looking through what it remembers.",
        ("query", "q", "text"),
    ),
    "forget_memory": ("", "Forgetting something it had remembered.", ()),
    # --- the deep-agent harness's own stack --------------------------------
    # `create_deep_agent` pre-assembles these, so every `DeepAgentNode` has
    # them whether or not its author added a tool. They are the platform's,
    # not a package's — which is why they belong in this table and a
    # package's own tools do not. Measured on a live MCP run
    # (`launch-readiness/112`): three of the fourteen lines in one card's
    # stack were `"Calling a tool."`, and all three were these.
    #
    # **None of these declares an argument, and that is the decision.** Caught
    # on the live MCP run this table was verified against: `read_file`
    # declared `file_path`, and what reached the customer chat was
    # `Reading /offload/mcp_list_lenses/call_eeR8/3LoOli2BeA5Cqk4p6ik.txt.`
    # A path on this filesystem is never a path a person named — it is the
    # harness's own scratch space, or an offload envelope this platform wrote
    # — so it is the base's "a lens id they have never met" exactly, and the
    # per-tool declaration that is supposed to overrule that reasoning has
    # nothing better to declare. The developer-facing `code_*` and
    # `platform_*` file tools DO name theirs: those paths are a repository a
    # developer asked about, which is a value they have met.
    "ls": ("", "Listing the files it is working with.", ()),
    "read_file": ("", "Reading a file it has open.", ()),
    "write_file": ("", "Writing a file.", ()),
    "edit_file": ("", "Editing a file.", ()),
    "glob": ("", "Looking for matching files.", ()),
    "grep": ("", "Searching its files.", ()),
    "task": ("", "Handing part of the work to a helper.", ()),
    "write_todos": ("", "Planning the steps it will take.", ()),
}

#: The panel's own ceiling, shared with `narration.py`'s `_MAX_NARRATION_LEN`.
#: A sentence longer than this loses its argument rather than being cut: the
#: bare form is always true, and a half-shown value is not.
_MAX_SENTENCE_LEN = 80

#: Every tool name this table can speak for. Exported so a test can walk it
#: rather than re-listing it, and so the count in a document has a way to fail.
TOOL_NAMES: tuple[str, ...] = tuple(sorted(_TABLE))


def describe_tool_call(name: str, args: Mapping[str, Any] | None = None) -> str | None:
    """One sentence for this call, or `None` when the table has never met it.

    `None` rather than a guess: the caller's own keyword floor is a better
    answer for an unknown tool than a sentence this table would be inventing,
    and "I do not know this tool" is a state worth keeping distinguishable.
    """
    entry = _TABLE.get((name or "").strip())
    if entry is None:
        return None
    with_value, bare, keys = entry
    if with_value and keys:
        value = _usable_value(args, keys)
        if value is not None:
            sentence = with_value.format(value=value)
            # A long-but-legal value can still push a short sentence past the
            # panel's ceiling. Dropping back to the bare form is the honest
            # move — it says less, and everything it says is true.
            if len(sentence) <= _MAX_SENTENCE_LEN:
                return sentence
    return bare


def _usable_value(args: Mapping[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    """The first declared argument that is safe to show, or `None`.

    Safe means: present, a plain string, non-empty once stripped, single-line,
    and short enough to show whole. Everything else is dropped — never
    stringified, never shortened.
    """
    if not args:
        return None
    for key in keys:
        raw = args.get(key)
        if not isinstance(raw, str):
            continue
        value = raw.strip()
        if not value or "\n" in value or "\r" in value:
            continue
        if len(value) > _MAX_VALUE_LEN:
            continue
        return value
    return None
