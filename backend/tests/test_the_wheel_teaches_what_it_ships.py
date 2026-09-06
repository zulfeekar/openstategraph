"""A stranger's agent learns the principles, not only the shape.

`install-experience/25`. The wheel carried 23 example packages, three
templates and every `AGENTS.md` beside them, and carried **neither `docs/`
nor `CLAUDE.md`**. So an agent opened on a stranger's project could learn
what a package *looks like* and could not learn how this project *builds*
one: it would produce something that runs and does not match the rules —
a router with the output contract in an editable field, a second engine
where a registration was wanted, a `answer` key two node types write.

For a stranger the wheel **is** the product, so the material has to travel
in it. A wheel cannot write into a project at install time and must not try
— the format is defined as an unpack, with no hook to run (PEP 427 / the
binary distribution format specification: *"a wheel file may be installed by
simply unpacking into site-packages with the standard 'unzip' tool"*, and
*"Wheel does not contain setup.py or setup.cfg"*). That is a property worth
keeping, not a limitation to route around: a distribution that writes into
your repository on install is the supply-chain shape. So the split is the
one every sanctioned mechanism uses — **the distribution carries the
material, a console script the user runs puts it where their agent looks**.

## What this file gates

The brief's danger is not that it is wrong today. It is that it is a
**second copy of the principles**, which is the duplication defect this
repository names more often than any other. So:

- the lexicon section is **derived** — regenerated here out of `CLAUDE.md`
  and compared byte for byte, exactly as `docs/openapi.json` is compared
  against the app that generates it;
- every rule the brief quotes must appear **verbatim** in `CLAUDE.md`;
- every file the brief names must **exist**;
- and the bytes `init` writes into a project must be the bytes that ship,
  never a second rendering.

What is *not* pinned, said plainly because a gate nobody states the limits
of is a gate people over-trust: the connective prose between those quotes is
hand-written and can rot. It was kept to the minimum a machine needs to act
on the quotes, and it names no version, no count and no number that could be
derived instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openstategraph import agent_brief

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
CLAUDE_MD = REPO / "CLAUDE.md"


# ------------------------------------------------------------------ derive


def _settled_vocabulary(text: str) -> str:
    """The three bullets under `Settled vocabulary:` in `CLAUDE.md`."""
    lines = text.splitlines()
    start = lines.index("Settled vocabulary:") + 1
    end = start
    while end < len(lines) and lines[end].startswith("- "):
        end += 1
    return "\n".join(lines[start:end])


def _user_facing_table(text: str) -> str:
    """The user-facing word table, header row through its last row."""
    lines = text.splitlines()
    header = "| User-facing word | Means | Must never mean |"
    start = lines.index(header)
    end = start
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    return "\n".join(lines[start:end])


def lexicon_block(claude_md: str) -> str:
    """The brief's lexicon section, derived. The one renderer."""
    return _settled_vocabulary(claude_md) + "\n\n" + _user_facing_table(claude_md)


# ------------------------------------------------------------------ tests


def test_the_brief_travels_in_the_package() -> None:
    """Inside `openstategraph/`, so it is ordinary package data and a wheel
    carries it — the same reason `templates/` lives there."""
    assert agent_brief.BRIEF.is_file()
    assert agent_brief.BRIEF.parent.name == "openstategraph"
    assert agent_brief.brief_text().strip()


def test_the_lexicon_is_derived_from_claude_md() -> None:
    """Not transcribed. Regenerate and compare; a `CLAUDE.md` edit to either
    the bullets or the table fails here with the replacement in the diff."""
    expected = lexicon_block(CLAUDE_MD.read_text())
    assert expected in agent_brief.brief_text(), (
        "the brief's lexicon has drifted from CLAUDE.md. Replace the block "
        "between the lexicon markers with:\n\n" + expected
    )


#: Every rule the brief states as this project's law. Each must be a
#: substring of `CLAUDE.md` — the brief quotes, it never paraphrases.
QUOTED_RULES = (
    "TDD. Tests before implementation.",
    "Interface → Abstract → Base → Concrete",
    "never by editing the engine",
    "Cardinality belongs to the port, not the node",
    "Never put a non-finite number in a serialisable field",
    "A state key more than one node type can write needs a named reducer",
    "Expressions are a JSON AST, never host-language code.",
    "We are a compiler, not a runtime",
    "Never write an execution engine.",
    "this platform cannot do that yet",
)


@pytest.mark.parametrize("rule", QUOTED_RULES)
def test_every_rule_the_brief_quotes_is_in_claude_md(rule: str) -> None:
    claude = CLAUDE_MD.read_text()
    assert rule in claude, f"{rule!r} is not in CLAUDE.md — the brief invented it"
    assert rule in agent_brief.brief_text(), f"{rule!r} left the brief; drop it here too"


def test_every_file_the_brief_names_exists() -> None:
    """A brief that sends an agent to a page that is not there is worse than
    one that sends it nowhere."""
    named = set(re.findall(r"`(docs/[A-Za-z0-9_./-]+)`", agent_brief.brief_text()))
    assert named, "the brief names no reference material at all"
    missing = sorted(name for name in named if not (REPO / name).exists())
    assert not missing, f"the brief names files this repository does not have: {missing}"


def test_the_brief_states_no_version() -> None:
    """No number typed into prose that a command already answers."""
    from openstategraph import __version__

    assert __version__ not in agent_brief.brief_text()


# ------------------------------------------------------- what init writes


def test_the_block_is_the_shipped_bytes(tmp_path: Path) -> None:
    """Not a second rendering. What lands in the project between the markers
    is `agent_brief.md` itself, so an upgrade delivers the new brief and
    nothing can drift in between."""
    agent_brief.write_into(tmp_path)
    written = (tmp_path / "AGENTS.md").read_text()
    body = written.split(agent_brief.MARKER_START)[1].split(agent_brief.MARKER_END)[0]
    assert body.strip() == agent_brief.brief_text().strip()


def test_a_fresh_project_gets_the_brief(tmp_path: Path) -> None:
    from openstategraph.scaffold import init_project

    result = init_project(tmp_path / "proj", label="proj")
    assert result.agents_md.read_text().startswith(agent_brief.MARKER_START)
    assert result.agents_md in result.created
    assert result.agents_md_action == "created"


def test_running_it_twice_changes_nothing(tmp_path: Path) -> None:
    """Idempotent: the second pass finds the block current and writes no byte."""
    from openstategraph.scaffold import init_project

    first = init_project(tmp_path / "proj", label="proj")
    before = first.agents_md.read_bytes()
    second = init_project(tmp_path / "proj", label="proj", force=True)
    assert second.agents_md.read_bytes() == before
    assert second.agents_md_action == "current"
    assert second.agents_md not in second.created


def test_an_existing_agents_md_keeps_every_word_it_had(tmp_path: Path) -> None:
    """The block is *added*. Nothing outside the markers is ever touched —
    the same rule `init` already follows for `.gitignore`."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "AGENTS.md").write_text("# House rules\n\nRun `make check`.\n")
    from openstategraph.scaffold import init_project

    result = init_project(project, label="proj", force=True)
    text = result.agents_md.read_text()
    assert "# House rules" in text and "Run `make check`." in text
    assert agent_brief.brief_text().strip() in text
    assert result.agents_md_action == "added"


def test_a_stale_block_is_replaced_and_its_neighbours_are_not(tmp_path: Path) -> None:
    """An upgrade has to be able to deliver a new brief, and the markers are
    what make that honest: inside them is generated, outside them is yours."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "AGENTS.md").write_text(
        f"before\n\n{agent_brief.MARKER_START}\nan old brief\n{agent_brief.MARKER_END}\n\nafter\n"
    )
    from openstategraph.scaffold import init_project

    result = init_project(project, label="proj", force=True)
    text = result.agents_md.read_text()
    assert text.startswith("before")
    assert text.rstrip().endswith("after")
    assert "an old brief" not in text
    assert agent_brief.brief_text().strip() in text
    assert result.agents_md_action == "refreshed"
