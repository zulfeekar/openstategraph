"""`openstategraph open .` — one verb, pointed at a folder.

install-experience/26. The comparison the owner drew was a standalone graph
tool installed once and run as `<tool> .`: one verb, point it at a folder, it
works. Four things stood between this CLI and that, and only the fourth was a
missing feature — the other three were things the command knew and did not
say.

The assertions below are grouped by the question each answers, because the
verb's whole subject is *what it tells you before it binds a socket*.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from openstategraph import cli, opening
from openstategraph.workflows_root import WORKFLOWS_ROOT_ENV, resolve_workflows_root


@pytest.fixture(autouse=True)
def _no_ambient_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every case below is about which directory was chosen and why, so no
    case may inherit one from the machine running it.

    `checkout_root` is neutralised for the same reason and it is the sharpest
    one: it answers from `__file__`, so a test suite run from inside this
    repository is *always* in the checkout branch of the chain no matter where
    it stands. That is correct behaviour and it would make every case below
    assert the checkout's own answer.
    """
    from openstategraph import workflows_root as module
    from openstategraph.config_file import CONFIG_ENV_VAR, reset_active_config

    monkeypatch.setattr(module, "checkout_root", lambda: None)
    monkeypatch.delenv(WORKFLOWS_ROOT_ENV, raising=False)
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    reset_active_config()
    yield
    reset_active_config()


def package(root: Path, slug: str, *, name: str, nodes: int = 1) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    document = {"nodes": [{"id": f"n{i}", "type": "io.input"} for i in range(nodes)], "edges": []}
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": name, "document": document})
    )
    return directory


def a_project(tmp_path: Path, *, workflows: bool = True, config: bool = True) -> Path:
    project = tmp_path / "svc"
    project.mkdir()
    if workflows:
        (project / "workflows").mkdir()
    if config:
        (project / "openstategraph.yaml").write_text("workflows_dir: workflows\n")
    return project


class TestItSaysWhichDirectoryItChoseAndWhy:
    """The failure mode was invisible: stand in the wrong place and you
    silently edit a different project's workflows. Naming the directory out
    loud is most of the fix, and naming *what chose it* is the rest."""

    def test_the_convention_says_so(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        choice = resolve_workflows_root()
        assert choice.path == tmp_path / "workflows"
        assert choice.source == "convention"
        assert "workflows" in choice.why

    def test_the_environment_says_so_and_names_the_variable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "elsewhere"))
        choice = resolve_workflows_root()
        assert choice.source == "environment"
        assert WORKFLOWS_ROOT_ENV in choice.why

    def test_the_config_file_says_so_and_names_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path)
        (project / "openstategraph.yaml").write_text("workflows_dir: flows\n")
        monkeypatch.chdir(project)
        choice = resolve_workflows_root()
        assert choice.path == project / "flows"
        assert choice.source == "config"
        assert "openstategraph.yaml" in choice.why

    def test_workflows_root_is_the_same_answer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One chain, two views. A second implementation of the precedence is
        the defect `workflows_root` was written to have already fixed once."""
        from openstategraph.workflows_root import workflows_root

        monkeypatch.chdir(tmp_path)
        assert workflows_root() == resolve_workflows_root().path

    def test_the_plan_names_the_project_it_was_pointed_at(self, tmp_path: Path) -> None:
        project = a_project(tmp_path)
        os.chdir(project)
        plan = opening.plan(project, create=False, can_ask=False)
        assert plan.refusal is None
        assert str(project) in "\n".join(plan.lines)
        assert plan.workflows_root == project / "workflows"

    def test_the_root_and_its_reason_are_printed_once_by_the_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One directory, one printer. `open` adds only what is about its
        own argument; `serve` already had to say where the workflows are, and
        now says what chose them — so neither verb prints it twice."""
        project = a_project(tmp_path)
        monkeypatch.chdir(project)
        facts = "\n".join(cli.startup_facts())
        assert str(project / "workflows") in facts
        assert "openstategraph.yaml" in facts
        assert str(project / "workflows") not in "\n".join(
            opening.plan(project, create=False, can_ask=False).lines
        )

    def test_a_root_outside_the_project_is_called_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole invisible failure, made loud: the path you named is not
        the directory this is about to edit."""
        project = a_project(tmp_path, config=False)
        other = tmp_path / "other-workflows"
        other.mkdir()
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(other))
        monkeypatch.chdir(project)
        plan = opening.plan(project, create=False, can_ask=False)
        printed = "\n".join(plan.lines)
        assert WORKFLOWS_ROOT_ENV in printed
        assert "not the path you gave" in printed


class TestItReviewsWhatIsThereBeforeItDoesAnything:
    """Ticket 13's review, reused rather than written a second time."""

    def test_it_names_each_package_by_slug_and_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path)
        package(project / "workflows", "their-flow", name="Lens QA", nodes=7)
        monkeypatch.chdir(project)
        printed = "\n".join(opening.plan(project, create=False, can_ask=False).lines)
        assert "their-flow" in printed
        assert "Lens QA" in printed
        assert "7 nodes" in printed

    def test_rubble_is_a_row_carrying_its_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path)
        broken = project / "workflows" / "half-built"
        broken.mkdir(parents=True)
        (broken / "workflow.json").write_text("{oh no")
        monkeypatch.chdir(project)
        printed = "\n".join(opening.plan(project, create=False, can_ask=False).lines)
        assert "half-built" in printed
        assert "will not parse" in printed

    def test_an_empty_root_says_it_is_empty_rather_than_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path)
        monkeypatch.chdir(project)
        printed = "\n".join(opening.plan(project, create=False, can_ask=False).lines)
        assert "no packages in it yet" in printed


class TestADirectoryThatIsItselfAPackage:
    """The case the owner named. Treating a package as a project root would
    create `workflows/workflows/`, and doing it silently is worse."""

    def test_it_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = a_project(tmp_path)
        starter = package(project / "workflows", "starter", name="Starter")
        monkeypatch.chdir(starter)
        plan = opening.plan(starter, create=False, can_ask=True)
        assert plan.refusal is not None
        assert "workflow package" in plan.refusal

    def test_it_names_the_project_root_it_thinks_you_meant(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path)
        starter = package(project / "workflows", "starter", name="Starter")
        monkeypatch.chdir(starter)
        refusal = opening.plan(starter, create=False, can_ask=True).refusal or ""
        assert str(project) in refusal

    def test_it_does_not_redirect_on_its_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A verb that quietly means a different directory is the defect this
        whole ticket is about, one level in."""
        project = a_project(tmp_path)
        starter = package(project / "workflows", "starter", name="Starter")
        monkeypatch.chdir(starter)
        plan = opening.plan(starter, create=False, can_ask=True)
        assert plan.consent_needed is False
        assert plan.workflows_root != project / "workflows" / "starter" / "workflows"


class TestItAsksBeforeCreatingAnything:
    """`open` is the read-only verb. `init` is the scaffolding verb. A verb
    that quietly scaffolds is a verb people stop trusting to be read-only."""

    def test_a_bare_directory_is_refused_and_offers_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path, workflows=False, config=False)
        monkeypatch.chdir(project)
        plan = opening.plan(project, create=False, can_ask=False)
        assert plan.refusal is not None
        assert "openstategraph init" in plan.refusal
        assert "--create" in plan.refusal

    def test_nothing_was_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project = a_project(tmp_path, workflows=False, config=False)
        monkeypatch.chdir(project)
        opening.plan(project, create=False, can_ask=False)
        assert list(project.iterdir()) == []

    def test_a_terminal_is_asked_rather_than_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path, workflows=False, config=False)
        monkeypatch.chdir(project)
        plan = opening.plan(project, create=False, can_ask=True)
        assert plan.refusal is None
        assert plan.consent_needed is True

    def test_create_is_the_non_interactive_consent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path, workflows=False, config=False)
        monkeypatch.chdir(project)
        plan = opening.plan(project, create=True, can_ask=False)
        assert plan.refusal is None
        assert plan.consent_needed is False
        assert plan.will_create is True

    def test_a_workflows_directory_with_no_config_is_adopted_not_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It already works — `./workflows` is the convention every reader
        resolves — so refusing it would be a rule inventing a problem."""
        project = a_project(tmp_path, config=False)
        package(project / "workflows", "theirs", name="Theirs")
        monkeypatch.chdir(project)
        plan = opening.plan(project, create=False, can_ask=False)
        assert plan.refusal is None
        assert "theirs" in "\n".join(plan.lines)

    def test_and_it_says_no_config_file_was_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = a_project(tmp_path, config=False)
        monkeypatch.chdir(project)
        printed = "\n".join(opening.plan(project, create=False, can_ask=False).lines)
        assert "no configuration file" in printed
        assert "openstategraph init" in printed


class TestTheVerbItself:
    """`open` is not `serve`, and the difference is the argument for it."""

    def test_open_takes_an_optional_directory(self) -> None:
        args = cli.build_parser().parse_args(["open"])
        assert args.directory is None
        assert cli.build_parser().parse_args(["open", "."]).directory == "."

    def test_serve_did_not_grow_one(self) -> None:
        """A verb that opens a browser and asks questions is not the verb a
        container runs."""
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["serve", "."])

    def test_open_opens_the_browser_by_default(self) -> None:
        assert cli.build_parser().parse_args(["open"]).open is True

    def test_and_a_flag_suppresses_it(self) -> None:
        """A tool that steals focus in CI is a bug."""
        assert cli.build_parser().parse_args(["open", "--no-open"]).open is False

    def test_serve_still_does_not_open_by_default(self) -> None:
        assert cli.build_parser().parse_args(["serve"]).open is False

    def test_a_bare_path_is_the_shorthand(self) -> None:
        """`openstategraph .` — the shape the owner asked for."""
        assert cli.expand_bare_path(["."]) == ["open", "."]

    def test_an_existing_directory_is_taken_as_one(self, tmp_path: Path) -> None:
        assert cli.expand_bare_path([str(tmp_path)]) == ["open", str(tmp_path)]

    def test_a_known_command_is_never_a_path(self, tmp_path: Path) -> None:
        """Tolerant in reading, strict in trusting: the candidate is resolved
        against the parser's own set of verbs first."""
        (tmp_path / "run").mkdir()
        os.chdir(tmp_path)
        assert cli.expand_bare_path(["run", "x", "y"]) == ["run", "x", "y"]

    def test_a_typo_is_left_for_argparse_to_report(self) -> None:
        assert cli.expand_bare_path(["srve"]) == ["srve"]

    def test_a_flag_is_left_alone(self) -> None:
        assert cli.expand_bare_path(["--version"]) == ["--version"]

    def test_nothing_is_left_alone(self) -> None:
        assert cli.expand_bare_path([]) == []
