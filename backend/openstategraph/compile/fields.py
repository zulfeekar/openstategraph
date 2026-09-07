"""Reading one declared field out of a node's saved `data`, tolerantly.

A document is JSON a user edited, so a field the schema declares as a string
can arrive as `None`, as a number, or not at all — and every reader of it wants
the same thing: the string, or a default, never an exception. That is one
sentence and one reason to change, which is why this is a module rather than a
private helper on whichever caller happened to need it first.

`_replaces_rules` and `_summarizes` joined it from `compile/node_runtime.py`
in the `docs-and-gaps/03` split. They are the same sentence with a name: one
declared field, read out of a node's saved `data`, tolerantly. They were in
the runtime's file because four node families call them, which is a reason
for four families to import them and not a reason for them to live beside
the builders. Neither adds an import, so this module's place on the
emitter's prelude roster is untouched.

It is `CLAUDE.md`'s "read tolerantly" rule applied to the *document* side, the
mirror of `messages.content_text` on the provider side, and like that one it
imports nothing from this package — which is what lets `compile/state.py` sit
on the emitter's prelude roster (`export-and-eject/16`). `_text` lived in
`compile/context.py` until then, and its one cross-module reader was the state
module; the seam that module's own docstring draws — *state readers here,
document readers over there* — was the reason not to answer this by moving a
document reader into it.
"""

from __future__ import annotations

from typing import Any


def _text(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key)
    return value if isinstance(value, str) else default


def _replaces_rules(data: dict[str, Any]) -> bool:
    """`rulesMode` — the one extend/replace switch every prompted node has.

    `criteriaMode` is the grader's older spelling of the same field and is
    still read, so documents saved before the skill layer keep their behaviour
    exactly (`docs/decisions/skill-layer.md` records the generalisation and
    the condition for dropping this fallback). It is a *fallback*, never a
    second setting: `rulesMode` wins wherever both appear.
    """
    return (_text(data, "rulesMode") or _text(data, "criteriaMode")) == "replace"


def _summarizes(data: dict[str, Any]) -> bool:
    """Whether this agent manages its own context. **Default: yes.**

    Absent means on, which is the owner's decision of 2026-08-15 and is what
    makes the 22 shipped examples — none of which mentions the key — summarize
    at all. An explicit `false` still means off, and that is not a rounding
    error: the editor materialises every field default into `data`, so a
    document saved before the default flipped carries a literal
    `"summarize": false`. Reading absent-as-on and false-as-off keeps the
    promise `withMigratedRulesMode` states on the TypeScript side — opening a
    document must never change what it does.
    """
    value = data.get("summarize")
    return True if value is None else bool(value)


def branch_entries(raw: Any) -> list[Any]:
    """The router's branch table, in either of its two saved forms.

    v1 documents store a newline-separated string of names; v2 (ticket 20)
    stores ``[{id, name}]`` so edges survive renames. Anything unusable
    collapses to a single ``"default"`` branch rather than raising — a router
    is the entry point, and refusing to compile is a total outage where a
    misroute is recoverable. `Branch.of` handles per-entry normalisation.

    It lived in `compile/context.py` until `osg-agent-experience/80`, which
    needed it in `workflow_compiler` — the module `context` imports. Moved
    rather than copied, for the reason the branch table has exactly one
    reading: a second one would drift the day a third saved form arrives.
    `context` re-exports it, so no caller moved.
    """
    if isinstance(raw, str):
        names = [line.strip() for line in raw.split("\n") if line.strip()]
        return names or ["default"]
    if isinstance(raw, list):
        entries = [entry for entry in raw if isinstance(entry, (str, dict))]
        return entries or ["default"]
    return ["default"]


def branch_ids_by_spelling(raw: Any) -> dict[str, str]:
    """`{how it might be written: the branch id}` for one node's branch table.

    Tolerant in reading, strict in trusting (`CLAUDE.md`). A function may
    answer with the branch's **name**, which is what a developer writes and
    what the card shows, or with its stable **id**, which is what the port and
    the edge carry — both are in the document, so both are real spellings of
    the same branch and refusing one would be a trap rather than a rule.
    Case and surrounding whitespace are forgiven for the same reason.

    Nothing else is. A name outside this table resolves to no branch at all
    and the caller takes its fallback, which is the strict half: the tolerance
    widens how a *declared* branch may be spelled, never what counts as one.

    Declaration order decides a tie, so a table whose name and id collide
    across two rows resolves to the row a reader meets first.

    `route.check`'s reading of a function's answer and the compiler's reading
    of a classifier's `fallback` field are the same question — which branch is
    this string? — so they are one function (`osg-agent-experience/80`).
    """
    table: dict[str, str] = {}
    for entry in branch_entries(raw):
        if isinstance(entry, dict):
            branch_id = str(entry.get("id") or entry.get("name") or "")
            name = str(entry.get("name") or entry.get("id") or "")
        else:
            branch_id = name = str(entry)
        if not branch_id:
            continue
        table.setdefault(name.strip().casefold(), branch_id)
        table.setdefault(branch_id.strip().casefold(), branch_id)
    return table
