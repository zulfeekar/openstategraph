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
