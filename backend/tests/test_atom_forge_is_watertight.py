"""`skills/atom-forge` says how many of things it has, and the numbers must be true.

This repository's recorded failure mode is a **number in prose with no way to
fail**: `CLAUDE.md` carried "ten public members" for months while the class had
eleven, and the fix in both languages was a census test rather than a better
paragraph. The skill had the same shape — "eight dimensions", "all eleven
gates", "the 10/10 readiness card" — repeated across the skill, its two
reference files, `docs/building-an-atom.md` and `CLAUDE.md`. Adding a ninth
dimension on 2026-08-18 falsified five sentences at once, in four files, and
nothing failed.

So the counts are pinned here, and the structural properties the 2026-08-18
sweep added are pinned with them: the routing question, the two gate sets, the
two readiness cards, and the "not here" row that stops the scope map
misrouting.

Deliberately a *content* test over markdown. The skill is agent-agnostic plain
markdown with no code to unit-test, and its correctness is entirely a property
of what it says.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "atom-forge" / "SKILL.md"
QUESTIONS = REPO / "skills" / "atom-forge" / "references" / "interview-questions.md"
GATES = REPO / "skills" / "atom-forge" / "references" / "honesty-gates.md"
ATOM_DOC = REPO / "docs" / "building-an-atom.md"
CLAUDE = REPO / "CLAUDE.md"

#: Rows in the dimension table, `| 1 | **Trigger** | …` through `| 9 | …`.
DIMENSION_ROW = re.compile(r"^\| (\d) \| \*\*", re.MULTILINE)

#: How many dimensions the interview has. Change this only by changing the
#: table, and say in the commit why the new one earns its place — a tenth
#: dimension is a form, which is the failure the skill's own preamble names.
DIMENSIONS = 9


class TestTheCountsAreTrue:
    def test_the_dimension_table_has_the_number_everything_else_claims(self) -> None:
        rows = DIMENSION_ROW.findall(SKILL.read_text())
        assert [int(n) for n in rows] == list(range(1, DIMENSIONS + 1))

    def test_no_surface_still_says_eight(self) -> None:
        # The five sentences that were false for an afternoon, in four files.
        for path in (SKILL, QUESTIONS, GATES, ATOM_DOC, CLAUDE):
            text = path.read_text()
            assert "eight dimensions" not in text, path
            assert "10/10 readiness card" not in text, path

    def test_the_gate_reference_is_not_described_as_one_list(self) -> None:
        # "all eleven" was true when every gate was a canvas gate. It stopped
        # being true when Set B landed, and a stale total is how an author
        # concludes they have run everything.
        assert "all eleven" not in GATES.read_text()
        assert "all eleven" not in SKILL.read_text()


class TestTheStructureTheSweepAdded:
    """Each of these closed a gap found by running the skill against ten
    concepts (`.scratch/the-atom-has-no-context/research/01-*`). A later tidy-up
    that deletes one restores a specific, recorded defect."""

    def test_it_routes_before_it_interviews(self) -> None:
        # Without this, a connector scores ~3/11 against the canvas card and
        # reads as unbuildable rather than out of scope.
        skill = SKILL.read_text()
        assert "## Phase 0 — route, in one question" in skill
        assert "Is this thing on the canvas, or does something on the canvas use it?" in skill

    def test_it_names_both_gate_sets(self) -> None:
        # One list of eleven, all about packaging, returned a false green for a
        # connector: not one of them fires.
        skill = SKILL.read_text()
        assert "### Set A — the canvas gates" in skill
        assert "### Set B — the outside-contact gates" in skill
        assert "Set B — the outside-contact gates" in GATES.read_text()

    def test_gate_nine_is_declared_to_belong_to_both_sets(self) -> None:
        # The reducer gate is about the state schema, not the canvas. That it
        # is the only shared one is the evidence the split is real.
        assert "belongs to both sets" in SKILL.read_text()

    def test_outside_contact_asks_all_five(self) -> None:
        # Five follow-ups, one dimension — five dimensions would make it a form.
        skill = SKILL.read_text()
        for follow_up in ("**Needs**", "**Repeats**", "**Leaks**", "**Costs**", "**Stalls**"):
            assert follow_up in skill, follow_up

    def test_the_scope_map_can_say_not_here(self) -> None:
        # Every other row maps to something that exists, so a requirement that
        # fits none of them got a confident answer that fits none of it —
        # episodic memory being the live case.
        questions = QUESTIONS.read_text()
        assert "something this platform does not have" in questions
        assert "cite the ticket" in questions.lower()

    def test_there_are_two_readiness_cards(self) -> None:
        skill = SKILL.read_text()
        assert "CANVAS ROUTE" in skill
        assert "INFRASTRUCTURE ROUTE" in skill

    def test_the_interview_is_told_to_verify_and_to_recommend(self) -> None:
        # Ask alone was the whole method. An unverified answer is a hypothesis,
        # and a redirect with no recommendation has done half the job.
        skill = SKILL.read_text()
        assert "Ask, verify, recommend" in skill
        assert "do not take an answer on trust" in skill.lower()

    def test_the_function_contract_is_where_an_author_reads_it(self) -> None:
        # It lived only in `_discovered_function`'s docstring, and its state
        # denial is a constraint on the runtime-context work.
        for path in (SKILL, ATOM_DOC):
            text = path.read_text()
            assert "fn(text: str) -> str" in text, path
            assert "ticket 35" in text.lower(), path
