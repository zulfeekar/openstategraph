"""The kanban card store — `kanban-patrol/19`.

The story: a coding agent writes "I've got this card" once, when it attends.
If it crashes, loses network, or is simply forgotten, nothing ever writes the
next sentence — the card would say "In Progress" forever, indistinguishable
from a card someone is genuinely, slowly still working. This module is the
one place that difference is made honest: an implicit heartbeat on every
write, a 60-minute flag that never auto-releases, and a claim that is
atomic — first-wins, loser told, never silently overwritten.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from openstategraph.kanban_store import (
    BOARD_AREAS,
    BOARD_COLUMNS,
    BOARD_PRIORITIES,
    Card,
    MissingEvidenceError,
    Stage,
    StageOrderError,
    column_for,
    ensure_schema,
    file_card,
    flagged_stale,
    read_card,
    release_card,
    set_stage,
)


def _db(tmp_path: Path) -> Path:
    path = tmp_path / "kanban.sqlite"
    ensure_schema(path)
    return path


def _filed(db: Path, task_id: str = "proj-a:thread-1") -> None:
    file_card(
        db,
        task_id=task_id,
        board="workflows",
        kind="bug",
        category="bug",
        title="A tool call with no timeout",
    )


class TestExclusiveAtomicAttend:
    def test_first_attend_wins(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)

        result = set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        assert result.ok
        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.ATTENDED
        assert card.actor == "alice"

    def test_second_attend_loses_and_is_told_who_has_it(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        result = set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="bob")

        assert not result.ok
        assert "alice" in result.reason
        card = read_card(db, "proj-a:thread-1")
        assert card.actor == "alice", "the loser must never overwrite the winner"

    def test_a_naive_read_then_write_would_have_let_bob_win(self, tmp_path: Path) -> None:
        """The concurrency shape `16` asks for: two claimants, exactly one
        wins. A read-then-write (read card, check unattended, then write)
        passes every single-caller test and fails this one — the write here
        must be a single conditional UPDATE, not read-check-write."""
        db = _db(tmp_path)
        _filed(db)

        first = set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")
        second = set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="bob")

        assert first.ok and not second.ok
        assert len({first.ok, second.ok}) == 2, "exactly one claimant must win"


class TestStageOnlyAdvances:
    def test_green_without_red_is_refused(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        try:
            set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="tests/test_x.py::test_y")
            assert False, "skipping red must raise"
        except StageOrderError:
            pass

        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.ATTENDED, "a refused transition must not be recorded"

    def test_backward_is_refused(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")

        try:
            set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")
            assert False, "moving backward must raise"
        except StageOrderError:
            pass

    def test_the_ordinary_path_advances_cleanly(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)

        evidence_kwargs = {
            Stage.RED: {"test_id": "tests/test_x.py::test_y", "reason": "boom"},
            Stage.GREEN: {"test_id": "tests/test_x.py::test_y"},
            Stage.FINISHED: {"commit": "deadbeef"},
        }
        for stage in (Stage.ATTENDED, Stage.RED, Stage.GREEN, Stage.FINISHED):
            result = set_stage(db, "proj-a:thread-1", stage, actor="alice", **evidence_kwargs.get(stage, {}))
            assert result.ok, stage

        assert read_card(db, "proj-a:thread-1").stage is Stage.FINISHED


class TestTheImplicitHeartbeat:
    def test_every_stage_write_refreshes_the_heartbeat_no_separate_ping(
        self, tmp_path: Path
    ) -> None:
        db = _db(tmp_path)
        _filed(db)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")
        first_beat = read_card(db, "proj-a:thread-1").last_heartbeat_at

        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")
        second_beat = read_card(db, "proj-a:thread-1").last_heartbeat_at

        assert second_beat >= first_beat


class TestTheLease:
    def test_a_fresh_claim_is_not_flagged(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        assert flagged_stale(db, threshold_seconds=3600) == []

    def test_an_old_heartbeat_is_flagged_not_released(self, tmp_path: Path) -> None:
        """Flag, never auto-release — a human decides. The card's own stage
        must be untouched by the mere act of checking staleness."""
        db = _db(tmp_path)
        _filed(db)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE cards SET last_heartbeat_at = ? WHERE task_id = ?",
            ("2020-01-01T00:00:00+00:00", "proj-a:thread-1"),
        )
        conn.commit()
        conn.close()

        stale = flagged_stale(db, threshold_seconds=3600)

        assert stale == ["proj-a:thread-1"]
        assert read_card(db, "proj-a:thread-1").stage is Stage.ATTENDED, (
            "checking staleness must never itself change the card"
        )


class TestUnattendedNeverFlagged:
    def test_a_card_nobody_attended_is_never_stale(self, tmp_path: Path) -> None:
        """Staleness is about an abandoned *claim* — an unattended card has
        no claim to abandon, and flagging it would just be a second, wrong
        spelling of 'Detected'."""
        db = _db(tmp_path)
        _filed(db)

        assert flagged_stale(db, threshold_seconds=0) == []


class TestFinishedNeverFlagged:
    """`kanban-patrol/32`: staleness is about an abandoned *claim*, and
    `finished` is not an abandoned claim — it is a finished one. Nobody
    writes to a resolved card again, so its heartbeat is old by design and
    passes the threshold within the hour. Flagging it offered `release_card`
    — the one control on the board that empties all four evidence fields —
    on the one column that is read-only, so a verified resolution was one
    misread click from a fresh Detected card with no history.

    Excluded at the store, where the fact is computed, so every door (the
    API row's `stale`, `openstategraph kanban release`, `kanban_release_card`)
    stops asserting it at once rather than each remembering the rule.
    """

    def _finished(self, db: Path, task_id: str = "proj-a:thread-1") -> None:
        set_stage(db, task_id, Stage.ATTENDED, actor="alice")
        set_stage(
            db, task_id, Stage.RED, actor="alice",
            test_id="tests/test_x.py::test_y", reason="boom",
        )
        set_stage(db, task_id, Stage.GREEN, actor="alice", test_id="tests/test_x.py::test_y")
        set_stage(db, task_id, Stage.FINISHED, actor="alice", commit="deadbeef")

    def test_a_finished_card_past_the_threshold_is_not_stale(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        self._finished(db)

        assert flagged_stale(db, threshold_seconds=0) == []

    def test_an_attended_card_past_the_threshold_still_is(self, tmp_path: Path) -> None:
        """The narrowing must not turn the flag off for the case it exists
        for — an abandoned live claim is still named."""
        db = _db(tmp_path)
        _filed(db, "proj-a:thread-2")
        set_stage(db, "proj-a:thread-2", Stage.ATTENDED, actor="alice")

        assert flagged_stale(db, threshold_seconds=0) == ["proj-a:thread-2"]

    def test_releasing_a_finished_card_is_refused(self, tmp_path: Path) -> None:
        """The evidence survives the refusal — that is the whole harm this
        ticket names, asserted rather than implied."""
        db = _db(tmp_path)
        _filed(db)
        self._finished(db)

        result = release_card(db, "proj-a:thread-1", threshold_seconds=0)

        assert not result.ok
        assert "not stale" in result.reason
        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.FINISHED
        assert card.evidence_test_id == "tests/test_x.py::test_y"
        assert card.evidence_commit == "deadbeef"


class TestFlaggedStaleWithNoStoreYet:
    """`kanban-patrol/19`: `flagged_stale` had zero callers outside this test
    file until the API route and `release_card` both needed it — and neither
    `read_card` nor `list_cards`'s own "no store yet is an empty answer, not
    a crash" guard had ever been copied here. Found live, wiring the API
    route in, not by inspection."""

    def test_a_store_that_does_not_exist_yet_is_an_empty_list_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "kanban.sqlite"

        assert flagged_stale(db, threshold_seconds=3600) == []


class TestRelease:
    """`kanban-patrol/19`'s explicit Release — the human half of "flag,
    never auto-release". A human presses this only on a card the system has
    already flagged; it must never release a card by mere request."""

    def _staled(self, db: Path, task_id: str = "proj-a:thread-1") -> None:
        set_stage(db, task_id, Stage.ATTENDED, actor="alice")
        set_stage(
            db, task_id, Stage.RED, actor="alice",
            test_id="tests/test_x.py::test_y", reason="boom",
        )
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE cards SET last_heartbeat_at = ? WHERE task_id = ?",
            ("2020-01-01T00:00:00+00:00", task_id),
        )
        conn.commit()
        conn.close()

    def test_releasing_a_genuinely_stale_card_resets_it_fully(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        self._staled(db)

        result = release_card(db, "proj-a:thread-1", threshold_seconds=3600)

        assert result.ok
        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.UNATTENDED
        assert card.actor is None
        assert card.last_heartbeat_at is None
        assert card.evidence_test_id == ""
        assert card.evidence_red_reason == ""
        assert card.evidence_green is False
        assert card.evidence_commit == ""

    def test_releasing_a_fresh_active_card_is_refused(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        result = release_card(db, "proj-a:thread-1", threshold_seconds=3600)

        assert not result.ok
        assert "not stale" in result.reason
        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.ATTENDED, "a refused release must not touch the card"
        assert card.actor == "alice"

    def test_releasing_an_unattended_card_is_refused(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)

        result = release_card(db, "proj-a:thread-1", threshold_seconds=3600)

        assert not result.ok
        assert "not stale" in result.reason
        assert read_card(db, "proj-a:thread-1").stage is Stage.UNATTENDED

    def test_a_fresh_attend_after_release_starts_clean(self, tmp_path: Path) -> None:
        """No leftover evidence bleeds into the new attempt — a genuine full
        release, not a partial one."""
        db = _db(tmp_path)
        _filed(db)
        self._staled(db)
        release_card(db, "proj-a:thread-1", threshold_seconds=3600)

        result = set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="bob")

        assert result.ok
        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.ATTENDED
        assert card.actor == "bob"
        assert card.evidence_test_id == ""
        assert card.evidence_red_reason == ""
        assert card.evidence_green is False
        assert card.evidence_commit == ""


class TestKanbanStorePath:
    """Same shape as `run_store_path`/`memory.checkpoint_path` — an env
    override wins outright, otherwise `state_dir()/kanban.sqlite`.
    `kanban-patrol/19`: unsuffixed, alongside `memory.sqlite`/`runs.sqlite`,
    because the board is per-project and cross-workflow, matching them —
    not `checkpoints-{slug}.sqlite`, which is per-workflow."""

    def test_default_path_is_state_dir_kanban_sqlite(self, tmp_path: Path, monkeypatch) -> None:
        from openstategraph.kanban_store import KANBAN_STORE_PATH_ENV, kanban_store_path
        from openstategraph.state_dir import state_dir

        monkeypatch.delenv(KANBAN_STORE_PATH_ENV, raising=False)
        workflows_root = tmp_path / "workflows"

        assert kanban_store_path(workflows_root) == state_dir(workflows_root) / "kanban.sqlite"

    def test_env_override_wins(self, tmp_path: Path, monkeypatch) -> None:
        from openstategraph.kanban_store import KANBAN_STORE_PATH_ENV, kanban_store_path

        override = tmp_path / "elsewhere.sqlite"
        monkeypatch.setenv(KANBAN_STORE_PATH_ENV, str(override))

        assert kanban_store_path(tmp_path / "workflows") == override


class TestPriorityAreaAndWhenFiled:
    """`kanban-patrol/02`: priority and area are patrol-minted, human-revised
    — the one axis this schema deliberately lets a human overwrite. `filed_at`
    is a real timestamp, never a worded guess, so the board can compute its
    own relative phrase rather than being handed a stale one."""

    def test_a_filed_card_carries_priority_area_and_a_real_timestamp(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        file_card(
            db,
            task_id="proj-a:thread-1",
            board="workflows",
            kind="bug",
            category="bug",
            title="A tool call with no timeout",
            priority="high",
            area="backend",
        )

        card = read_card(db, "proj-a:thread-1")

        assert card.priority == "high"
        assert card.area == "backend"
        assert card.filed_at is not None


class TestPriorityReason:
    """`kanban-patrol/25`. Priority is a level (`high`/`med`/`low`); this is
    the plain-English *why* for THIS card, written at classification time —
    not `cardPriority.ts`'s generic per-level sentence, which is the same
    for every card at that level regardless of its actual evidence."""

    def test_a_filed_card_carries_its_own_reason(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        file_card(
            db,
            task_id="proj-a:thread-1",
            board="workflows",
            kind="bug",
            category="bug",
            title="A tool call with no timeout",
            priority="high",
            area="backend",
            priority_reason="Asked the same question 4 times in one thread — real cost, no fix needed beyond a note.",
        )

        card = read_card(db, "proj-a:thread-1")

        assert "4 times" in card.priority_reason

    def test_omitting_it_is_an_empty_string_not_an_error(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        file_card(
            db, task_id="proj-a:thread-1", board="workflows", kind="bug",
            category="bug", title="x", priority="med", area="backend",
        )

        assert read_card(db, "proj-a:thread-1").priority_reason == ""


class TestEnsureSchemaRepairsAnOlderStore:
    """`kanban-patrol/26`. `ensure_schema` was `CREATE TABLE IF NOT EXISTS` —
    correct for a store that doesn't exist yet, blind to one that exists
    with an older shape. Per-column check, add what's missing: every change
    this schema has ever needed has been "add a column," never a rename."""

    def test_a_store_missing_a_column_gets_it_added(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        ensure_schema(db)
        file_card(db, task_id="proj-a:thread-1", board="workflows", kind="bug",
                   category="bug", title="x", priority="high", area="backend",
                   priority_reason="a real reason")

        # Simulate a store built before `priority_reason` existed.
        conn = sqlite3.connect(db)
        conn.execute("ALTER TABLE cards RENAME TO cards_new")
        conn.execute(
            """
            CREATE TABLE cards (
                task_id TEXT PRIMARY KEY, board TEXT NOT NULL, kind TEXT NOT NULL,
                category TEXT NOT NULL, title TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'unattended', actor TEXT,
                last_heartbeat_at TEXT, priority TEXT NOT NULL DEFAULT 'med',
                area TEXT NOT NULL DEFAULT 'backend', filed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO cards (task_id, board, kind, category, title, stage, priority, area, filed_at) "
            "SELECT task_id, board, kind, category, title, stage, priority, area, filed_at FROM cards_new"
        )
        conn.execute("DROP TABLE cards_new")
        conn.commit()
        conn.close()

        # This must not crash — the whole point of the fix.
        ensure_schema(db)

        card = read_card(db, "proj-a:thread-1")
        assert card.priority_reason == "", "a repaired column defaults empty, not the old value"

    def test_an_up_to_date_store_is_untouched(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        ensure_schema(db)
        file_card(db, task_id="proj-a:thread-1", board="workflows", kind="bug",
                   category="bug", title="x", priority="high", area="backend")

        ensure_schema(db)  # must be a no-op

        assert read_card(db, "proj-a:thread-1").title == "x"


class TestEvidenceGate:
    """`kanban-patrol/17`+`21`. Resolved means a test went red, then green —
    not an actor's word. The evidence lives where the transition actually
    happened: `red` requires a test id and the failure reason, `green`
    requires the *same* test id, and `finished` refuses unless both are
    already durably on the row — never a fresh claim re-asserted at the end.

    "An actor's report is testimony; the artifact is evidence" — this
    session's own rule, now enforced structurally.
    """

    def _attended(self, tmp_path: Path, task_id: str = "proj-a:thread-1") -> Path:
        db = _db(tmp_path)
        _filed(db, task_id)
        set_stage(db, task_id, Stage.ATTENDED, actor="alice")
        return db

    def test_red_without_a_test_id_is_refused(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        try:
            set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", reason="boom")
            assert False, "missing test_id must raise"
        except MissingEvidenceError as exc:
            assert "test_id" in str(exc)

    def test_red_without_a_reason_is_refused(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        try:
            set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y")
            assert False, "missing reason must raise"
        except MissingEvidenceError as exc:
            assert "reason" in str(exc)

    def test_red_with_both_is_recorded_on_the_row(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(
            db, "proj-a:thread-1", Stage.RED, actor="alice",
            test_id="tests/test_x.py::test_y", reason="AssertionError: no timeout set",
        )

        card = read_card(db, "proj-a:thread-1")
        assert card.evidence_test_id == "tests/test_x.py::test_y"
        assert card.evidence_red_reason == "AssertionError: no timeout set"
        assert card.evidence_green is False

    def test_green_with_a_different_test_id_is_refused(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")

        try:
            set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="tests/test_other.py::test_z")
            assert False, "a mismatched test id must raise"
        except MissingEvidenceError as exc:
            assert "does not match" in str(exc)

    def test_green_with_the_matching_test_id_is_recorded(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")

        set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="tests/test_x.py::test_y")

        assert read_card(db, "proj-a:thread-1").evidence_green is True

    def test_finished_without_evidence_is_refused_and_names_what_is_missing(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="t", reason="r")
        # No green recorded — finished must refuse and say why.
        try:
            set_stage(db, "proj-a:thread-1", Stage.FINISHED, actor="alice")
            assert False, "finished with no green evidence must raise"
        except MissingEvidenceError as exc:
            assert "green" in str(exc).lower()

    def test_finished_with_complete_evidence_is_accepted(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="t", reason="r")
        set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="t")

        result = set_stage(db, "proj-a:thread-1", Stage.FINISHED, actor="alice", commit="deadbeef")

        assert result.ok
        assert read_card(db, "proj-a:thread-1").stage is Stage.FINISHED

    def test_finished_with_a_different_test_id_is_refused(self, tmp_path: Path) -> None:
        """`kanban-patrol/33`: `finished` used to read only `commit` off this
        parameter and drop `test_id` without a word. It must be refused with
        the same wording shape `green` uses, and the row must stay unchanged."""
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")
        set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="tests/test_x.py::test_y")

        try:
            set_stage(
                db, "proj-a:thread-1", Stage.FINISHED, actor="alice",
                test_id="tests/other.py::t", commit="abc1234",
            )
            assert False, "a mismatched test id at finished must raise"
        except MissingEvidenceError as exc:
            assert "does not match" in str(exc)

        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.GREEN
        assert card.evidence_test_id == "tests/test_x.py::test_y"

    def test_finished_with_no_test_id_still_succeeds(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")
        set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="tests/test_x.py::test_y")

        result = set_stage(db, "proj-a:thread-1", Stage.FINISHED, actor="alice", commit="deadbeef")

        assert result.ok
        assert read_card(db, "proj-a:thread-1").stage is Stage.FINISHED

    def test_finished_with_the_matching_test_id_succeeds(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")
        set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="tests/test_x.py::test_y")

        result = set_stage(
            db, "proj-a:thread-1", Stage.FINISHED, actor="alice",
            test_id="tests/test_x.py::test_y", commit="deadbeef",
        )

        assert result.ok
        assert read_card(db, "proj-a:thread-1").stage is Stage.FINISHED

    def test_a_ratchet_that_matches_nothing_guards_nothing__test_id_cannot_be_blank_at_green(
        self, tmp_path: Path
    ) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="t", reason="r")

        try:
            set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="")
            assert False, "a blank test_id at green must raise, not silently match"
        except MissingEvidenceError:
            pass


class TestActorMustBeReal:
    """`kanban-patrol/20`. Not full identity (the CLI's trust boundary is
    the shell it runs in, per the owner's own decision; MCP has no way to
    read a request's identity — the installed library exposes no request
    context to a tool function at all, checked, not assumed). But a blank
    actor is a "already attended by " with nothing in the blank — meaningless
    to a human reading the card — so this is the floor: an actor must be a
    real, non-blank string, typed as such rather than a bare `str`."""

    def test_a_blank_actor_is_refused_on_attend(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        try:
            set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="")
            assert False, "a blank actor must raise"
        except MissingEvidenceError as exc:
            assert "actor" in str(exc)

    def test_a_whitespace_only_actor_is_refused(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        try:
            set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="   ")
            assert False, "a whitespace-only actor must raise"
        except MissingEvidenceError:
            pass

    def test_a_real_actor_is_accepted_as_before(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        _filed(db)
        result = set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")
        assert result.ok


class TestEvidenceCannotBeGamedWithWhitespace:
    """A confirmed real bug: `if not reason` is Python truthiness, and
    `bool(' ')` is `True` — a single space passed as evidence, silently,
    same failure class as a blank actor already refused elsewhere."""

    def _attended(self, tmp_path: Path, task_id: str = "proj-a:thread-1") -> Path:
        db = _db(tmp_path)
        _filed(db, task_id)
        set_stage(db, task_id, Stage.ATTENDED, actor="alice")
        return db

    def test_whitespace_only_reason_is_refused(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        try:
            set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="t", reason="   ")
            assert False, "a whitespace-only reason must raise"
        except MissingEvidenceError as exc:
            assert "reason" in str(exc)

    def test_whitespace_only_test_id_at_red_is_refused(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        try:
            set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="   ", reason="r")
            assert False, "a whitespace-only test_id must raise"
        except MissingEvidenceError as exc:
            assert "test_id" in str(exc)

    def test_whitespace_only_test_id_at_green_is_refused(self, tmp_path: Path) -> None:
        db = self._attended(tmp_path)
        set_stage(db, "proj-a:thread-1", Stage.RED, actor="alice", test_id="t", reason="r")
        try:
            set_stage(db, "proj-a:thread-1", Stage.GREEN, actor="alice", test_id="   ")
            assert False, "a whitespace-only test_id at green must raise"
        except MissingEvidenceError as exc:
            assert "test_id" in str(exc)


class TestCommitIsNowRequiredEvidence:
    """`kanban-patrol/17`'s own bar names four things — test id, red reason,
    green, and "the commit or diff that carries the work." `commit` was
    optional; a card could reach `finished` without it. Made required,
    matching the ticket's own stated bar exactly."""

    def _through_green(self, tmp_path: Path, task_id: str = "proj-a:thread-1") -> Path:
        db = _db(tmp_path)
        _filed(db, task_id)
        set_stage(db, task_id, Stage.ATTENDED, actor="alice")
        set_stage(db, task_id, Stage.RED, actor="alice", test_id="t", reason="r")
        set_stage(db, task_id, Stage.GREEN, actor="alice", test_id="t")
        return db

    def test_finished_with_no_commit_is_refused(self, tmp_path: Path) -> None:
        db = self._through_green(tmp_path)
        try:
            set_stage(db, "proj-a:thread-1", Stage.FINISHED, actor="alice")
            assert False, "finished with no commit must raise"
        except MissingEvidenceError as exc:
            assert "commit" in str(exc).lower()

    def test_finished_with_a_blank_commit_is_refused(self, tmp_path: Path) -> None:
        db = self._through_green(tmp_path)
        try:
            set_stage(db, "proj-a:thread-1", Stage.FINISHED, actor="alice", commit="   ")
            assert False, "a whitespace-only commit must raise"
        except MissingEvidenceError:
            pass

    def test_finished_with_a_real_commit_succeeds(self, tmp_path: Path) -> None:
        db = self._through_green(tmp_path)
        result = set_stage(db, "proj-a:thread-1", Stage.FINISHED, actor="alice", commit="deadbeef")

        assert result.ok
        assert read_card(db, "proj-a:thread-1").evidence_commit == "deadbeef"


class TestTheColumnACardIsIn:
    """`kanban-patrol/16`'s list door needs a column, and a column is derived
    — never stored. The frontend already derives it (`cardKind.ts`,
    `kanbanCardMapping.ts`); this is that same rule on the backend, so an MCP
    client and the board cannot disagree about where a card sits.

    Lifecycle outranks kind, and the ordering is the design: a claimed
    `decision` leaves Needs You, because somebody is already answering it.
    """

    def _card(self, tmp_path: Path, kind: str, stage: Stage | None = None) -> Card:
        db = tmp_path / "kanban.sqlite"
        ensure_schema(db)
        file_card(db, task_id="t", board="b", kind=kind, category=kind, title="x")
        if stage is not None:
            for step in (Stage.ATTENDED, Stage.RED, Stage.GREEN, Stage.FINISHED):
                set_stage(
                    db, "t", step, actor="alice",
                    test_id="tests/test_x.py::t", reason="it was red", commit="deadbeef",
                )
                if step is stage:
                    break
        return read_card(db, "t")

    def test_an_unattended_task_is_detected(self, tmp_path: Path) -> None:
        assert column_for(self._card(tmp_path, "bug")) == "detected"

    def test_an_unattended_judgement_needs_you(self, tmp_path: Path) -> None:
        assert column_for(self._card(tmp_path, "decision")) == "needsYou"

    def test_a_claimed_judgement_leaves_needs_you(self, tmp_path: Path) -> None:
        assert column_for(self._card(tmp_path, "decision", Stage.ATTENDED)) == "inProgress"

    def test_a_finished_card_is_resolved(self, tmp_path: Path) -> None:
        assert column_for(self._card(tmp_path, "bug", Stage.FINISHED)) == "resolved"

    def test_every_answer_is_one_of_the_declared_columns(self, tmp_path: Path) -> None:
        for kind in ("research", "task", "bug", "prototype", "grilling", "decision"):
            assert column_for(self._card(tmp_path, kind)) in BOARD_COLUMNS


class TestTheVocabularyIsNotSpeltTwice:
    """`BOARD_COLUMNS`, `BOARD_AREAS` and `BOARD_PRIORITIES` restate unions
    the frontend declares. A restatement with no way to fail is a story
    (CLAUDE.md), and this one would fail *quietly*: a seventh area added in
    TypeScript would make `kanban_list_cards` refuse a filter for a column a
    user is looking straight at, and name a set of accepted values that is
    simply out of date. So the tuples are read back off the source of truth.
    """

    ROOT = Path(__file__).resolve().parents[2] / "src" / "view" / "board"

    def _union(self, file_name: str, type_name: str) -> tuple[str, ...]:
        source = (self.ROOT / file_name).read_text()
        match = re.search(rf"export type {type_name} =([^;]+);", source)
        assert match, f"no `export type {type_name}` in {file_name}"
        return tuple(re.findall(r"'([^']+)'", match.group(1)))

    def test_the_columns_match_the_board(self) -> None:
        assert BOARD_COLUMNS == self._union("patrolBoardModel.ts", "BoardColumnId")

    def test_the_areas_match_the_board(self) -> None:
        assert BOARD_AREAS == self._union("cardPriority.ts", "BoardArea")

    def test_the_priorities_match_the_board(self) -> None:
        assert BOARD_PRIORITIES == self._union("cardPriority.ts", "BoardPriority")
