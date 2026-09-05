"""`.env` reaches the environment — providers-and-credentials ticket 01.

The defect this closes, reproduced in a clean sandbox before the fix: a key
placed in `.env` was never read, and the resulting message told the user to do
the thing they had just done.

    MissingProviderKey: Provider "anthropic" has no credential —
      set ANTHROPIC_API_KEY in .env (see `openstategraph env-example`).

A closed loop. Good copy pointing at a mechanism that did not exist.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from openstategraph.dotenv import (
    find_env_file,
    load_env_file,
    parse_env_file,
)


class TestParsing:
    def test_the_shapes_people_actually_paste(self) -> None:
        parsed = parse_env_file(
            "\n".join(
                [
                    "# a comment",
                    "",
                    "ANTHROPIC_API_KEY=sk-ant-plain",
                    'OPENAI_API_KEY="sk-openai-quoted"',
                    "OPENSTATEGRAPH_OLLAMA_MODEL='gpt-oss:120b-cloud'",
                    "export OLLAMA_HOST=http://example",
                    "   SPACED   =   padded   ",
                    "NOT_A_LINE",
                ]
            )
        )
        assert parsed["ANTHROPIC_API_KEY"] == "sk-ant-plain"
        # Quotes are stripped because people copy them out of documentation.
        assert parsed["OPENAI_API_KEY"] == "sk-openai-quoted"
        assert parsed["OPENSTATEGRAPH_OLLAMA_MODEL"] == "gpt-oss:120b-cloud"
        # `export` is accepted because people paste it out of a shell.
        assert parsed["OLLAMA_HOST"] == "http://example"
        assert parsed["SPACED"] == "padded"
        assert "NOT_A_LINE" not in parsed


class TestInlineComments:
    """A trailing `# note` is a comment, not part of the value.

    Ticket 01 decided the opposite — deliberately, to keep the parser small.
    A real `.env` settled it (providers-and-credentials ticket 02): this line,
    written by hand and loaded on every CLI run,

        OLLAMA_ENDPOINT = "https://ollama.com"  # Adjust if needed

    arrived as `'"https://ollama.com"  # Adjust if needed'` — quotes intact,
    because the quote-stripper requires the first and last character to match
    and this one ends in `d`. The value was silently wrong rather than absent,
    which is the failure mode this project spends the most effort avoiding.
    """

    def test_the_line_that_forced_this(self) -> None:
        parsed = parse_env_file('OLLAMA_ENDPOINT = "https://ollama.com"  # Adjust if needed')
        assert parsed["OLLAMA_ENDPOINT"] == "https://ollama.com"

    def test_an_unquoted_value_loses_its_comment_too(self) -> None:
        assert parse_env_file("OLLAMA_HOST=http://example  # note")["OLLAMA_HOST"] == (
            "http://example"
        )

    def test_a_hash_inside_quotes_survives(self) -> None:
        """The quotes are what make it data rather than a comment."""
        assert parse_env_file('ANTHROPIC_API_KEY="sk-a # b"')["ANTHROPIC_API_KEY"] == "sk-a # b"

    def test_a_hash_with_no_space_before_it_is_part_of_the_value(self) -> None:
        """A credential may legitimately contain one, and often does.

        The whitespace is the signal. Cutting at every `#` would corrupt keys
        far more often than it would strip a comment.
        """
        assert parse_env_file("OPENAI_API_KEY=sk-abc#def")["OPENAI_API_KEY"] == "sk-abc#def"


@pytest.fixture(autouse=True)
def _restore_the_environment() -> Iterator[None]:
    """`load_env_file` writes into the real `os.environ`, so every test here
    mutates process-global state.

    Each test deletes the one key it is about, which is why this suite has
    never gone red — but a file with a second key, or a test added without the
    `delenv`, leaks into whatever runs next, and the failure appears somewhere
    else (reviews-2026-08-14 ticket 10). Snapshot and restore removes the
    class rather than the instances.
    """
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)


class TestLoading:
    def test_a_key_in_the_file_reaches_the_environment(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-the-file\n")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert load_env_file(tmp_path) == tmp_path / ".env"
        assert os.environ["ANTHROPIC_API_KEY"] == "from-the-file"

    def test_the_real_environment_always_wins(self, tmp_path: Path, monkeypatch) -> None:
        """The authority rule, and the one worth being certain of.

        An exported variable beats the file, so `ANTHROPIC_API_KEY=… run …`
        overrides it, a container's injected secret beats a stale `.env` baked
        into an image, and CI never has to delete a file to take control.
        """
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-the-file\n")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "already-exported")
        load_env_file(tmp_path)
        assert os.environ["ANTHROPIC_API_KEY"] == "already-exported"

    def test_no_file_is_not_a_problem(self, tmp_path: Path) -> None:
        # A deployment that exports its variables properly needs no `.env`.
        assert load_env_file(tmp_path) is None

    def test_it_is_found_from_a_subdirectory(self, tmp_path: Path, monkeypatch) -> None:
        # `openstategraph run ./workflows/demo` is as likely to be typed from a
        # subdirectory as from the project root.
        (tmp_path / ".env").write_text("OPENAI_API_KEY=found-from-below\n")
        deep = tmp_path / "workflows" / "demo"
        deep.mkdir(parents=True)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert find_env_file(deep) == tmp_path / ".env"
        load_env_file(deep)
        assert os.environ["OPENAI_API_KEY"] == "found-from-below"

    def test_an_unreadable_file_does_not_stop_the_run(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # The run may not need the key at all; if it does, the missing-credential
        # message will say so in its own words.
        path = tmp_path / ".env"
        path.write_text("ANTHROPIC_API_KEY=x\n")
        path.chmod(0o000)
        try:
            assert load_env_file(tmp_path) is None
        finally:
            path.chmod(0o600)


class TestTheLibrarySeamDoesNotLoadIt:
    def test_load_workflow_never_reads_a_dotenv(self) -> None:
        """The boundary this module exists to hold.

        Importing a library must not reach into the host application's process
        and rewrite its environment from a file on disk. `load_workflow` runs
        inside someone else's app; `cli.console_main` is a process the user
        launched. Same split LangChain and LangGraph draw.
        """
        import inspect

        from openstategraph import loader

        source = inspect.getsource(loader)
        assert "load_env_file" not in source, (
            "load_workflow must not populate the environment from a file — "
            "see openstategraph/dotenv.py"
        )


class TestEveryWayToLaunchTheProcessReadsIt:
    """The other half of the same boundary, and the half that was missing.

    `console_main` loads `.env`; `main` deliberately does not, because this
    project's own tests call `main()` in-process and a function that rewrites
    `os.environ` from disk poisons every test after it. That split is right.

    But `cli.py`'s `__main__` guard called **`main`**, so
    `python3 -m openstategraph.cli serve` — a process the user launched, by any
    reading — silently ran with no `.env`. Two documented ways to start the same
    CLI, one of them without credentials, and the symptom is not an error: every
    provider reads "needs key" and workflows run against mock data.

    Found live on 2026-08-18: `.claude/launch.json` starts the backend with
    `python3 -m uvicorn openstategraph.api.main:app`, which is the same bypass
    one layer further out. `scripts/dev.sh` has always known — it loads `.env`
    into the shell itself, in a block that exists for exactly this reason.
    """

    def test_the_module_entry_point_loads_the_file(self) -> None:
        import inspect

        from openstategraph import cli

        source = inspect.getsource(cli)
        # Only the guarded block, not everything after it: `console_main` is
        # *defined* below the guard, so a naive split matches its `def` line and
        # the assertion passes while the guard still calls `main`. Found by this
        # test passing when it should have been red.
        after = source.split('if __name__ == "__main__"')[-1]
        guard = "\n".join(
            line
            for line in after.splitlines()[1:]
            if line.startswith((" ", "\t")) or not line.strip()
        ).strip()
        assert "console_main()" in guard, (
            "`python -m openstategraph.cli` is a process the user launched, so it "
            "must read `.env` like the console script does. Calling `main()` here "
            "skips `load_env_file` and every provider silently reads 'needs key'."
        )
        assert "main()" in guard  # sanity: the guard still runs something

    def test_main_itself_still_does_not(self) -> None:
        # The half that must not change: `main` is a *function*, and this
        # project's tests call it in-process.
        import inspect

        from openstategraph import cli

        body = inspect.getsource(cli.main)
        assert "load_env_file" not in body


class TestOneWalkForTheProject:
    """The `.env` walk and the config walk are the same walk — `osg-agent-experience/47`.

    They were not. `find_config_file` walks up to the git root and stops
    there; this module walked up four parents from the working directory and
    stopped there. So a project deep enough — `workflows/<slug>/tools/` is
    already three — had its `openstategraph.yaml` found and the `.env` beside
    it not found, and the symptom is the one this whole module exists to end:
    every provider reads "needs a key" while the key sits in the file the
    error names.

    Reproduced before the fix, from `workflows/demo/a/b/c` in a project whose
    root held both files: `config: …/openstategraph.yaml`, `env: None`.
    """

    def test_the_env_beside_the_config_is_found_however_deep_you_stand(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / "openstategraph.yaml").write_text("workflows_dir: workflows\n")
        (tmp_path / ".env").write_text("OLLAMA_API_KEY=x\n")
        deep = tmp_path / "workflows" / "demo" / "a" / "b" / "c"
        deep.mkdir(parents=True)

        assert find_env_file(deep) == tmp_path / ".env"

    def test_the_walk_still_stops_at_the_git_root(self, tmp_path: Path) -> None:
        """The bound the config walk already draws, inherited rather than
        restated: a stray `.env` above somebody's project is not their
        project's credentials.
        """
        (tmp_path / ".env").write_text("OLLAMA_API_KEY=from-outside\n")
        project = tmp_path / "project"
        (project / ".git").mkdir(parents=True)
        assert find_env_file(project) is None


class TestAMalformedLineIsNamedByNumber:
    """The line the owner hit, and the two halves of the answer.

    A value holding `{}` or `;` unquoted breaks `source .env` in a shell, so a
    developer arrives here having been told their file is broken. It is not:
    this parser takes the value as it stands. What *is* skipped — a line with
    no `=` at all — is now reported, by **number only**, because the content
    of a line in a credentials file is a credential.
    """

    def test_a_value_a_shell_would_choke_on_is_taken_as_it_stands(self) -> None:
        parsed = parse_env_file("DSN=host=db;user=a{b}c\nOTHER=1\n")
        assert parsed["DSN"] == "host=db;user=a{b}c"
        assert parsed["OTHER"] == "1"

    def test_the_skipped_line_is_reported_by_number_and_never_by_content(self) -> None:
        from openstategraph.dotenv import scan_env_file

        scanned = scan_env_file("A=1\n\n# note\nthis is not a variable\nB=2\n")
        assert scanned.values == {"A": "1", "B": "2"}
        assert scanned.malformed == (4,)
        assert "this is not a variable" not in " ".join(map(str, scanned.malformed))

    def test_loading_warns_with_the_number_alone(self, tmp_path: Path, capsys) -> None:
        (tmp_path / ".env").write_text("OPENAI_API_KEY=k\nthis is not a variable\n")
        load_env_file(tmp_path)
        warning = capsys.readouterr().err
        assert "line 2" in warning
        assert "this is not a variable" not in warning


class TestTheGeneratedExampleRoundTrips:
    """`openstategraph env-example` prints a file people copy to `.env`.

    Nothing had ever run the one through the other, so a generator line this
    parser could not read would have shipped as a silently missing variable.
    """

    def test_every_generated_name_survives_the_parser(self) -> None:
        from openstategraph.providers import env_example_section, provider_catalogue

        text = env_example_section()
        parsed = parse_env_file(text)
        for spec in provider_catalogue().list():
            for variable in spec.env_vars:
                assert variable in parsed, variable
                assert parsed[variable] == ""


class TestStartupSaysWhetherItReadOne:
    """`startup_facts()` answers *did my key reach this process* — 47.

    Every other question a reader has at startup is answered there (which
    model, which workflows root, why that root). Whether the `.env` two feet
    away was read was not, so the only way to find out was to press Run.

    The count and never the names: a variable name in a credentials file is
    already half of what somebody should not paste into a support thread.
    """

    def test_a_project_with_a_dotenv_says_so_with_a_count(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from openstategraph import cli

        (tmp_path / ".git").mkdir()
        (tmp_path / ".env").write_text("OLLAMA_API_KEY=x\nOLLAMA_HOST=http://example\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        load_env_file(tmp_path)

        assert os.environ["OLLAMA_API_KEY"] == "x"
        assert ".env: read, 2 variables" in cli.startup_facts()

    def test_no_file_says_so_too(self, tmp_path: Path, monkeypatch) -> None:
        from openstategraph import cli

        (tmp_path / ".git").mkdir()
        monkeypatch.chdir(tmp_path)
        assert load_env_file(tmp_path) is None
        assert "no .env" in "\n".join(cli.startup_facts())
