"""The rules the package carries, and the one place they are read from.

`osg-agent-experience/25`. This repository's `CLAUDE.md` is the long form and
is **not** shipped: it is full of this checkout's own ticket ids, module
censuses and dated corrections, none of which mean anything inside somebody
else's project. The distribution carries `engineering_rules.md` instead — the
same non-negotiables, a dozen lines a section — and
`backend/tests/test_engineering_rules_match_claude_md.py` pins every section
of it to a section of the long form, so a rule cannot appear here that the
platform never wrote down.

One module, so the text has one reader. The MCP tool wraps this; the skill
sheet's command-line door gets a generated copy written by `init` (slice 5).
A second `read_text` somewhere else is how the two would drift.
"""

from __future__ import annotations

from pathlib import Path

#: Package data, beside this module — the same idiom `agent_brief.py` uses.
ENGINEERING_RULES: Path = Path(__file__).resolve().parent / "engineering_rules.md"


def read_engineering_rules() -> str:
    """The rules text, verbatim."""
    return ENGINEERING_RULES.read_text(encoding="utf-8")


__all__ = ["ENGINEERING_RULES", "read_engineering_rules"]
