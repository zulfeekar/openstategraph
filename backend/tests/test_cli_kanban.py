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
from openstategraph.kanban_store import Stage, ensure_schema, file_card, kanban_store_path


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
