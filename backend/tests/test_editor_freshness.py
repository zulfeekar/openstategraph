"""The served editor says when it is older than the source (production-ready 60).

The owner asked why both `localhost:8000` and `localhost:5273` render an editor.
They are two editors: 5273 is Vite serving `src/` with hot reload, 8000 is
`openstategraph serve` hosting the API and the **built** bundle from `dist/`.
The design is right — 8000 is the product — and the trap is that its editor is
only as fresh as the last `npm run build`, with nothing saying so.

A guard already existed and was pointed the wrong way:
`test_the_wheel_ships_a_current_editor.py` stops a *wheel* shipping stale, and
fired correctly during this session. It protects nobody with a browser open.
Same fact, two audiences, one unserved.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.editor_freshness import (
    STALE_EDITOR_WARNING,
    editor_is_stale,
    warn_if_stale,
)


def _checkout(tmp_path: Path, *, built_after: bool) -> Path:
    """A fake checkout with `dist/`, `src/` and the real build hook importable."""
    (tmp_path / "src").mkdir()
    (tmp_path / "dist").mkdir()
    source = tmp_path / "src" / "main.ts"
    index = tmp_path / "dist" / "index.html"
    if built_after:
        source.write_text("x")
        index.write_text("<html></html>")
        index.touch()
    else:
        index.write_text("<html></html>")
        source.write_text("x")  # written last, so newer than the build
    return tmp_path


class TestItAnswersOnlyWhenItCan:
    def test_an_installed_wheel_is_told_nothing(self, tmp_path: Path) -> None:
        """`None`, not `False`.

        `False` claims "this editor is current", and a site-packages install
        cannot claim that — there is no `src/` to compare against. Answering
        `False` would be a promise nothing checked, and a warning that fires for
        every real user because a path is missing is worse than the silence.
        """
        assert editor_is_stale(tmp_path) is None

    def test_a_dist_with_no_src_is_told_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "index.html").write_text("<html></html>")
        assert editor_is_stale(tmp_path) is None


class TestItAnswersInThisCheckout:
    def test_the_real_repository_gives_a_boolean(self) -> None:
        # Not which boolean — that depends on whether somebody has just built.
        # What is pinned is that the question *applies* here, which is the
        # difference between a checkout and an install.
        assert editor_is_stale() in (True, False)


class TestTheWarningIsSaidOnce:
    def test_nothing_is_logged_when_the_question_does_not_apply(
        self, tmp_path: Path
    ) -> None:
        assert warn_if_stale(tmp_path) is None

    def test_the_sentence_names_both_ways_out(self) -> None:
        # A warning that says only "you are stale" leaves a developer guessing.
        # Both remedies are real and one of them is instant.
        assert "npm run build" in STALE_EDITOR_WARNING
        assert "5273" in STALE_EDITOR_WARNING
