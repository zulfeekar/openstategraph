"""The sheet's shortest ritual, walked on a real board.

`osg-agent-experience/23`. The requirement's headline promise is *"TDD first,
then implementation"*, and `05` established that nothing in this repository can
tell a test written before its code from one written after — every other rule
here is a shape check on the finished artifact. The board is the one exception:
`kanban_store.set_stage` refuses `green` on a card that never reported `red`
(`StageOrderError`), and refuses `finished` without a test id, a red reason, a
green and a commit (`MissingEvidenceError`). Ordering, recorded as a fact.

So the entry sheet does not merely describe a good habit; it instructs an agent
to write rows into a store that will refuse them if the instruction is wrong.
That makes the ritual **executable**, which is the only reason a markdown page
can be tested here at all — this file does not assert on the prose, it *runs*
it: the stages the sheet names, in the order it names them, against the real
store, with the evidence the sheet says to supply.

The reason it is worth doing is `23`'s own question — is the card mandatory, or
the default with an escape? The sheet answers *mandatory*: every size files one.
What a **tweak** was documented to skip was the evidence itself — "no attend, no
`red`/`green`" — and that path does not exist in the software: the board's
`finished` gate reads red and green off the row, so the shortest documented
ritual ended in a refusal naming three missing fields. A developer who followed
it exactly could not finish their card.

Deliberately **not** asserted: that a tweak *ought* to be short. The ritual's
content is the author's call, and step 5 — the deliberate break — is a real
thing to skip, because it is the expensive one and it writes nothing. Asserted
here only that whatever the pages tell an agent to type is something the board
accepts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from openstategraph.bundled_skills import BUNDLED_SKILLS
from openstategraph.kanban_store import (
    MissingEvidenceError,
    Stage,
    ensure_schema,
    file_card,
    read_card,
    set_stage,
)

SHEET = BUNDLED_SKILLS["openstategraph"] / "SKILL.md"
LOOP = BUNDLED_SKILLS["openstategraph"] / "references" / "build-loop.md"

#: The row of the size table whose third cell is the whole ritual for the
#: smallest ask. `| **tweak** | one setting… | one confirming question · … |`
TWEAK_ROW = re.compile(r"^\| \*\*tweak\*\* \|[^|]*\|([^|]*)\|", re.MULTILINE)

ACTOR = "osg-agent-experience/23"
TEST_ID = "test_the_tweak_ritual_reaches_finished"
REASON = "the field did not exist, so the assertion read None"
COMMIT = "0123456789abcdef"


def _board(tmp_path: Path) -> Path:
    db = tmp_path / "kanban.sqlite"
    ensure_schema(db)
    file_card(
        db,
        task_id="tweak-1",
        board="demo",
        kind="task",
        category="build",
        title="add maxRetries to the grader",
    )
    return db


def _stages_named(cell: str) -> list[Stage]:
    """Every board stage the cell names, in the order it names them.

    Derived rather than transcribed: the point of the gate is that the page
    and the store cannot disagree, and a hand-written list here would be a
    third description to keep in step with the other two.
    """
    found = [(cell.index(f"`{stage.value}`"), stage) for stage in Stage if f"`{stage.value}`" in cell]
    return [stage for _, stage in sorted(found)]


def _walk(db: Path, stages: list[Stage]) -> None:
    """Type what the page says, supplying the evidence it says to supply."""
    for stage in stages:
        set_stage(
            db,
            "tweak-1",
            stage,
            actor=ACTOR,
            test_id=TEST_ID if stage in (Stage.RED, Stage.GREEN) else "",
            reason=REASON if stage is Stage.RED else "",
            commit=COMMIT if stage is Stage.FINISHED else "",
        )


class TestTheSmallestRitualIsExecutable:
    def _cell(self) -> str:
        match = TWEAK_ROW.search(SHEET.read_text(encoding="utf-8"))
        assert match, "the size table no longer carries a tweak row"
        return match.group(1)

    def test_the_row_names_the_stage_writes_it_makes(self) -> None:
        """`23`'s first done-when. A ritual that names only its last stage
        leaves an agent to guess the three the board demands before it."""
        named = _stages_named(self._cell())

        assert named, "the tweak row names no board stage at all"
        assert named[-1] is Stage.FINISHED, named
        assert named == sorted(named, key=lambda stage: list(Stage).index(stage)), (
            f"the tweak row names stages out of the order the board advances them: {named}"
        )

    def test_walking_exactly_what_the_row_names_reaches_finished(self, tmp_path: Path) -> None:
        """The whole gate. No prose is asserted — the row is executed."""
        db = _board(tmp_path)

        _walk(db, _stages_named(self._cell()))

        card = read_card(db, "tweak-1")
        assert card.stage is Stage.FINISHED
        assert card.evidence_test_id == TEST_ID
        assert card.evidence_red_reason == REASON
        assert card.evidence_green is True
        assert card.evidence_commit == COMMIT

    def test_the_long_form_does_not_tell_a_reader_to_skip_a_stage(self) -> None:
        """`build-loop.md` opens by saying what a tweak leaves out. A stage
        named there is a row the board will refuse later, so what may be
        skipped is a *step of the page* — the deliberate break — never a
        stage."""
        opening = LOOP.read_text(encoding="utf-8").split("## 1.", 1)[0]
        skipped = re.findall(r"no (?:deliberate )?`?([a-z]+)`?(?:/`([a-z]+)`)?", opening)
        named = {word for pair in skipped for word in pair if word}

        stages = {stage.value for stage in Stage} | {"attend"}
        assert not (named & stages), (
            f"the short form tells a tweak to skip {sorted(named & stages)}, and the board's "
            "finished gate reads exactly those off the card: the ritual ends in a refusal"
        )


class TestTheBoardStillRefusesTheClaimTheSheetRestsOn:
    """The other half: the sheet is only worth executing while the store is
    still the thing that cannot be talked round. If these go green-by-default
    the gate above proves nothing."""

    def test_green_without_red_is_refused(self, tmp_path: Path) -> None:
        db = _board(tmp_path)
        set_stage(db, "tweak-1", Stage.ATTENDED, actor=ACTOR)

        with pytest.raises(Exception) as caught:
            set_stage(db, "tweak-1", Stage.GREEN, actor=ACTOR, test_id=TEST_ID)
        assert "green" in str(caught.value)

    def test_finished_names_every_field_it_is_missing(self, tmp_path: Path) -> None:
        db = _board(tmp_path)
        set_stage(db, "tweak-1", Stage.ATTENDED, actor=ACTOR)

        with pytest.raises(MissingEvidenceError) as caught:
            set_stage(db, "tweak-1", Stage.FINISHED, actor=ACTOR, commit=COMMIT)

        message = str(caught.value)
        for field in ("test_id", "red reason", "green"):
            assert field in message, message
