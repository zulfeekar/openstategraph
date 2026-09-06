"""`osg-agent-experience/65` — an empty board and a lost board were one sentence.

A project's board was reported gone: three sessions had filed, attended and
finished six cards, a fourth ran `kanban triage` and was told *nothing to
triage*, and `workflows/.openstategraph/` did not exist. The investigation in
the ticket found no deletion at all. `kanban_store_path()` is
`state_dir(root)/kanban.sqlite`, and `state_dir()` answers with
`<workflows root>/.openstategraph` **only inside a checkout**; installed from a
wheel it answers with `user_state_home()/project_key(root)`, a directory keyed
by a digest of the resolved workflows root. Two processes standing in
different places, or one installed and one from source, address two different
files and neither says which.

So the defect is not the location. It is that **nothing printed it** — and
`list_cards`' own docstring is where the confusion is written down, correctly
for a library function and fatally for a door: *"no store yet" and "store, no
rows" mean the same thing to a reader*.

Three assertions, at the three layers the fix lives at:

1. the rule is resolved in one place and carries its reason (`resolve_state_dir`);
2. a door prints it (`kanban where`), and `triage` names the file it read;
3. the documentation stops stating branch 2 as if it were the whole rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.kanban_store import kanban_store_location, kanban_store_path
from kanban_by_path import ensure_schema, file_card
from openstategraph.state_dir import STATE_DIR_ENV, resolve_state_dir, state_dir


@pytest.fixture()
def _project(tmp_path: Path) -> Path:
    (tmp_path / "workflows").mkdir()
    return tmp_path


def _root(project: Path) -> list[str]:
    return ["--workflows-root", str(project / "workflows")]


class TestOneRuleInOnePlace:
    """`state_dir()` is defined as `resolve_state_dir().path`, so the two can
    never disagree — the same construction `workflows_root()` uses over
    `resolve_workflows_root()`, and for the same reason: a second precedence
    chain written for the report is a chain that drifts from the real one."""

    def test_state_dir_is_the_choice_s_path(self, _project: Path) -> None:
        root = _project / "workflows"

        assert state_dir(root) == resolve_state_dir(root).path

    def test_a_checkout_says_so_by_name(self, _project: Path) -> None:
        choice = resolve_state_dir(_project / "workflows")

        assert choice.source == "checkout"
        assert "checkout" in choice.why

    def test_an_installed_run_names_the_per_user_directory(
        self, _project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The branch the ticket was filed over. Nothing about it is wrong —
        it is the only writable answer when the package is not in a source
        tree — but it is the branch nobody had been shown."""
        import openstategraph.workflows_root as workflows_root

        monkeypatch.setattr(workflows_root, "checkout_root", lambda: None)
        monkeypatch.delenv(STATE_DIR_ENV, raising=False)

        choice = resolve_state_dir(_project / "workflows")

        from openstategraph.state_dir import user_state_home

        assert choice.source == "installed"
        assert user_state_home() in choice.path.parents
        assert "installed" in choice.why

    def test_the_environment_override_says_it_won(
        self, _project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "elsewhere"))

        choice = resolve_state_dir(_project / "workflows")

        assert choice.source == "environment"
        assert STATE_DIR_ENV in choice.why
        assert choice.path == (tmp_path / "elsewhere").resolve()


class TestTheStoreKnowsWhetherItIsThere:
    def test_location_agrees_with_the_path_function(self, _project: Path) -> None:
        root = _project / "workflows"

        assert kanban_store_location(root).path == kanban_store_path(root)

    def test_a_project_with_no_board_says_so(self, _project: Path) -> None:
        location = kanban_store_location(_project / "workflows")

        assert location.exists is False

    def test_a_project_with_a_board_says_so(self, _project: Path) -> None:
        root = _project / "workflows"
        ensure_schema(kanban_store_path(root))

        assert kanban_store_location(root).exists is True

    def test_asking_never_creates_anything(self, _project: Path) -> None:
        """`state_dir`'s own rule, inherited: merely asking where the board
        would go must leave a read-only mount untouched."""
        root = _project / "workflows"

        kanban_store_location(root)

        assert not (root / ".openstategraph").exists()


class TestTheDoorPrintsIt:
    def test_where_prints_the_path_and_the_reason(self, _project: Path, capsys) -> None:
        code = cli.main(["kanban", "where"] + _root(_project))

        printed = capsys.readouterr().out
        assert code == 0
        assert str(kanban_store_path(_project / "workflows")) in printed
        assert "checkout" in printed

    def test_where_reports_absence_as_absence(self, _project: Path, capsys) -> None:
        cli.main(["kanban", "where"] + _root(_project))

        assert "no board here yet" in capsys.readouterr().out

    def test_where_counts_the_cards_it_found(self, _project: Path, capsys) -> None:
        db = kanban_store_path(_project / "workflows")
        ensure_schema(db)
        file_card(db, task_id="proj-a:one", board="workflows", kind="bug", category="bug", title="A tool call with no timeout")

        cli.main(["kanban", "where"] + _root(_project))

        printed = capsys.readouterr().out
        assert "1 card" in printed
        assert "no board here yet" not in printed

    def test_triage_on_a_missing_board_names_the_file_it_read(self, _project: Path, capsys) -> None:
        """The sentence the ticket was filed over. `nothing to triage` is a
        true statement about an empty board and a lie about a board that was
        never here, and the reader cannot tell which they got."""
        code = cli.main(["kanban", "triage"] + _root(_project))

        printed = capsys.readouterr().out
        assert code == 0
        assert "no board here yet" in printed
        assert str(kanban_store_path(_project / "workflows")) in printed

    def test_triage_on_an_empty_board_says_empty_and_not_missing(self, _project: Path, capsys) -> None:
        ensure_schema(kanban_store_path(_project / "workflows"))

        cli.main(["kanban", "triage"] + _root(_project))

        printed = capsys.readouterr().out
        assert "no board here yet" not in printed
        assert "empty" in printed
        assert str(kanban_store_path(_project / "workflows")) in printed

    def test_a_board_with_work_still_triages(self, _project: Path, capsys) -> None:
        db = kanban_store_path(_project / "workflows")
        ensure_schema(db)
        file_card(db, task_id="proj-a:one", board="workflows", kind="bug", category="bug", title="A tool call with no timeout")

        cli.main(["kanban", "triage"] + _root(_project))

        printed = capsys.readouterr().out
        assert "proj-a:one" in printed
        assert "no board here yet" not in printed


class TestTheDocumentationStopsStatingOneBranch:
    """`docs/the-patrol-board.md` §8 said *Cards live in
    `workflows/.openstategraph/kanban.sqlite`* with no condition on it. That
    is branch 2 of three, and a reader following it looks in the one place the
    store is not — which is exactly what happened."""

    def _doc(self) -> str:
        return (Path(__file__).resolve().parents[2] / "docs" / "the-patrol-board.md").read_text()

    def test_the_doc_does_not_state_the_location_unconditionally(self) -> None:
        assert "Cards live in `workflows/.openstategraph/kanban.sqlite`" not in self._doc()

    def test_the_doc_points_at_the_door(self) -> None:
        assert "kanban where" in self._doc()

    def test_the_doc_says_the_board_is_machine_local(self) -> None:
        """The ticket's second done-when: durability is decided and written
        down. It is machine-local state — not committed, not carried by a
        clone — so a card is not a record of a decision."""
        doc = self._doc()
        assert "machine-local" in doc
        assert "a card is not a record" in doc
