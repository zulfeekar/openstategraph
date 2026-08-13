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
                    "export OLLAMA_HOST=http://example  # trailing text is part of the value",
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
        assert parsed["OLLAMA_HOST"].startswith("http://example")
        assert parsed["SPACED"] == "padded"
        assert "NOT_A_LINE" not in parsed


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
        inside someone else's app; the CLI and `create_app` are processes the
        user launched. Same split LangChain and LangGraph draw.
        """
        import inspect

        from openstategraph import loader

        source = inspect.getsource(loader)
        assert "load_env_file" not in source, (
            "load_workflow must not populate the environment from a file — "
            "see openstategraph/dotenv.py"
        )
