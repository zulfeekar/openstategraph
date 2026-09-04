"""The package's short form of the architecture rules, held against the long one.

`osg-agent-experience/25`, slice 1. A coding agent that has installed the wheel
has no `CLAUDE.md` — that file is this repository's, not the distribution's, and
shipping it would hand a stranger's project a document full of this checkout's
own ticket ids and module censuses. So the package carries
`openstategraph/engineering_rules.md`: the same non-negotiables, short form,
served over MCP by `get_engineering_rules`.

Two documents saying the same thing is exactly the drift this repository's own
rules warn about. What is pinned here is the **section list**, not the bodies:

- every `##` heading in the rules file names a section that exists in
  `CLAUDE.md`, so a rule cannot be invented here that the long form never made;
- the rules file still names the things the sheet sends an agent here to read —
  the ladder, registries, TDD, port cardinality, and the one the owner
  clarified on 2026-09-04: *never invent a node type the registry does not
  know* (making a new one is fine, through the family's base, registered).

Bodies are **meant** to differ — the package's version is a dozen lines where
`CLAUDE.md` argues for a page — so nothing here compares prose. That is the
recorded cost (`03-program-design.md`, least-confident decision 3): a body that
drifts in meaning is caught by review, not by this file.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = ROOT / "CLAUDE.md"
RULES = ROOT / "backend" / "openstategraph" / "engineering_rules.md"

_HEADING = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)


def _normalise(heading: str) -> str:
    """Case-insensitive and punctuation-tolerant.

    `CLAUDE.md` writes `### Cardinality belongs to the port, not the node` and
    the short form writes `## Cardinality belongs to the port`; an em dash, a
    `*bold*` word or an arrow must not be the thing that decides whether two
    headings are the same heading.
    """
    return " ".join(re.sub(r"[^0-9a-z]+", " ", heading.lower()).split())


def _headings(text: str) -> list[tuple[int, str]]:
    return [(len(m.group(1)), m.group(2)) for m in _HEADING.finditer(text)]


def test_both_documents_were_found() -> None:
    """The guard every gate written this way needs."""
    assert CLAUDE_MD.is_file()
    assert RULES.is_file(), (
        "the package ships no `engineering_rules.md`, so `get_engineering_rules` "
        "has nothing to serve"
    )


def test_every_rules_section_names_a_section_of_claude_md() -> None:
    long_form = [_normalise(text) for _, text in _headings(CLAUDE_MD.read_text(encoding="utf-8"))]
    short_form = [
        text for level, text in _headings(RULES.read_text(encoding="utf-8")) if level == 2
    ]

    assert short_form, "the rules file declares no `##` sections"
    orphans = [
        text
        for text in short_form
        if not any(_normalise(text) in candidate for candidate in long_form)
    ]
    assert not orphans, (
        "these sections of `engineering_rules.md` name no section of `CLAUDE.md`, "
        "so the package is telling an adopter a rule this project never wrote "
        f"down: {orphans}"
    )


def test_the_rules_name_what_the_sheet_sends_an_agent_here_to_read() -> None:
    text = RULES.read_text(encoding="utf-8").lower()

    for phrase in (
        "abstract",
        "registry",
        "maxconnections",
        "test",
        "never invent a node type",
    ):
        assert phrase in text, f"`engineering_rules.md` never mentions {phrase!r}"


def test_the_no_invented_type_rule_states_the_way_out() -> None:
    """The owner's clarification, 2026-09-04. *Never invent a type the registry
    does not know* is not *never make a new one* — a rule read as the second
    stops an agent building the thing the developer asked for. The section has
    to carry the extension path or it teaches the wrong lesson."""
    text = RULES.read_text(encoding="utf-8").lower()

    assert "never invent a node type" in text
    assert "register" in text
    assert "building-an-atom" in text, "the way out names no pipeline to follow"


def test_no_section_of_the_rules_is_longer_than_a_dozen_lines() -> None:
    """The short form is the whole point: a rules file an agent will not read
    is a rules file that changes nothing. `CLAUDE.md` stays the long form, and
    it is eleven times longer than this file for exactly the reasons it
    argues at length and this one states."""
    text = RULES.read_text(encoding="utf-8")
    # Any level, not just `##`: a subsection is a section, and counting one
    # inside its parent would let a page-long `###` hide under a short `##`.
    sections = re.split(r"^#{2,4} ", text, flags=re.MULTILINE)[1:]

    overlong = [
        section.splitlines()[0]
        for section in sections
        if len([line for line in section.splitlines() if line.strip()]) > 12
    ]
    assert not overlong, (
        f"these sections run past a dozen non-blank lines: {overlong}. The long "
        "form is `CLAUDE.md`; this file is the one an agent reads before every "
        "build."
    )
