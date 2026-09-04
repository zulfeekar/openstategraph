"""The entry sheet's promises, held against the software that has to keep them.

`osg-agent-experience/25`, slice 5. The sheet a stranger's coding agent reads
is the one document in this repository whose every instruction is executed by
something that cannot ask a follow-up question. A tool name it gets wrong is a
call that returns nothing; a CLI verb it invents is a shell error in the middle
of a build the developer is watching.

So the pin is the shape `test_documented_mcp_tool_surface.py` and
`test_documented_cli_surface.py` already use, pointed at the sheet and its
reference pages:

- **Sheet → source.** Every backticked tool name the sheet presents as an MCP
  tool is in `EXPOSED_TOOLS`; every `openstategraph <verb>` it tells an agent
  to type is a verb the real parser accepts.
- **Source → sheet.** For the board verbs specifically, both directions: a
  `kanban_*` tool or a `kanban <sub>` subcommand the sheet never names is a
  door the agent it was written for cannot find. The board is the whole
  mechanism of the loop, so a missing verb there is not a documentation gap,
  it is a step of the procedure with no way to perform it.

Deliberately **not** pinned: the prose. The interview's questions, the
sizing argument, the credits — that is the useful half, and a test demanding
particular sentences tests an author's wording rather than the software.

## The lexicon rule, and its one exemption

`kanban-patrol/24`: nothing shipped may name a skill installed on the owner's
own machine. Crediting a shape is a different act from redistributing
somebody's document, and a sheet that names `<some-tool>` sends a stranger's
agent looking for a file their machine does not have.

The one exemption is the word *grilling*, and it is exempt because this
product owns it independently: `kanban file --kind grilling` is a card kind
(`kanban_store`), a judgement a human must weigh. The rule is therefore
narrowed rather than dropped — the word may appear only on a line that also
says `kind`, which is the sense the product means and the sense a reader
cannot mistake for an instruction to invoke something.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.bundled_skills import BUNDLED_SKILLS, RULES_REFERENCE
from openstategraph.mcp_server import EXPOSED_TOOLS
from openstategraph.skills import SkillDocument

ROOT = Path(__file__).resolve().parents[2]

SHEET = BUNDLED_SKILLS["openstategraph"] / "SKILL.md"
REFERENCES = BUNDLED_SKILLS["openstategraph"] / "references"
READER_PAGE = ROOT / "docs" / "the-openstategraph-skill.md"

#: The sheet's own ceiling, from `03-program-design.md`. A sheet is read in
#: full by every agent that picks it up, on every turn it is loaded; length is
#: the cost the developer pays for a rule they may not need. The long form
#: goes to `references/`, which is read only when the step needs it.
SHEET_LINE_CEILING = 250

#: A backticked name shaped like one of this server's tools. Narrow on
#: purpose, exactly as `test_documented_mcp_tool_surface.py` argues: the pages
#: are full of ordinary code, and a rule wide enough to catch every identifier
#: is a rule with a suppression in its future.
TOOL_IN_PROSE = re.compile(r"`(kanban_\w+|get_node_vocabulary|get_engineering_rules|\w+_workflow(?:_\w+)?)`")

#: `openstategraph init`, `openstategraph kanban triage`. The second word is
#: optional because most commands have no subcommand, and a trailing argument
#: (`openstategraph validate workflows/x`) is resolved by longest match below.
INVOCATION = re.compile(r"openstategraph ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")

#: Skills installed on the owner's machine. Credit the shape, never the name.
FORBIDDEN_NAMES = (
    "ticket-loop-orchestrator",
    "ticket-loop",
    "wayfinder",
    "grill-me",
    "show-me",
    "software-factory",
    "feature-design",
)


def _verbs() -> set[str]:
    """Every command and subcommand the real parser accepts, as typed."""
    found: set[str] = set()

    def walk(parser: argparse.ArgumentParser, prefix: str) -> None:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    found.add(f"{prefix} {name}".strip())
                    walk(sub, f"{prefix} {name}".strip())

    walk(cli.build_parser(), "")
    return found


def _pages() -> dict[Path, str]:
    pages = {SHEET: SHEET.read_text(encoding="utf-8")}
    for page in sorted(REFERENCES.glob("*.md")):
        pages[page] = page.read_text(encoding="utf-8")
    return pages


def test_the_sheet_and_its_references_were_found() -> None:
    """The guard every gate written this way needs: if either side moves, the
    assertions below compare nothing to nothing."""
    assert SHEET.is_file()
    assert REFERENCES.is_dir()
    #: Four pages are written; the fifth — `engineering-rules.md` — is
    #: generated by the installer from the package's own rules file, so it is
    #: deliberately absent here and pinned in `test_bundled_skill_tree.py`.
    assert {page.name for page in REFERENCES.glob("*.md")} == {
        "interview.md",
        "build-loop.md",
        "subagents.md",
        "environments.md",
    }
    assert "engineering-rules" in RULES_REFERENCE
    assert len(EXPOSED_TOOLS) > 5


def test_the_sheet_parses_as_a_skill_document() -> None:
    """An agent's own YAML reader is the first thing that touches this file.
    A sheet it silently skips is a sheet nobody reads."""
    document = SkillDocument.parse(SHEET.read_text(encoding="utf-8"))

    assert document.name == "openstategraph"
    assert document.description
    assert document.body.strip()


def test_the_sheet_stays_under_its_line_ceiling() -> None:
    lines = SHEET.read_text(encoding="utf-8").splitlines()

    assert len(lines) <= SHEET_LINE_CEILING, (
        f"the entry sheet is {len(lines)} lines against a ceiling of {SHEET_LINE_CEILING}; "
        "the long form belongs in references/, which is read only when a step needs it"
    )


@pytest.mark.parametrize("page", sorted(_pages()), ids=lambda p: p.name)
def test_every_tool_the_pages_name_is_exposed(page: Path) -> None:
    text = page.read_text(encoding="utf-8")
    claimed = {match.group(1) for match in TOOL_IN_PROSE.finditer(text)}

    unknown = sorted(name for name in claimed if name not in EXPOSED_TOOLS)
    assert not unknown, (
        f"{page.name} tells an agent to call these and the server registers no such "
        f"tool: {unknown}"
    )


@pytest.mark.parametrize("page", sorted(_pages()), ids=lambda p: p.name)
def test_every_command_the_pages_name_is_real(page: Path) -> None:
    """Longest match wins: `openstategraph validate workflows/x` resolves to
    `validate`, because `validate workflows` is not a subcommand. The one
    exception is `kanban`, whose subcommand is required — a second word there
    must be a real one rather than falling back to the group."""
    text = page.read_text(encoding="utf-8")
    verbs = _verbs()
    bad: list[str] = []
    for match in INVOCATION.finditer(text):
        first, second = match.group(1), match.group(2)
        pair = f"{first} {second}".strip() if second else first
        if pair in verbs:
            continue
        if first == "kanban" and second:
            bad.append(pair)
        elif first not in verbs:
            bad.append(pair)
    assert not bad, f"{page.name} tells an agent to type commands argparse rejects: {bad}"


def test_every_board_tool_and_verb_the_loop_needs_is_named() -> None:
    """The other direction, board only. The loop *is* the board — file,
    triage, attend, stage, show — so a door the pages never name is a step of
    the procedure with no way to perform it."""
    text = "\n".join(_pages().values())

    missing_tools = [name for name in EXPOSED_TOOLS if name.startswith("kanban_") and f"`{name}`" not in text]
    missing_verbs = [
        verb for verb in _verbs() if verb.startswith("kanban ") and f"openstategraph {verb}" not in text
    ]

    assert not missing_tools, f"the board exposes these over MCP and the sheet never names them: {missing_tools}"
    assert not missing_verbs, f"the board has these CLI verbs and the sheet never names them: {missing_verbs}"


@pytest.mark.parametrize("page", sorted(_pages()), ids=lambda p: p.name)
def test_no_page_names_a_skill_from_somebody_elses_machine(page: Path) -> None:
    text = page.read_text(encoding="utf-8")

    named = sorted(name for name in FORBIDDEN_NAMES if name in text)
    assert not named, (
        f"{page.name} names {named} — credit the shape, never the name "
        "(kanban-patrol/24): a stranger's agent has no such file"
    )


@pytest.mark.parametrize("page", sorted(_pages()), ids=lambda p: p.name)
def test_grilling_appears_only_as_a_card_kind(page: Path) -> None:
    """The narrowed half of the lexicon rule. The word is this product's own
    when it names a card kind and somebody else's when it names a procedure."""
    offenders = [
        line.strip()
        for line in page.read_text(encoding="utf-8").splitlines()
        if "grilling" in line and "kind" not in line
    ]

    assert not offenders, (
        f"{page.name} uses `grilling` outside its card-kind sense: {offenders}"
    )


def test_the_readers_page_exists_and_is_indexed() -> None:
    """`docs/README.md` is the only index; a page it does not name is a page
    nobody reaches from the documentation's own front door."""
    assert READER_PAGE.is_file()
    index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "the-openstategraph-skill.md" in index
