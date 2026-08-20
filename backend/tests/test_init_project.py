"""`openstategraph init [dir]` — the command that makes a project.

install-experience T6, and the honest substitute for a syntax pip cannot
parse. `pip install openstategraph[directory:'my_demo']` does not merely fail
to do anything useful — the dependency-specifier grammar takes bare
identifiers, so it does not *parse*. The directory a user wants to name is
therefore named by a command, and this is it.

Two promises are tested separately because they fail separately:

1. **What it writes** — a commented `openstategraph.yaml`, a `.gitignore`, and
   `workflows/starter/` from the `minimal` template, which is the template
   that pins no model and so runs on whatever provider extra was installed.
   It never writes `.env`: a generator that emits a credential file is a
   generator whose output someone commits. It *prints* how to make one.
2. **What it refuses** — four existing-directory cases, four distinguishable
   messages, and the confirmation is `--force` rather than a prompt. Exit
   codes are this CLI's API for CI, and a command that blocks on stdin hangs a
   CI job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.config_file import CONFIG_FILENAMES, load_config, looks_like_a_secret
from openstategraph.scaffold import ScaffoldError, init_project


@pytest.fixture(autouse=True)
def _fresh():
    from openstategraph.config_file import reset_active_config
    from openstategraph.providers import reset_provider_catalogue

    reset_provider_catalogue()
    reset_active_config()
    yield
    reset_provider_catalogue()
    reset_active_config()


class TestWhatItWrites:
    def test_it_creates_the_directory_the_user_named(self, tmp_path: Path) -> None:
        result = init_project(tmp_path / "my_demo")

        assert result.directory == (tmp_path / "my_demo")
        assert result.directory.is_dir()

    def test_the_config_file_is_the_canonical_name(self, tmp_path: Path) -> None:
        result = init_project(tmp_path / "my_demo")

        assert result.config.name == CONFIG_FILENAMES[0]
        assert result.config.is_file()

    def test_the_config_it_writes_is_one_this_project_can_load(self, tmp_path: Path) -> None:
        """A generated config that the loader rejects is worse than none — it
        teaches the wrong shape and fails on the second command."""
        result = init_project(tmp_path / "my_demo")

        config = load_config(result.config)
        assert config.version == 1
        assert config.workflows_dir == "workflows"

    def test_the_generated_config_carries_no_secret(self, tmp_path: Path) -> None:
        """Not "should not" — the same rule the loader enforces, applied to the
        thing we generate. A default model line is a model id; a key never
        appears because nothing here reads one."""
        result = init_project(tmp_path / "my_demo")

        for line in result.config.read_text().splitlines():
            assert not looks_like_a_secret(line.partition(":")[2].strip()), line

    def test_the_generated_config_is_commented(self, tmp_path: Path) -> None:
        """The owner's decision: the file a person opens next explains itself.
        A bare `version: 1` teaches nothing about what may go in it."""
        text = init_project(tmp_path / "my_demo").config.read_text()

        assert "# default_model:" in text
        assert text.count("#") > 10

    def test_it_writes_a_gitignore_naming_dot_env(self, tmp_path: Path) -> None:
        """`.env` is not written, so the ignore rule is what has to be there
        *before* the user creates one by hand from the printed instructions."""
        result = init_project(tmp_path / "my_demo")

        assert ".env" in result.gitignore.read_text()

    def test_it_never_writes_dot_env(self, tmp_path: Path) -> None:
        result = init_project(tmp_path / "my_demo")

        assert not (result.directory / ".env").exists()

    def test_the_starter_is_a_package_that_validates(self, tmp_path: Path) -> None:
        result = init_project(tmp_path / "my_demo")

        assert result.starter is not None
        assert (result.starter / "workflow.json").is_file()
        assert cli.main(["validate", str(result.starter)]) == cli.EXIT_OK

    def test_the_starter_pins_no_model(self, tmp_path: Path) -> None:
        """Story one, made literal on the filesystem: the first package an
        adopter owns runs on whatever provider extra they installed."""
        import json

        result = init_project(tmp_path / "my_demo")
        assert result.starter is not None
        document = json.loads((result.starter / "workflow.json").read_text())["document"]

        assert not document.get("settings", {}).get("model")

    def test_empty_skips_the_starter(self, tmp_path: Path) -> None:
        """For someone adding OpenStateGraph to a repository that already has
        packages of its own."""
        result = init_project(tmp_path / "my_demo", starter=False)

        assert result.starter is None
        assert result.workflows.is_dir()
        assert list(result.workflows.iterdir()) == []

    def test_the_workflows_directory_can_be_named(self, tmp_path: Path) -> None:
        result = init_project(tmp_path / "my_demo", workflows_dir="flows")

        assert result.workflows == (tmp_path / "my_demo" / "flows")
        assert load_config(result.config).workflows_dir == "flows"

    def test_the_project_it_writes_answers_its_own_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The end-to-end claim of T6 plus T7 together: from inside the
        starter, `workflows_root()` is the directory `init` just wrote."""
        import os

        from openstategraph.config_file import reset_active_config
        from openstategraph.workflows_root import workflows_root

        # `conftest` points this at a file that does not exist so the
        # checkout's own config cannot decide the suite's default; a test about
        # the *search* has to clear the thing that short-circuits it.
        monkeypatch.delenv("OPENSTATEGRAPH_CONFIG", raising=False)

        result = init_project(tmp_path / "my_demo", workflows_dir="flows")
        assert result.starter is not None
        cwd = Path.cwd()
        os.chdir(result.starter)
        try:
            reset_active_config()
            assert workflows_root() == result.workflows.resolve()
        finally:
            os.chdir(cwd)
            reset_active_config()


class TestTheFourExistingDirectoryCases:
    """The owner's requirement: if the folder exists, warn and force a rename
    or an explicit confirmed override. Four cases, four messages, exit codes
    fixed — and the confirmation is a flag, which is why it appears inside the
    refusal rather than in documentation somewhere."""

    def test_one_it_does_not_exist(self, tmp_path: Path, capsys) -> None:
        code = cli.main(["init", str(tmp_path / "my_demo")])

        assert code == cli.EXIT_OK
        assert "created" in capsys.readouterr().out

    def test_two_it_exists_and_is_empty(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "my_demo"
        target.mkdir()

        code = cli.main(["init", str(target)])
        printed = capsys.readouterr().out

        assert code == cli.EXIT_OK
        assert "exists and is empty — using it" in printed
        assert (target / "openstategraph.yaml").is_file()

    def test_three_it_is_already_an_openstategraph_project(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "my_demo"
        target.mkdir()
        (target / "openstategraph.yaml").write_text("version: 1\n")

        code = cli.main(["init", str(target)])
        printed = capsys.readouterr().err

        assert code == cli.EXIT_FAILURE
        assert "is already there" in printed
        assert "nothing was written" in printed
        assert "--force" in printed
        # Nothing was written: the file it would have written is still theirs.
        assert (target / "openstategraph.yaml").read_text() == "version: 1\n"
        assert not (target / "workflows").exists()

    def test_four_it_exists_and_is_not_ours(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "my_demo"
        target.mkdir()
        for index in range(14):
            (target / f"file{index}.txt").write_text("x")

        code = cli.main(["init", str(target)])
        printed = capsys.readouterr().err

        assert code == cli.EXIT_FAILURE
        assert "already exists and has 14 files in it" in printed
        assert "Nothing was written" in printed
        assert "--force" in printed
        assert not (target / "openstategraph.yaml").exists()

    def test_the_count_is_singular_when_there_is_one(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "my_demo"
        target.mkdir()
        (target / "README.md").write_text("x")

        cli.main(["init", str(target)])

        assert "has 1 file in it" in capsys.readouterr().err

    def test_the_refusals_are_distinguishable(self, tmp_path: Path, capsys) -> None:
        """Case three and case four send the reader to different next moves —
        *open it* versus *pick another name* — so they must never collapse into
        one sentence."""
        ours = tmp_path / "ours"
        ours.mkdir()
        (ours / "openstategraph.yaml").write_text("version: 1\n")
        theirs = tmp_path / "theirs"
        theirs.mkdir()
        (theirs / "README.md").write_text("x")

        cli.main(["init", str(ours)])
        first = capsys.readouterr().err
        cli.main(["init", str(theirs)])
        second = capsys.readouterr().err

        assert first != second
        assert "openstategraph serve" in first
        assert "pick another name" in second


class TestForceAddsAndNeverOverwrites:
    def test_force_uses_a_directory_that_is_not_ours(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "my_demo"
        target.mkdir()
        (target / "README.md").write_text("mine")

        code = cli.main(["init", str(target), "--force"])

        assert code == cli.EXIT_OK
        assert (target / "openstategraph.yaml").is_file()
        assert (target / "README.md").read_text() == "mine"

    def test_force_never_overwrites_a_file_it_did_not_write(self, tmp_path: Path) -> None:
        """C5: only the "directory is not empty" precondition is waived. The
        standing refusal to overwrite is untouched."""
        target = tmp_path / "my_demo"
        target.mkdir()
        (target / "openstategraph.yaml").write_text("version: 1\n")
        (target / ".gitignore").write_text("node_modules\n")

        code = cli.main(["init", str(target), "--force"])

        assert code == cli.EXIT_OK
        assert (target / "openstategraph.yaml").read_text() == "version: 1\n"
        assert (target / ".gitignore").read_text() == "node_modules\n"

    def test_an_existing_starter_is_left_alone_and_said_so(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "my_demo"
        (target / "workflows" / "starter").mkdir(parents=True)
        (target / "workflows" / "starter" / "workflow.json").write_text("{}")
        # The config file is what makes this project *ours*, and so its
        # workflows root is ours too (production-ready/68). Without it, a
        # pre-existing `workflows/` is somebody else's and `--force` refuses
        # before reaching the starter at all — a different promise, tested in
        # `TestAWorkflowsDirectoryThatWasAlreadyThere`. This test's promise is
        # the one that survives either way: a starter already there is never
        # overwritten.
        (target / "openstategraph.yaml").write_text("version: 1\n")

        code = cli.main(["init", str(target), "--force"])
        printed = capsys.readouterr().out

        assert code == cli.EXIT_OK
        assert (target / "workflows" / "starter" / "workflow.json").read_text() == "{}"
        assert "already there" in printed

    def test_a_file_where_the_directory_should_be_is_refused(self, tmp_path: Path) -> None:
        target = tmp_path / "my_demo"
        target.write_text("not a directory")

        with pytest.raises(ScaffoldError, match="not a directory"):
            init_project(target)


class TestWhatItPrints:
    def test_it_prints_the_default_model_and_why(self, tmp_path: Path, capsys) -> None:
        """`init` is where story one is first *shown*: the extra chose the
        vendor, and the one thing left is the key."""
        from openstategraph.providers import provider_catalogue

        cli.main(["init", str(tmp_path / "my_demo")])
        printed = " ".join(capsys.readouterr().out.split())
        elected = provider_catalogue().elected_default()

        assert (elected.model or "(none)") in printed
        # The one sentence is composed once, in `ProviderDefault`, so the CLI
        # cannot invent a second wording. Whitespace-normalised because it is
        # wrapped for the terminal.
        assert elected.reason in printed

    def test_it_prints_how_to_make_dot_env_without_making_one(self, tmp_path: Path, capsys) -> None:
        cli.main(["init", str(tmp_path / "my_demo")])
        printed = capsys.readouterr().out

        assert ".env" in printed
        assert "openstategraph env-example" in printed
        assert not (tmp_path / "my_demo" / ".env").exists()

    def test_it_prints_the_next_two_commands(self, tmp_path: Path, capsys) -> None:
        cli.main(["init", str(tmp_path / "my_demo")])
        printed = capsys.readouterr().out

        assert "openstategraph serve" in printed
        assert "openstategraph run" in printed

    def test_no_argument_means_the_current_directory(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """The shape someone adding OpenStateGraph to an existing repository
        wants. `init .` is the same thing, spelled."""
        here = tmp_path / "here"
        here.mkdir()
        monkeypatch.chdir(here)

        code = cli.main(["init"])

        assert code == cli.EXIT_OK
        assert (here / "openstategraph.yaml").is_file()


class TestAWorkflowsDirectoryThatWasAlreadyThere:
    """Ticket production-ready/68.

    `init` is careful about somebody else's *project* directory and was silent
    about the one directory it is most likely to collide over. Two things would
    share a root — theirs and ours — and `WorkflowStore.list` would scan their
    folders from then on.

    The consent question is the whole design, and reproducing it is what
    settled it: the collision is reachable **only** under `--force`, because a
    non-empty target is already refused and a target that does not exist cannot
    contain a `workflows/`. So `--force` cannot also be the waiver — that would
    make this refusal unreachable. The waiver is instead the marker case two
    already uses: a target carrying an OpenStateGraph config file is *ours*,
    its `workflows/` is ours, and re-running `init --force` there stays
    idempotent. A target with no config is somebody else's, and their
    `workflows/` is theirs.
    """

    def test_it_refuses_to_move_into_a_workflows_directory_that_is_not_ours(
        self, tmp_path: Path, capsys
    ) -> None:
        target = tmp_path / "my_demo"
        (target / "workflows" / "their-thing").mkdir(parents=True)
        (target / "workflows" / "their-thing" / "README.md").write_text("theirs")

        code = cli.main(["init", str(target), "--force"])
        printed = capsys.readouterr().err

        assert code == cli.EXIT_FAILURE
        assert "workflows/" in printed
        assert "Nothing was written" in printed
        # Written nothing: not the config, not the starter.
        assert not (target / "openstategraph.yaml").exists()
        assert not (target / "workflows" / "starter").exists()
        assert (target / "workflows" / "their-thing" / "README.md").read_text() == "theirs"

    def test_the_refusal_names_the_exit_that_exists(self, tmp_path: Path, capsys) -> None:
        """`--workflows-dir` ships today. A refusal that does not name it makes
        a user go and look for it."""
        target = tmp_path / "my_demo"
        (target / "workflows").mkdir(parents=True)

        cli.main(["init", str(target), "--force"])

        assert "--workflows-dir" in capsys.readouterr().err

    def test_the_named_exit_actually_works(self, tmp_path: Path, capsys) -> None:
        target = tmp_path / "my_demo"
        (target / "workflows" / "their-thing").mkdir(parents=True)

        code = cli.main(["init", str(target), "--force", "--workflows-dir", "agents"])

        assert code == cli.EXIT_OK
        assert (target / "agents" / "starter").is_dir()
        assert not (target / "workflows" / "starter").exists()

    def test_our_own_project_is_not_refused_so_a_re_run_stays_idempotent(
        self, tmp_path: Path, capsys
    ) -> None:
        """A target carrying our config file is ours, and so is its
        `workflows/`. `init x --force` twice must not start refusing."""
        target = tmp_path / "my_demo"
        target.mkdir()

        assert cli.main(["init", str(target)]) == cli.EXIT_OK
        capsys.readouterr()

        code = cli.main(["init", str(target), "--force"])

        assert code == cli.EXIT_OK
        assert (target / "workflows" / "starter").is_dir()

    def test_it_is_distinguishable_from_the_non_empty_refusal(
        self, tmp_path: Path, capsys
    ) -> None:
        """Case four sends the reader to *pick another name*; this one sends
        them to *pick another workflows root*. Different moves, different
        sentences."""
        theirs = tmp_path / "theirs"
        theirs.mkdir()
        (theirs / "README.md").write_text("x")
        shared = tmp_path / "shared"
        (shared / "workflows").mkdir(parents=True)

        cli.main(["init", str(theirs)])
        non_empty = capsys.readouterr().err
        cli.main(["init", str(shared), "--force"])
        collision = capsys.readouterr().err

        assert non_empty != collision
        assert "pick another name" in non_empty
        assert "--workflows-dir" not in non_empty

    def test_the_suggested_root_is_never_the_one_that_just_collided(
        self, tmp_path: Path, capsys
    ) -> None:
        """Found by trying to break it: the refusal printed
        `--workflows-dir agents` to a user who had just passed
        `--workflows-dir agents`. A suggestion that repeats the failing input
        is a loop, not an exit."""
        target = tmp_path / "my_demo"
        (target / "agents").mkdir(parents=True)

        cli.main(["init", str(target), "--force", "--workflows-dir", "agents"])
        printed = capsys.readouterr().err

        assert "--workflows-dir agents\n" not in printed
        assert "--workflows-dir agents_2" in printed

    def test_the_suggestion_walks_past_names_that_are_also_taken(
        self, tmp_path: Path, capsys
    ) -> None:
        target = tmp_path / "my_demo"
        (target / "workflows").mkdir(parents=True)
        (target / "workflows_2").mkdir()

        cli.main(["init", str(target), "--force"])

        assert "--workflows-dir workflows_3" in capsys.readouterr().err

    def test_a_file_standing_where_the_root_should_be_says_so(
        self, tmp_path: Path, capsys
    ) -> None:
        """`workflows/` with a trailing slash is a lie when it is a file, and
        `mv` is the wrong advice. Mirrors the refusal one level up, which
        already distinguishes a file from a directory."""
        target = tmp_path / "my_demo"
        target.mkdir()
        (target / "workflows").write_text("not a directory")

        code = cli.main(["init", str(target), "--force"])
        printed = capsys.readouterr().err

        assert code == cli.EXIT_FAILURE
        assert "is not a directory" in printed
        assert "Nothing was written" in printed
        assert not (target / "openstategraph.yaml").exists()
        assert (target / "workflows").read_text() == "not a directory"
