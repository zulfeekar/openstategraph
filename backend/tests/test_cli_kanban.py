"""`openstategraph kanban` — kanban-patrol/19's CLI adapter.

Every coding agent can shell out; not every one is MCP-attached to this
project's server. This is the lower-common-denominator door — a thin wrapper
over `kanban_store.set_stage`, never a second implementation of the claim or
ordering logic (`16` gets the MCP door over the identical function).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.kanban_store import (
    Stage,
    column_for,
    ensure_schema,
    file_card,
    kanban_store_path,
    read_card,
)


@pytest.fixture()
def _project(tmp_path: Path) -> Path:
    (tmp_path / "workflows").mkdir()
    return tmp_path


def _filed(project: Path, task_id: str = "proj-a:thread-1") -> Path:
    db = kanban_store_path(project / "workflows")
    ensure_schema(db)
    file_card(db, task_id=task_id, board="workflows", kind="bug", category="bug", title="A tool call with no timeout")
    return db


def _root(project: Path) -> list[str]:
    return ["--workflows-root", str(project / "workflows")]


class TestAttend:
    def test_attend_writes_the_claim(self, _project: Path, capsys) -> None:
        db = _filed(_project)

        code = cli.main(["kanban", "attend", "proj-a:thread-1", "--actor", "alice"] + _root(_project))

        assert code == 0
        from openstategraph.kanban_store import read_card

        assert read_card(db, "proj-a:thread-1").stage is Stage.ATTENDED

    def test_a_second_attend_exits_nonzero_and_says_who_has_it(self, _project: Path, capsys) -> None:
        _filed(_project)
        cli.main(["kanban", "attend", "proj-a:thread-1", "--actor", "alice"] + _root(_project))

        code = cli.main(["kanban", "attend", "proj-a:thread-1", "--actor", "bob"] + _root(_project))

        assert code != 0
        assert "alice" in capsys.readouterr().err


class TestStage:
    def test_stage_advances_the_card(self, _project: Path) -> None:
        db = _filed(_project)
        cli.main(["kanban", "attend", "proj-a:thread-1", "--actor", "alice"] + _root(_project))

        code = cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "red", "--actor", "alice",
                "--test-id", "tests/test_x.py::test_y", "--reason", "AssertionError: no timeout set",
            ]
            + _root(_project)
        )

        assert code == 0
        from openstategraph.kanban_store import read_card

        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.RED
        assert card.evidence_test_id == "tests/test_x.py::test_y"
        assert card.evidence_red_reason == "AssertionError: no timeout set"

    def test_skipping_a_stage_exits_nonzero_with_a_clear_reason(self, _project: Path, capsys) -> None:
        _filed(_project)
        cli.main(["kanban", "attend", "proj-a:thread-1", "--actor", "alice"] + _root(_project))

        code = cli.main(
            ["kanban", "stage", "proj-a:thread-1", "green", "--actor", "alice", "--test-id", "tests/test_x.py::test_y"]
            + _root(_project)
        )

        assert code != 0
        assert "one step at a time" in capsys.readouterr().err


class TestEvidenceGate:
    """`kanban-patrol/17`+`21`'s CLI door — the same gate `kanban_store.py`
    enforces, reached through `kanban stage`, refused cleanly rather than
    with a stack trace."""

    def _attended(self, project: Path, task_id: str = "proj-a:thread-1") -> Path:
        db = _filed(project, task_id)
        cli.main(["kanban", "attend", task_id, "--actor", "alice"] + _root(project))
        return db

    def test_red_without_test_id_or_reason_exits_nonzero(self, _project: Path, capsys) -> None:
        self._attended(_project)

        code = cli.main(["kanban", "stage", "proj-a:thread-1", "red", "--actor", "alice"] + _root(_project))

        assert code != 0
        assert "test_id" in capsys.readouterr().err

    def test_red_with_both_succeeds(self, _project: Path) -> None:
        db = self._attended(_project)

        code = cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "red", "--actor", "alice",
                "--test-id", "tests/test_x.py::test_y", "--reason", "boom",
            ]
            + _root(_project)
        )

        assert code == 0
        from openstategraph.kanban_store import read_card

        assert read_card(db, "proj-a:thread-1").stage is Stage.RED

    def test_green_with_a_mismatched_test_id_exits_nonzero(self, _project: Path, capsys) -> None:
        self._attended(_project)
        cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "red", "--actor", "alice",
                "--test-id", "tests/test_x.py::test_y", "--reason", "boom",
            ]
            + _root(_project)
        )

        code = cli.main(
            ["kanban", "stage", "proj-a:thread-1", "green", "--actor", "alice", "--test-id", "tests/test_other.py::test_z"]
            + _root(_project)
        )

        assert code != 0
        assert "does not match" in capsys.readouterr().err

    def test_finished_with_no_evidence_exits_nonzero(self, _project: Path, capsys) -> None:
        self._attended(_project)
        cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "red", "--actor", "alice",
                "--test-id", "tests/test_x.py::test_y", "--reason", "boom",
            ]
            + _root(_project)
        )

        code = cli.main(["kanban", "stage", "proj-a:thread-1", "finished", "--actor", "alice"] + _root(_project))

        assert code != 0
        assert "green" in capsys.readouterr().err.lower()

    def test_full_red_green_finished_with_matching_evidence_succeeds(self, _project: Path) -> None:
        db = self._attended(_project)
        assert cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "red", "--actor", "alice",
                "--test-id", "tests/test_x.py::test_y", "--reason", "boom",
            ]
            + _root(_project)
        ) == 0
        assert cli.main(
            ["kanban", "stage", "proj-a:thread-1", "green", "--actor", "alice", "--test-id", "tests/test_x.py::test_y"]
            + _root(_project)
        ) == 0

        code = cli.main(
            ["kanban", "stage", "proj-a:thread-1", "finished", "--actor", "alice", "--commit", "abc123"]
            + _root(_project)
        )

        assert code == 0
        from openstategraph.kanban_store import read_card

        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.FINISHED
        assert card.evidence_green is True
        assert card.evidence_commit == "abc123"


class TestRelease:
    """`kanban-patrol/19`'s explicit Release — the human half of "flag,
    never auto-release". This door is a thin wrapper over
    `kanban_store.release_card`, never a second implementation."""

    def _staled(self, project: Path, task_id: str = "proj-a:thread-1") -> Path:
        import sqlite3

        db = _filed(project, task_id)
        cli.main(["kanban", "attend", task_id, "--actor", "alice"] + _root(project))
        cli.main(
            [
                "kanban", "stage", task_id, "red", "--actor", "alice",
                "--test-id", "tests/test_x.py::test_y", "--reason", "boom",
            ]
            + _root(project)
        )
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE cards SET last_heartbeat_at = ? WHERE task_id = ?",
            ("2020-01-01T00:00:00+00:00", task_id),
        )
        conn.commit()
        conn.close()
        return db

    def test_releasing_a_stale_card_succeeds_and_resets_it(self, _project: Path) -> None:
        db = self._staled(_project)

        code = cli.main(["kanban", "release", "proj-a:thread-1"] + _root(_project))

        assert code == 0
        from openstategraph.kanban_store import read_card

        card = read_card(db, "proj-a:thread-1")
        assert card.stage is Stage.UNATTENDED
        assert card.actor is None
        assert card.evidence_test_id == ""

    def test_releasing_an_active_card_exits_nonzero_and_says_not_stale(
        self, _project: Path, capsys
    ) -> None:
        _filed(_project)
        cli.main(["kanban", "attend", "proj-a:thread-1", "--actor", "alice"] + _root(_project))

        code = cli.main(["kanban", "release", "proj-a:thread-1"] + _root(_project))

        assert code != 0
        assert "not stale" in capsys.readouterr().err


class TestShow:
    def test_show_prints_the_instruction_for_pasting(self, _project: Path, capsys) -> None:
        _filed(_project)

        code = cli.main(["kanban", "show", "proj-a:thread-1"] + _root(_project))

        out = capsys.readouterr().out
        assert code == 0
        assert "proj-a:thread-1" in out
        assert "A tool call with no timeout" in out


class TestPatrolRun:
    """`openstategraph patrol run` — kanban-patrol/07's synchronous door.
    The async/SSE "outlives the board" layer is a separate follow-up; this
    proves the loop itself works from the command line."""

    def test_files_real_cards_and_prints_what_it_did(self, tmp_path: Path, monkeypatch, capsys) -> None:
        # This suite's own isolation fixture (`_no_ambient_config_file`)
        # points `OPENSTATEGRAPH_CONFIG` at a file that does not exist, for
        # every test by default — a test that wants config discovery to
        # find something real sets the variable to its own file, per that
        # fixture's own docstring.
        from openstategraph.config_file import reset_active_config
        from openstategraph.scaffold import init_project

        result = init_project(tmp_path / "proj", starter=False)
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(result.config))
        reset_active_config()

        code = cli.main(["patrol", "run", "--workflows-root", str(result.workflows)])

        out = capsys.readouterr().out
        assert code == 0
        assert "finding" in out

    def test_a_config_that_predates_project_id_is_adopted_and_the_line_printed(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """`kanban-patrol/23`: this door used to refuse, which left the board
        permanently dead for any project made before the field existed. It
        now appends the line to that project's own config and says so."""
        import yaml

        from openstategraph.config_file import reset_active_config

        (tmp_path / "workflows").mkdir()
        config = tmp_path / "openstategraph.yaml"
        # A minimal, hand-written config with no `project_id:` line at all.
        config.write_text("version: 1\nworkflows_dir: workflows\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()

        code = cli.main(["patrol", "run", "--workflows-root", str(tmp_path / "workflows")])

        out = capsys.readouterr().out
        assert code == 0
        assert "project_id: " in out
        written = yaml.safe_load(config.read_text())
        assert written["workflows_dir"] == "workflows"
        assert written["project_id"] and written["project_id"] in out
        assert (tmp_path / ".openstategraph" / "project_identity").read_text().strip() == written[
            "project_id"
        ]


class TestAnswer:
    """`kanban-patrol/15`. The CLI half of Answer — the same one write path
    the board and the MCP door use, so a decision typed at a terminal and a
    decision typed in a browser land identically on the row."""

    def _judgement(self, project: Path, task_id: str = "proj-a:judgement") -> Path:
        db = kanban_store_path(project / "workflows")
        ensure_schema(db)
        file_card(
            db,
            task_id=task_id,
            board="workflows",
            kind="decision",
            category="decision",
            title="Which model should the grader use?",
        )
        return db

    def test_answer_records_the_decision_and_moves_the_card(self, _project: Path) -> None:
        db = self._judgement(_project)

        code = cli.main(
            ["kanban", "answer", "proj-a:judgement", "--actor", "alice", "--answer", "The cloud one."]
            + _root(_project)
        )

        assert code == 0
        card = read_card(db, "proj-a:judgement")
        assert card.answer == "The cloud one."
        assert card.answered_by == "alice"
        assert column_for(card) == "detected"

    def test_an_empty_answer_exits_nonzero_and_names_what_is_missing(
        self, _project: Path, capsys
    ) -> None:
        # A refusal is a clean non-zero exit with a plain reason, never a
        # stack trace — the same shape `stage`'s evidence gate already uses.
        db = self._judgement(_project)

        code = cli.main(
            ["kanban", "answer", "proj-a:judgement", "--actor", "alice", "--answer", "   "]
            + _root(_project)
        )

        assert code != 0
        assert "answer" in capsys.readouterr().err
        assert read_card(db, "proj-a:judgement").answer == ""

    def test_a_task_kind_card_is_refused_with_a_reason(self, _project: Path, capsys) -> None:
        _filed(_project)

        code = cli.main(
            ["kanban", "answer", "proj-a:thread-1", "--actor", "alice", "--answer", "yes"]
            + _root(_project)
        )

        assert code != 0
        assert "not waiting on a decision" in capsys.readouterr().err

    def test_a_second_answer_exits_nonzero_and_says_who_answered(
        self, _project: Path, capsys
    ) -> None:
        self._judgement(_project)
        cli.main(
            ["kanban", "answer", "proj-a:judgement", "--actor", "alice", "--answer", "The cloud one."]
            + _root(_project)
        )

        code = cli.main(
            ["kanban", "answer", "proj-a:judgement", "--actor", "bob", "--answer", "The local one."]
            + _root(_project)
        )

        assert code != 0
        assert "alice" in capsys.readouterr().err

    def test_show_prints_the_decision_once_it_has_one(self, _project: Path, capsys) -> None:
        # `show` is what an agent reads instead of the board. A card whose
        # question has been settled and whose answer `show` omits is a card
        # that sends the agent back to ask it again.
        self._judgement(_project)
        cli.main(
            ["kanban", "answer", "proj-a:judgement", "--actor", "alice", "--answer", "The cloud one."]
            + _root(_project)
        )

        cli.main(["kanban", "show", "proj-a:judgement"] + _root(_project))

        out = capsys.readouterr().out
        assert "The cloud one." in out
        assert "alice" in out


class TestAttendHandsBackTheMarker:
    """`kanban-patrol/08`. Attending a card is the moment an agent starts
    producing runs, and it is the last moment anything tells it anything. So
    the marker it must set on those runs is printed here, spelled out, rather
    than left in a skill file the agent may not have installed."""

    def test_attending_prints_the_session_marker_for_this_card(
        self, _project: Path, capsys
    ) -> None:
        from openstategraph.patrol import card_session_id

        _filed(_project, "proj-a:thread-1")

        code = cli.main(
            ["kanban", "attend", "proj-a:thread-1", "--actor", "alice"] + _root(_project)
        )

        assert code == 0
        out = capsys.readouterr().out
        assert card_session_id("proj-a:thread-1") in out, (
            "Nothing told the agent how to mark the runs it is about to make, "
            "so the next patrol files a card about this card's own work."
        )
        assert "--session-id" in out


class TestFile:
    """`osg-agent-experience/25`'s filing door, for the agent that can shell
    out but is not MCP-attached. Same `file_idea_card`, never a second
    implementation of the brief's refusals."""

    @pytest.fixture()
    def _identified(self, _project: Path, monkeypatch) -> Path:
        from openstategraph.config_file import reset_active_config

        config = _project / "openstategraph.yaml"
        config.write_text("project_id: proj-a\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()
        yield _project
        reset_active_config()

    def _argv(self, project: Path, *extra: str) -> list[str]:
        return [
            "kanban", "file",
            "--kind", "task",
            "--title", "Draft the agenda",
            "--story", "A weekly planner wants a first agenda without typing one.",
            "--done-when", "A run answers with five numbered items.",
            "--priority", "high",
            "--reason", "It is the first thing the owner asked for.",
            "--actor", "alice",
            *extra,
        ] + _root(project)

    def test_filing_writes_the_card_and_prints_where_it_landed(
        self, _identified: Path, capsys
    ) -> None:
        code = cli.main(self._argv(_identified))

        assert code == 0
        card = read_card(kanban_store_path(_identified / "workflows"), "proj-a:idea-draft-the-agenda")
        assert card.done_when == "A run answers with five numbered items."
        assert card.actor == "alice"
        out = capsys.readouterr().out
        assert "proj-a:idea-draft-the-agenda" in out
        assert "detected" in out

    def test_the_optional_fields_reach_the_card(self, _identified: Path) -> None:
        cli.main(
            self._argv(
                _identified,
                "--area", "frontend",
                "--blocked-by", "proj-a:idea-other",
                "--blocked-by", "proj-a:idea-second",
                "--agent-model", "opus",
                "--agent-effort", "high",
            )
        )

        card = read_card(kanban_store_path(_identified / "workflows"), "proj-a:idea-draft-the-agenda")
        assert card.area == "frontend"
        assert card.blocked_by == ("proj-a:idea-other", "proj-a:idea-second")
        assert (card.agent_model, card.agent_effort) == ("opus", "high")

    def test_a_blocker_no_card_carries_is_named_on_stdout(
        self, _identified: Path, capsys
    ) -> None:
        """`osg-agent-experience/30`. The refusal and the report are the
        store's, so this door and the MCP one cannot disagree; what is tested
        here is that the door does not swallow either."""
        cli.main(self._argv(_identified, "--blocked-by", "not-filed-yet"))

        out = capsys.readouterr().out
        assert "proj-a:idea-not-filed-yet" in out
        assert "no card carries" in out

    def test_a_blocker_naming_another_project_exits_nonzero(
        self, _identified: Path, capsys
    ) -> None:
        code = cli.main(self._argv(_identified, "--blocked-by", "proj-b:idea-elsewhere"))

        assert code != 0
        assert "proj-b:idea-elsewhere" in capsys.readouterr().err

    def test_a_grilling_lands_in_needs_you(self, _identified: Path, capsys) -> None:
        cli.main(self._argv(_identified, "--kind", "grilling"))

        assert "needsYou" in capsys.readouterr().out

    def test_a_blank_brief_field_exits_nonzero_and_names_it(
        self, _identified: Path, capsys
    ) -> None:
        argv = self._argv(_identified)
        argv[argv.index("--story") + 1] = "   "

        code = cli.main(argv)

        assert code != 0
        assert "story" in capsys.readouterr().err

    def test_a_second_card_with_the_same_title_exits_nonzero(
        self, _identified: Path, capsys
    ) -> None:
        cli.main(self._argv(_identified))

        code = cli.main(self._argv(_identified))

        assert code != 0
        assert "already" in capsys.readouterr().err


class TestTriage:
    """`osg-agent-experience/25` slice 4's read-only CLI door onto
    `kanban_store.triage` — same function, same order the MCP door answers
    with (`test_mcp_kanban.py::TestTriage`)."""

    @pytest.fixture()
    def _identified(self, _project: Path, monkeypatch) -> Path:
        from openstategraph.config_file import reset_active_config

        config = _project / "openstategraph.yaml"
        config.write_text("project_id: proj-a\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()
        yield _project
        reset_active_config()

    def _file(self, project: Path, title: str, *extra: str) -> None:
        argv = [
            "kanban", "file",
            "--kind", "task",
            "--title", title,
            "--story", "s", "--done-when", "d",
            "--priority", "med", "--reason", "r",
            "--actor", "alice",
            *extra,
        ] + _root(project)
        code = cli.main(argv)
        assert code == 0

    def _chained(self, project: Path) -> None:
        self._file(project, "Root")
        self._file(project, "Middle", "--blocked-by", "proj-a:idea-root")
        self._file(project, "Leaf", "--blocked-by", "proj-a:idea-middle")

    def test_the_chain_prints_root_then_middle_then_leaf_in_order(
        self, _identified: Path, capsys
    ) -> None:
        self._chained(_identified)
        capsys.readouterr()  # drop the file output

        code = cli.main(["kanban", "triage"] + _root(_identified))

        assert code == 0
        out = capsys.readouterr().out
        root_pos = out.index("proj-a:idea-root")
        middle_pos = out.index("proj-a:idea-middle")
        leaf_pos = out.index("proj-a:idea-leaf")
        assert root_pos < middle_pos < leaf_pos

    def test_it_prints_rank_and_why_here(self, _identified: Path, capsys) -> None:
        self._chained(_identified)
        capsys.readouterr()

        cli.main(["kanban", "triage"] + _root(_identified))

        out = capsys.readouterr().out
        assert "1. proj-a:idea-root" in out
        assert "unblocks" in out
        assert "blocked by" in out

    def test_a_board_that_is_not_there_says_so_rather_than_printing_nothing(
        self, _identified: Path, capsys
    ) -> None:
        """This assertion read `nothing to triage` until
        `osg-agent-experience/65`, and that is the defect it was asserting:
        this fixture has never filed a card, so there is no store at this
        address at all, and the sentence a reader got was the one an empty
        board gets. Six filed cards read as a project that had never had any.
        The address is now named and the two states are two sentences."""
        code = cli.main(["kanban", "triage"] + _root(_identified))

        out = capsys.readouterr().out
        assert code == 0
        assert "no board here yet" in out
        assert str(kanban_store_path(_identified / "workflows")) in out
