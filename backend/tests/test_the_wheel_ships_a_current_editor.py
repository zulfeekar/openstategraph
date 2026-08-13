"""The wheel shipped an editor three days older than the code.

Found by serving the wheel and looking at it. The bundled editor still carried
the *pre-ticket-22* loop wording — the phrasing that ticket's own comment calls
wrong — and still knew `team.workflow`, a node type schema v3 collapsed the
same day. The owner spotted it from the rendering before the bundle confirmed
it: "you are running old code, the editor has splines, it's not correct."

`hatch_build.py` copies `<repo>/dist` — whatever `npm run build` last wrote —
and **fails loudly when there is no editor at all while shipping an old one in
silence**. That is this codebase's own "degrade loud, never silent" rule kept
by half, which is the shape of most of the defects found today.

Staleness is worse than cosmetic here. The editor and the backend are a
two-sided contract: `WORKFLOW_SCHEMA_VERSION` lives on both sides, and an
editor built before a bump refuses documents the backend now writes as "saved
by a newer version". A wheel pairing a new backend with an old editor is not
out of date, it is broken.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _touch(path: Path, when: int) -> None:
    os.utime(path, (when, when))


class TestAStaleEditorIsRefused:
    def test_it_names_the_situation_and_the_fix(self) -> None:
        from hatch_build import STALE

        assert "npm run build" in STALE
        assert "stale" in STALE.lower()

    def test_a_dist_older_than_the_sources_is_rejected(self, tmp_path: Path) -> None:
        from hatch_build import editor_is_stale

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.tsx").write_text("export {}")

        _touch(dist / "index.html", 1_000_000)
        _touch(src / "App.tsx", 2_000_000)

        assert editor_is_stale(dist, src) is True

    def test_a_dist_newer_than_the_sources_is_accepted(self, tmp_path: Path) -> None:
        from hatch_build import editor_is_stale

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")
        src = tmp_path / "src"
        src.mkdir()
        (src / "App.tsx").write_text("export {}")

        _touch(src / "App.tsx", 1_000_000)
        _touch(dist / "index.html", 2_000_000)

        assert editor_is_stale(dist, src) is False

    def test_a_missing_source_tree_is_not_stale(self, tmp_path: Path) -> None:
        """Building from our own sdist: there is no `src/` to compare against.

        Refusing there would break every downstream repackager over a check
        that cannot apply.
        """
        from hatch_build import editor_is_stale

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>")

        assert editor_is_stale(dist, tmp_path / "does-not-exist") is False

    def test_the_checked_in_editor_matches_the_checked_in_source(self) -> None:
        """The real one, against this working tree.

        This is the assertion that would have failed all day: `dist/` was built
        on the 10th while `src/` last changed on the 13th.
        """
        from hatch_build import editor_is_stale

        dist = REPO / "dist"
        if not (dist / "index.html").is_file():
            pytest.skip("no built editor in this checkout — run `npm run build`")

        assert not editor_is_stale(dist, REPO / "src"), (
            "dist/ is older than src/ — the wheel would ship a stale editor. "
            "Run `npm run build`."
        )
