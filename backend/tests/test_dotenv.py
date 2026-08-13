"""`.env` reaches the environment — providers-and-credentials ticket 01.

The defect this closes, reproduced in a clean sandbox before the fix: a key
placed in `.env` was never read, and the resulting message told the user to do
the thing they had just done.

    MissingProviderKey: Provider "anthropic" has no credential —
      set ANTHROPIC_API_KEY in .env (see .env.example).

A closed loop. Good copy pointing at a mechanism that did not exist.
"""

from __future__ import annotations

import os
from pathlib import Path

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
