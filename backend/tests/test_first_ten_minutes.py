"""Two failures a stranger hits in their first ten minutes.

Both found by building the wheel into a clean venv and *using* it, which is the
only way either was going to surface — the repo's own
`scripts/clean_install_proof.sh` drives the CLI and boots the server, and
neither of these is visible to it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest


class TestDrawingAGraphNeedsNoProvider:
    """`openstategraph graph` exited 3 asking for a pip extra.

    Drawing the compiled topology is a *compile* operation — it calls
    `draw_mermaid()` on a graph and never invokes a model. But building the
    graph built a chat model, so the command demanded the resolved provider's
    integration package be installed. In a venv with only `[ollama]`, a
    document that resolved to Anthropic could not be *drawn*.

    `validate` was already fine, which is what makes this a `graph` bug rather
    than a policy: two read-only commands, one of them needing a vendor SDK.
    """

    def test_it_draws_with_no_provider_integration_available(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.cli import EXIT_OK, main
        from openstategraph.scaffold import new_package

        package = new_package(tmp_path, "d", template="loop", name="D")

        # No credential for anything: whatever resolves, its integration is the
        # one thing this command must not need.
        for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST"):
            monkeypatch.delenv(name, raising=False)

        assert main(["graph", str(package)]) == EXIT_OK

    def test_it_still_draws_the_loop(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """A picture nobody can read is not a fix."""
        from openstategraph.cli import main
        from openstategraph.scaffold import new_package

        package = new_package(tmp_path, "d", template="loop", name="D")
        main(["graph", str(package)])

        drawn = capsys.readouterr().out
        assert "grader1" in drawn
        assert "revise" in drawn

    def test_the_stand_in_says_why_if_anything_reaches_for_it(self) -> None:
        """It must not look like a model that merely failed."""
        from openstategraph.cli import _drawing_only_model
        from openstategraph.errors import MissingProviderKey

        with pytest.raises(MissingProviderKey) as caught:
            _drawing_only_model().invoke("hi")
        assert "graph" in str(caught.value)


class TestAnEmptyLogLevelDoesNotKillTheServer:
    """`serve` crashed on `OPENSTATEGRAPH_LOG_LEVEL=` — which the repo's own
    `.env.example` and `.env` both contain, unset.

    `logging.basicConfig(level="")` raises `ValueError: Unknown level: ''`, and
    it happened *after* the server printed its URLs, so it read as a server
    that had started. Lowercase `info` failed the same way, which is the more
    likely thing for a person to type.
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("", logging.INFO),
            ("   ", logging.INFO),
            ("info", logging.INFO),
            ("INFO", logging.INFO),
            ("debug", logging.DEBUG),
            ("WARNING", logging.WARNING),
            ("nonsense", logging.INFO),
        ],
    )
    def test_a_level_a_person_might_write(self, value: str, expected: int) -> None:
        from openstategraph.api.main import resolve_log_level

        assert resolve_log_level(value) == expected

    def test_an_unset_variable_is_the_documented_default(self) -> None:
        from openstategraph.api.main import resolve_log_level

        assert resolve_log_level(None) == logging.INFO

    def test_it_never_raises_whatever_is_in_the_environment(self) -> None:
        from openstategraph.api.main import resolve_log_level

        for value in ("", "  ", "10", "trace", "INFO ", os.linesep):
            assert isinstance(resolve_log_level(value), int)
