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
import json
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
        "shapes.md",
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


def test_the_loop_says_where_a_tool_binding_is_visible() -> None:
    """`osg-agent-experience/41`. A tool binds *into* an agent, so it produces
    no control flow and `graph` cannot draw it — an unbound tool looks like a
    correct picture. Only `validate`'s `Tool bindings:` line says, and a sheet
    that does not point at it sends an agent to the diagram."""
    page = (REFERENCES / "build-loop.md").read_text(encoding="utf-8")

    assert "Tool bindings:" in page
    assert "openstategraph graph` cannot show" in page
    # The other half of that ticket: the allowlist path is a refusal, not a
    # convention, and the sheet says so where somebody is wiring the tool.
    assert "outside it is refused" in page


class TestTheSizeGate:
    """`osg-agent-experience/31`. Measured, not opined: a one-field ask cost
    8 developer questions and 20 agent calls against this sheet followed
    literally, 6.7x the same ask with no skill at all
    (`.scratch/osg-agent-experience/ceremony-measured.md`).

    The cause was **order**. The sizing rule existed and could not fire: the
    interview ran first and ended with a size, so all eight dimensions were
    spent before the size that would have exempted them was chosen. So the
    owner's rule (round 5) is a rule about position — *size first; size
    decides the ritual, never the rules* — and a rule about position is
    exactly the kind a test can hold.

    Pinned here: that the size gate precedes the interview, that each of the
    three sizes names its own ritual, and that the four engineering
    non-negotiables are stated once **above** the sizes so no size can be read
    as exempting them. Still not pinned: the wording of any of it.
    """

    HEADING = re.compile(r"^##\s+\d+\.\s+(.*)$", re.MULTILINE)

    def _headings(self) -> list[str]:
        return [m.group(1).strip() for m in self.HEADING.finditer(SHEET.read_text(encoding="utf-8"))]

    def _index_of(self, needle: str) -> int:
        for position, heading in enumerate(self._headings()):
            if needle in heading.lower():
                return position
        raise AssertionError(f"no numbered section of the sheet mentions {needle!r}: {self._headings()}")

    def test_the_size_gate_is_a_step_of_its_own(self) -> None:
        assert self._index_of("big") >= 0

    def test_the_size_gate_precedes_the_interview(self) -> None:
        """The whole defect, as one assertion."""
        assert self._index_of("big") < self._index_of("interview"), (
            "the interview runs before the size is chosen, which is the ceremony "
            "defect measured in ticket 31: eight dimensions spent to discover a "
            "size that would have exempted them"
        )

    def test_the_size_gate_comes_straight_after_the_routing_check(self) -> None:
        """Before the ground rules, before the vocabulary, before anything the
        agent has to read: the size is decided from the ask itself."""
        assert self._index_of("big") < self._index_of("ground rules")

    def test_each_size_names_the_ritual_it_carries(self) -> None:
        text = SHEET.read_text(encoding="utf-8")
        for word in ("**tweak**", "**change**", "**feature or slice**"):
            assert word in text, f"the sizing table does not name {word}"

        tweak = next(line for line in text.splitlines() if "**tweak**" in line)
        change = next(line for line in text.splitlines() if "**change**" in line)
        feature = next(line for line in text.splitlines() if "**feature or slice**" in line)

        assert "one confirming question" in tweak and "no break" in tweak, (
            f"a tweak's ritual is not stated on its own row: {tweak}"
        )
        assert "break" in change, f"a change keeps the deliberate break, and its row must say so: {change}"
        assert "interview" in feature, f"only a feature or slice buys the interview: {feature}"

    def test_the_non_negotiables_are_stated_once_above_the_sizes(self) -> None:
        """Size decides the ritual, never the rules — so the rules are stated
        before the first size word, where no size can appear to exempt them."""
        text = SHEET.read_text(encoding="utf-8")
        #: The paragraph, not the line: this sheet is hard-wrapped, so a
        #: line-at-a-time reading would pin where the author broke a sentence.
        paragraph = next(
            (block for block in text.split("\n\n") if "Non-negotiable at every size" in block),
            None,
        )
        assert paragraph is not None, "the sheet never states what holds at every size"
        assert text.index(paragraph) < text.index("**tweak**"), (
            "the non-negotiables are stated below the sizes, where a size can be read as exempting them"
        )

        for named in ("rules", "register", "test", "card"):
            assert named in paragraph.lower(), (
                f"the non-negotiables paragraph never names {named!r}: {paragraph}"
            )


@pytest.mark.parametrize("page", sorted(_pages()), ids=lambda p: p.name)
def test_no_page_asks_for_this_repositorys_own_rituals(page: Path) -> None:
    """A handoff file and a ticket markdown file are how *this* repository runs
    unattended sessions. A stranger's agent has neither, and a sheet that asks
    for one sends it to write a file nobody will ever read
    (`osg-agent-experience/31`, the owner's rule)."""
    offenders = [
        line.strip()
        for line in page.read_text(encoding="utf-8").splitlines()
        if re.search(r"handoff|\.scratch|ticket (?:file|markdown)", line, re.IGNORECASE)
    ]

    assert not offenders, (
        f"{page.name} asks a stranger's agent for one of this repository's own rituals: {offenders}"
    )


class TestTheCliDoorCanAskWhatAFieldIs:
    """`osg-agent-experience/33`. Both doors are supposed to answer the sheet's
    first rule — *read the vocabulary before composing anything* — and one of
    them could not: the CLI row of the routing table sent the agent to read the
    installed `compile/port_specs.json` by eye. A Haiku agent that did not read
    it invented a `systemPrompt` on a classifier whose fields are `rules`,
    `branches`, `fallback` and `matchMode`.

    Two claims are pinned, and the second is the one that changes behaviour: a
    verb exists, **and** the sheet tells the agent to write the field list down
    before it writes `data`. A small model does what it is told to quote."""

    def _text(self) -> str:
        return SHEET.read_text(encoding="utf-8")

    def test_the_cli_row_of_the_routing_table_names_the_verb(self) -> None:
        row = next((line for line in self._text().splitlines() if "what can be composed" in line), None)
        assert row is not None, "the routing table lost its vocabulary row"
        assert "openstategraph nodes" in row, f"the CLI door still has no verb for the vocabulary: {row!r}"

    def test_the_verb_the_sheet_names_is_one_argparse_accepts(self) -> None:
        """The other direction. `test_every_command_the_pages_name_is_real`
        covers it for every page; stated here too because this row was a
        filesystem path for as long as the sheet existed."""
        assert "nodes" in _verbs()

    def test_the_ground_rules_require_quoting_the_fields_before_writing_data(self) -> None:
        section = next((block for block in self._text().split("\n\n") if "**The vocabulary**" in block), None)
        assert section is not None, "the sheet no longer opens with the two reads"
        assert "quote" in section.lower(), (
            "the sheet asks the agent to read the vocabulary and never to write any "
            "of it down; reading is what the Haiku agent believed it had done"
        )
        assert "`data`" in section, f"the instruction does not say before *what*: {section!r}"


class TestTheRecommendedShapeStep:
    """`osg-agent-experience/49`. The interview asked eight questions, filed
    six cards and never once said *what shape this concept should be*. The
    owner's concept was built as sixty-six nodes on one canvas — fifteen
    specialists, fifteen guards, fifteen graders, fifteen outputs — and a
    ten-minute conversation afterwards reached the shape a senior colleague
    would have named before the first card: fifteen packages behind one
    router. Every idiom in that sentence already existed. The sheet knew them
    by name and never said *when to reach for which*.

    Owner's framing, the same day: *"it is not just about lenses; we are
    talking about the product's scalability."* So the step asks the scaling
    question — **what in this concept is going to multiply?** — and reads the
    answer against a catalogue whose rules a test can run.

    Three claims are pinned here and the third is the one that makes the
    recommendation checkable rather than a mood:

    - the step exists, after the interview and before the cards are sized and
      filed;
    - every node type the catalogue names is a type the registry knows —
      the sheet's own first rule turned on the sheet's own catalogue;
    - the catalogue's rules, applied to the interview answers the owner's
      concept actually gave, pick *router -> N mounts*. No model runs. The
      table in `shapes.md` is the program.

    On the word *sizing*. The ticket asks for the step "before sizing and
    filing"; the ask-size gate is pinned first by `osg-agent-experience/31`
    and stays there. The sizing this step precedes is the one it can
    precede — the per-card size, model and effort chosen at filing.
    """

    HEADING = re.compile(r"^##\s+\d+\.\s+(.*)$", re.MULTILINE)

    #: `agent.llm`, `route.classifier`. The prefix must be a category the
    #: registry itself declares, derived rather than listed, so an ordinary
    #: dotted filename in prose is not mistaken for a promise about a type.
    DOTTED = re.compile(r"`([a-z][a-z0-9]*\.[a-z][a-z0-9_-]*)`")

    #: The document is not a node type and shares a category's spelling.
    NOT_A_TYPE = {"workflow.json"}

    #: A catalogue rule, as a test can run it: an axis and a count.
    RULE = re.compile(r"^([a-z]+)\s*>=\s*(\d+)$")

    #: The concept, as the interview actually answered it — from a real
    #: transcript, not invented: fifteen specialists, one warehouse holding
    #: forty-two pinned tables, one grain each, a question that can name a
    #: second specialist as a facet, one fact the code checks, one judge that
    #: can say what is wrong, one axis a question may arrive without.
    FIFTEEN_SPECIALISTS = {
        "specialists": 15,
        "sources": 1,
        "tables": 42,
        "parts": 1,
        "teams": 1,
        "tenants": 1,
        "checks": 1,
        "revisions": 1,
        "crossings": 1,
        "gaps": 1,
    }

    #: The discriminating fixture: one domain, and every axis flat.
    ONE_DOMAIN = {"specialists": 1, "sources": 1, "tables": 1}

    def _headings(self) -> list[str]:
        return [m.group(1).strip() for m in self.HEADING.finditer(SHEET.read_text(encoding="utf-8"))]

    def _index_of(self, needle: str) -> int:
        for position, heading in enumerate(self._headings()):
            if needle in heading.lower():
                return position
        raise AssertionError(f"no numbered section of the sheet mentions {needle!r}: {self._headings()}")

    def _catalogue(self) -> str:
        page = REFERENCES / "shapes.md"
        assert page.is_file(), "the catalogue the step reads does not exist"
        return page.read_text(encoding="utf-8")

    def _table(self, first_header_cell: str) -> list[tuple[str, str]]:
        """The rows of the table whose header row opens with that cell."""
        rows: list[tuple[str, str]] = []
        lines = self._catalogue().splitlines()
        for position, line in enumerate(lines):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and cells[0].lower() == first_header_cell:
                for row in lines[position + 2 :]:
                    if not row.strip().startswith("|"):
                        break
                    body = [cell.strip() for cell in row.strip().strip("|").split("|")]
                    if len(body) >= 2:
                        rows.append((body[0], body[1]))
                break
        assert rows, f"the catalogue has no table headed {first_header_cell!r} for a test to read"
        return rows

    def _spine(self, answers: dict[str, int]) -> str:
        """First match wins, and the catalogue says so in the same words."""
        for axis, shape in self._table("multiplies"):
            if axis.lower().startswith("otherwise"):
                return shape
            match = self.RULE.match(axis)
            assert match, f"a catalogue rule a test cannot run: {axis!r}"
            if answers.get(match.group(1), 0) >= int(match.group(2)):
                return shape
        raise AssertionError("the catalogue's rules match nothing and have no otherwise row")

    def _additions(self, answers: dict[str, int]) -> list[str]:
        found = []
        for axis, addition in self._table("also true"):
            match = self.RULE.match(axis)
            assert match, f"a catalogue rule a test cannot run: {axis!r}"
            if answers.get(match.group(1), 0) >= int(match.group(2)):
                found.append(addition)
        return found

    def test_the_step_is_a_numbered_step_of_its_own(self) -> None:
        assert self._index_of("shape") >= 0

    def test_it_follows_the_interview_and_precedes_filing(self) -> None:
        """The whole defect, as one assertion: the cards were filed against a
        shape nobody had named."""
        assert self._index_of("interview") < self._index_of("shape") < self._index_of("filing"), (
            "the shape is recommended somewhere other than between the interview "
            "and the cards, which is the only place it can change what gets built"
        )

    def test_the_step_asks_what_multiplies_and_names_what_it_rejected(self) -> None:
        text = SHEET.read_text(encoding="utf-8")
        section = text[text.index("## 6."):text.index("## 7.")]

        assert "multiply" in section.lower(), (
            "the step never asks the scaling question, which is the owner's whole framing"
        )
        assert "reject" in section.lower(), (
            "a recommendation with no rejected alternatives is an assertion; the "
            "developer cannot weigh what they were not shown"
        )
        assert "references/shapes.md" in section, "the step never says where the catalogue is"

    def test_every_node_type_the_catalogue_names_is_one_the_registry_knows(self) -> None:
        """The sheet's own first rule, turned on the sheet's own catalogue. A
        shape recommended out of a type nobody registered is the invented node
        type, arriving one level up where no validator looks."""
        specs = json.loads((ROOT / "backend" / "openstategraph" / "compile" / "port_specs.json").read_text())
        known = {node["type"] for node in specs["node_types"]}
        categories = {name.split(".", 1)[0] for name in known}

        claimed = {
            name
            for name in self.DOTTED.findall(self._catalogue())
            if name.split(".", 1)[0] in categories and name not in self.NOT_A_TYPE
        }
        assert claimed, "the catalogue recommends shapes and names no node type at all"

        unknown = sorted(name for name in claimed if name not in known)
        assert not unknown, f"the catalogue recommends node types the registry does not know: {unknown}"

    def test_the_catalogue_recommends_router_and_mounts_for_the_owners_concept(self) -> None:
        """The ticket's own done-when, as rules rather than as a model: the
        interview answers that produced sixty-six nodes on one canvas."""
        spine = self._spine(self.FIFTEEN_SPECIALISTS).lower()

        assert "router" in spine and "mount" in spine, (
            f"the catalogue's rules read the owner's own answers and picked {spine!r}; "
            "fifteen specialists behind one router is the shape the brainstorm reached"
        )

    def test_the_same_rules_leave_a_single_domain_concept_as_one_agent(self) -> None:
        """The rules discriminate. A catalogue that answers *router* to
        everything has recommended nothing."""
        spine = self._spine(self.ONE_DOMAIN).lower()

        assert "one agent" in spine, f"one domain, and the catalogue still reaches for a router: {spine!r}"

    def test_the_additions_carry_the_facet_and_the_gate(self) -> None:
        """The spine is not the whole recommendation. The owner's concept also
        crosses two specialists in one question and has a fact the code can
        check; both were reached in the brainstorm and both are add-ons rather
        than rival shapes."""
        additions = " | ".join(self._additions(self.FIFTEEN_SPECIALISTS)).lower()

        assert "facet" in additions, additions
        assert "guard" in additions or "gate" in additions, additions


class TestTheClosingBrief:
    """`osg-agent-experience/52`. The agent files the cards, builds them, moves
    them to `finished` — and stops. The developer opens the board, the folder
    and the transcript and pieces the session together themselves. The owner,
    2026-09-05: *"once the coding agent completes, give a brief back to the
    developer: what has been done and what the next steps are."*

    Three claims are pinned, and the third is the one that keeps the brief
    honest rather than merely present:

    - the step exists, and it comes **after** the cards are filed and after
      the build loop — a brief written before the work is a plan;
    - it names the `graph` verb, so the picture the developer reads is the one
      the compiler drew from the document that actually compiled;
    - it says in so many words that a diagram of what **exists** is never
      hand-drawn. Owner's decision 17, and this is the step where breaking it
      is most tempting: the agent has just built the thing and knows the shape
      by heart, so drawing it from memory costs nothing and gives the reader
      two pictures with no way to tell which one lied.

    Not pinned: the wording of the brief's own bullets, or its length in
    lines. The sheet states twenty; a test counting the lines of a document
    that does not exist yet would be measuring the sentence rather than the
    behaviour.
    """

    HEADING = re.compile(r"^##\s+\d+\.\s+(.*)$", re.MULTILINE)

    def _text(self) -> str:
        return SHEET.read_text(encoding="utf-8")

    def _headings(self) -> list[str]:
        return [m.group(1).strip() for m in self.HEADING.finditer(self._text())]

    def _index_of(self, needle: str) -> int:
        for position, heading in enumerate(self._headings()):
            if needle in heading.lower():
                return position
        raise AssertionError(f"no numbered section of the sheet mentions {needle!r}: {self._headings()}")

    def _section(self) -> str:
        """The brief's own step, from its heading to the next one."""
        text = self._text()
        headings = list(self.HEADING.finditer(text))
        for position, match in enumerate(headings):
            if "brief" in match.group(1).lower():
                end = headings[position + 1].start() if position + 1 < len(headings) else len(text)
                return text[match.start() : end]
        raise AssertionError(f"the sheet has no closing-brief step: {self._headings()}")

    def test_the_step_is_a_numbered_step_of_its_own(self) -> None:
        assert self._index_of("brief") >= 0

    def test_it_comes_after_the_cards_are_filed_and_after_the_build_loop(self) -> None:
        """The whole defect, as one assertion: the session ended with a stage
        change and nothing addressed to a person."""
        assert self._index_of("filing") < self._index_of("brief"), (
            "the brief is written before the cards exist, which makes it a plan"
        )
        assert self._index_of("build loop") < self._index_of("brief"), (
            "the brief is written before anything was built, so it reports intentions"
        )

    def test_the_brief_names_the_graph_verb(self) -> None:
        section = self._section()
        assert "openstategraph graph" in section, (
            "the closing step never names the verb that draws the compiled graph, so "
            f"the agent has to invent a picture: {section}"
        )

    def test_a_diagram_of_what_exists_is_never_hand_drawn(self) -> None:
        section = self._section().lower()
        assert "hand-draw" in section or "hand draw" in section or "hand-drawn" in section, (
            "the closing step never forbids hand-drawing the diagram, which is the "
            "one instruction the agent is most likely to skip here"
        )
        assert "never" in section, (
            "the closing step mentions hand-drawing without forbidding it"
        )

    def test_the_brief_is_left_behind_for_the_next_agent(self) -> None:
        """A brief that lives only in a transcript is a brief the next session
        cannot read — which is the same defect one turn later."""
        assert "AGENTS.md" in self._section(), (
            "the brief is spoken and never written down beside the workflow it describes"
        )


class TestTheProposedName:
    """`osg-agent-experience/35`. An agent handed a concept built the workflow
    and saved it: the editor said *Untitled*, and the folder was whatever the
    agent happened to type. The owner, 2026-09-04: *"instead of Untitled the
    agent can suggest a name from the concept itself — a sensible short name
    related to the concept."*

    Cosmetic on the document, permanent on the folder. A slug is minted from
    the name at the first save and frozen, because a slug that moves renames a
    directory — so the moment to get it right is **before** the first save, not
    after, and there is no later moment at all.

    Pinned here:

    - some numbered step proposes a name, and it is one the developer sees
      before the cards are filed and long before anything is saved;
    - it says what the name *costs* — the slug it would mint,
      `workflows/<slug>/` — because that is the half the developer cannot undo
      and the half an agent would not think to mention;
    - it is **proposed**, never silently chosen. A name an agent picks without
      saying so is the same defect as *Untitled* with better spelling: the
      developer still did not choose their own folder.

    Not pinned: the words of the proposal, or the example names.
    """

    HEADING = re.compile(r"^##\s+\d+\.\s+(.*)$", re.MULTILINE)

    def _sections(self) -> list[tuple[str, str]]:
        text = SHEET.read_text(encoding="utf-8")
        found = list(self.HEADING.finditer(text))
        out = []
        for position, match in enumerate(found):
            end = found[position + 1].start() if position + 1 < len(found) else len(text)
            out.append((match.group(1).strip(), text[match.start() : end]))
        return out

    def _index_of(self, needle: str) -> int:
        for position, (heading, _) in enumerate(self._sections()):
            if needle in heading.lower():
                return position
        raise AssertionError(f"no numbered section of the sheet mentions {needle!r}")

    def _naming_step(self) -> tuple[int, str]:
        """The step that proposes the workflow's name, found by what it does."""
        for position, (_, body) in enumerate(self._sections()):
            lowered = body.lower()
            if "name" in lowered and "slug" in lowered and "propos" in lowered:
                return position, body
        raise AssertionError(
            "no step of the sheet proposes a name for the workflow: the agent saves "
            f"whatever it typed, and the editor prints Untitled. {[h for h, _ in self._sections()]}"
        )

    def test_a_step_proposes_the_workflows_name(self) -> None:
        position, _ = self._naming_step()
        assert position >= 0

    def test_it_is_proposed_before_the_cards_and_before_any_save(self) -> None:
        """The slug is frozen at the first save, so a naming step that runs
        after the build loop is a step that can only apologise."""
        position, _ = self._naming_step()
        assert position <= self._index_of("filing"), (
            "the name is proposed after the cards are filed, by which point the "
            "developer has already agreed to build something nameless"
        )
        assert position < self._index_of("build loop"), (
            "the name is proposed after the build loop, and the first save inside it "
            "has already minted and frozen the slug"
        )

    def test_it_states_the_slug_the_name_would_mint(self) -> None:
        _, body = self._naming_step()
        assert "workflows/<slug>/" in body, (
            "the step proposes a name without saying it mints a directory, which is "
            f"the half the developer cannot change afterwards: {body}"
        )

    def test_the_name_is_proposed_and_never_silently_chosen(self) -> None:
        _, body = self._naming_step()
        lowered = body.lower()
        assert "never" in lowered, (
            "the step suggests a name and does not say the developer gets to refuse it"
        )
        assert "propos" in lowered, lowered
