"""An idea card — a card an agent files from a conversation, not from a patrol.

The patrol's own `file_card` mints a card out of *evidence already in the run
store*: it has a thread to point at, so the card's whole justification is the
finding behind it. A card filed from a conversation has none of that. What it
has instead is what a person said they wanted, and unless that is written on
the card at filing time it is gone — the next reader gets a title and has to
re-derive the brief from a chat log they cannot see.

So `file_idea_card` refuses a card with no story, no done-when and no reason
for its priority. That is the whole difference between the two writes, and it
is a refusal rather than a default because an empty string is exactly the
shape the missing brief would take.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openstategraph.kanban_store import IDEA_PREFIX, Stage, card_row, column_for, idea_task_id
from kanban_by_path import ensure_schema, file_idea_card, read_card, unresolved_blockers


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "kanban.sqlite"
    ensure_schema(path)
    return path


def _file(db: Path, **overrides: object) -> str:
    kwargs: dict[str, object] = {
        "project_id": "proj-a",
        "kind": "task",
        "title": "Draft the agenda",
        "story": "A weekly planner wants a first agenda without typing one.",
        "done_when": "A run answers with five numbered items.",
        "priority": "high",
        "priority_reason": "It is the first thing the owner asked for.",
    }
    kwargs.update(overrides)
    return file_idea_card(db, **kwargs)  # type: ignore[arg-type]


class TestTheId:
    def test_it_is_the_project_a_prefix_and_a_slug_of_the_title(self) -> None:
        assert idea_task_id("proj-a", "Draft the Agenda") == f"proj-a:{IDEA_PREFIX}draft-the-agenda"

    def test_punctuation_and_runs_of_space_collapse_to_single_dashes(self) -> None:
        assert idea_task_id("p", "  Grade  the   answer!! ") == f"p:{IDEA_PREFIX}grade-the-answer"

    def test_a_title_with_no_word_characters_at_all_is_refused(self) -> None:
        """Not an empty slug silently — `proj-a:idea-` is an id two different
        titles would both mint, which is the collision this whole id scheme is
        supposed to make impossible."""
        with pytest.raises(ValueError, match="title"):
            idea_task_id("proj-a", "!!! ???")


class TestWhatItWrites:
    def test_the_brief_is_on_the_card_it_returns(self, db: Path) -> None:
        task_id = _file(db)

        card = read_card(db, task_id)
        assert task_id == f"proj-a:{IDEA_PREFIX}draft-the-agenda"
        assert card.story.startswith("A weekly planner")
        assert card.done_when == "A run answers with five numbered items."
        assert card.priority_reason == "It is the first thing the owner asked for."
        assert card.stage is Stage.UNATTENDED

    def test_blocked_by_round_trips_as_a_list_not_a_string(self, db: Path) -> None:
        task_id = _file(db, title="Grade it", blocked_by=["proj-a:idea-draft-the-agenda"])

        assert read_card(db, task_id).blocked_by == ("proj-a:idea-draft-the-agenda",)

    def test_no_blockers_is_an_empty_tuple_never_a_literal_empty_string(self, db: Path) -> None:
        assert read_card(db, _file(db)).blocked_by == ()

    def test_the_model_and_effort_a_subagent_should_be_given_are_carried(self, db: Path) -> None:
        task_id = _file(db, agent_model="opus", agent_effort="high")

        card = read_card(db, task_id)
        assert (card.agent_model, card.agent_effort) == ("opus", "high")

    def test_a_patrol_card_carries_the_five_fields_empty_rather_than_missing(
        self, db: Path
    ) -> None:
        from kanban_by_path import file_card

        file_card(db, task_id="proj-a:thread-1", board="workflows", kind="bug",
                  category="bug", title="A tool call with no timeout")

        card = read_card(db, "proj-a:thread-1")
        assert (card.story, card.done_when, card.agent_model, card.agent_effort) == ("", "", "", "")
        assert card.blocked_by == ()


class TestRefusals:
    def test_a_kind_the_board_does_not_file_ideas_as_is_refused(self, db: Path) -> None:
        with pytest.raises(ValueError, match="kind"):
            _file(db, kind="research")

    @pytest.mark.parametrize("field", ["story", "done_when", "priority_reason"])
    def test_a_blank_brief_field_is_refused_by_name(self, db: Path, field: str) -> None:
        with pytest.raises(ValueError, match=field):
            _file(db, **{field: "   "})

    def test_a_priority_outside_the_boards_three_levels_is_refused(self, db: Path) -> None:
        with pytest.raises(ValueError, match="priority"):
            _file(db, priority="urgent")

    def test_a_second_card_with_the_same_title_is_refused_never_silently_ignored(
        self, db: Path
    ) -> None:
        """`file_card`'s `INSERT OR IGNORE` is right for a patrol re-run and
        wrong here: an agent filing two ideas that happen to share a title
        would get one card and no word about the other."""
        _file(db)

        with pytest.raises(ValueError, match="already"):
            _file(db, story="A different idea entirely, same words on the tin.")

        assert read_card(db, f"proj-a:{IDEA_PREFIX}draft-the-agenda").story.startswith(
            "A weekly planner"
        )


class TestAnOlderStore:
    def test_a_store_built_before_these_columns_gains_them_on_the_first_write(
        self, tmp_path: Path
    ) -> None:
        """kanban-patrol/26's additive path, exercised against the shape it was
        written for: a store that predates a column is repaired, not crashed
        on."""
        path = tmp_path / "old.sqlite"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE cards (task_id TEXT PRIMARY KEY, board TEXT NOT NULL, "
            "kind TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL, "
            "filed_at TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()

        task_id = _file(path)

        assert read_card(path, task_id).done_when == "A run answers with five numbered items."


class TestWhereItLands:
    def test_an_idea_task_is_work_an_agent_may_take_so_it_lands_in_detected(
        self, db: Path
    ) -> None:
        assert column_for(read_card(db, _file(db))) == "detected"

    def test_an_idea_grilling_ends_in_a_judgement_so_it_lands_in_needs_you(
        self, db: Path
    ) -> None:
        task_id = _file(db, kind="grilling", title="Should this be one node or two")

        assert column_for(read_card(db, task_id)) == "needsYou"


class TestTheWire:
    def test_the_row_every_door_publishes_carries_the_five_fields(self, db: Path) -> None:
        card = read_card(db, _file(db, agent_model="sonnet", agent_effort="medium",
                                   blocked_by=["proj-a:idea-other"]))

        row = card_row(card, stale=False)

        assert row["story"].startswith("A weekly planner")
        assert row["done_when"] == "A run answers with five numbered items."
        assert row["blocked_by"] == ["proj-a:idea-other"]
        assert row["agent_model"] == "sonnet"
        assert row["agent_effort"] == "medium"


class TestABlockedByIsResolvedAgainstTheBoard:
    """`osg-agent-experience/30`. `blocked_by` took any string verbatim, so
    the obvious guess — the bare slug, the readable half of an id the CLI had
    just printed — produced a blocker that no card would ever carry. The card
    was blocked forever and the real blocker lost its `unblocks N` credit.

    The seam is here rather than at either door, so the CLI and the MCP tool
    cannot disagree about what a blocker is.
    """

    def test_a_bare_slug_resolves_to_the_card_that_carries_it(self, db: Path) -> None:
        blocker = _file(db)  # proj-a:idea-draft-the-agenda

        task_id = _file(db, title="Grade it", blocked_by=["draft-the-agenda"])

        assert read_card(db, task_id).blocked_by == (blocker,)

    def test_a_bare_idea_prefixed_name_resolves_too(self, db: Path) -> None:
        blocker = _file(db)

        task_id = _file(db, title="Grade it", blocked_by=[f"{IDEA_PREFIX}draft-the-agenda"])

        assert read_card(db, task_id).blocked_by == (blocker,)

    def test_a_bare_name_of_a_patrol_card_resolves_without_the_idea_prefix(
        self, db: Path
    ) -> None:
        """A patrol card's id is `<project>:<thread_id>` with no `idea-` in
        it, so the bare form cannot simply have `idea-` glued on."""
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO cards (task_id, board, kind, category, title, stage, "
            "filed_at) VALUES (?, 'workflows', 'bug', 'finding', "
            "'A patrol finding', 'unattended', '2026-09-05T00:00:00+00:00')",
            ("proj-a:thread-77",),
        )
        conn.commit()
        conn.close()

        task_id = _file(db, title="Grade it", blocked_by=["thread-77"])

        assert read_card(db, task_id).blocked_by == ("proj-a:thread-77",)

    def test_a_full_id_no_card_carries_is_kept_so_ordering_still_works(
        self, db: Path
    ) -> None:
        """Filing a card that blocks on one not yet filed is a real ordering,
        so this is reported rather than refused."""
        task_id = _file(db, title="Grade it", blocked_by=["proj-a:idea-not-yet-filed"])

        assert read_card(db, task_id).blocked_by == ("proj-a:idea-not-yet-filed",)

    def test_an_unresolved_bare_slug_is_normalised_so_the_later_card_matches(
        self, db: Path
    ) -> None:
        """The forward reference has to become the id the blocker *will* be
        given, or it strands the card exactly as before."""
        task_id = _file(db, title="Grade it", blocked_by=["write-the-rubric"])

        assert read_card(db, task_id).blocked_by == (f"proj-a:{IDEA_PREFIX}write-the-rubric",)

    def test_a_blocker_naming_another_project_is_refused_with_both_names(
        self, db: Path
    ) -> None:
        with pytest.raises(ValueError) as exc:
            _file(db, title="Grade it", blocked_by=["proj-b:idea-elsewhere"])

        assert "proj-b:idea-elsewhere" in str(exc.value)
        assert "proj-a" in str(exc.value)

    def test_a_blank_blocker_is_refused_rather_than_stored(self, db: Path) -> None:
        with pytest.raises(ValueError, match="blank"):
            _file(db, title="Grade it", blocked_by=["   "])

    def test_the_same_blocker_twice_is_one_blocker(self, db: Path) -> None:
        blocker = _file(db)

        task_id = _file(
            db, title="Grade it", blocked_by=["draft-the-agenda", blocker]
        )

        assert read_card(db, task_id).blocked_by == (blocker,)


class TestFilingReportsABlockerNoCardCarries:
    """The ticket's first done-when: reported at filing time, naming it."""

    def test_an_unresolved_blocker_is_named(self, db: Path) -> None:
        _file(db, title="Grade it", blocked_by=["write-the-rubric"])

        assert unresolved_blockers(db, read_card(db, "proj-a:idea-grade-it")) == (
            f"proj-a:{IDEA_PREFIX}write-the-rubric",
        )

    def test_a_blocker_a_card_carries_is_not_reported(self, db: Path) -> None:
        _file(db)
        _file(db, title="Grade it", blocked_by=["draft-the-agenda"])

        assert unresolved_blockers(db, read_card(db, "proj-a:idea-grade-it")) == ()
