"""Reading one declared field out of a node's saved `data`, tolerantly.

A document is JSON a user edited, so a field the schema declares as a string
can arrive as `None`, as a number, or not at all — and every reader of it wants
the same thing: the string, or a default, never an exception. That is one
sentence and one reason to change, which is why this is a module rather than a
private helper on whichever caller happened to need it first.

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
