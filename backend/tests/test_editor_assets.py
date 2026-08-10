"""The wheel must carry the canvas, and one origin must serve the product.

Scale-and-adopt ticket 01. The gap this closes: we called the project a
*visual* workflow builder and shipped 215 KB of Python with no UI, so the
canvas existed only for people who cloned the repository or ran Docker.

Three claims are pinned here, and each one has already been a real defect
somewhere in this class of packaging:

1. **Resolution order.** Explicit environment beats the packaged copy beats a
   checkout's `dist/` — the same precedence `workflows_root.py` uses, for the
   same reason.
2. **A missing build is a sentence, not a 404.** A developer running `serve`
   from a source checkout that never ran `npm run build` gets a page telling
   them exactly that. A bare 404 at `/` is indistinguishable from a broken
   install.
3. **The mount is off unless asked for.** `scripts/dev.sh` and pytest must see
   the app exactly as they always did — Vite serves the editor there.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openstategraph.api import editor_assets


def built_editor(directory: Path, marker: str = "<div id=\"root\"></div>") -> Path:
    """The smallest thing that is recognisably a built SPA."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(f"<!doctype html><html><body>{marker}</body></html>")
    return directory


class TestResolution:
    def test_the_environment_wins_over_everything(self, tmp_path: Path) -> None:
        explicit = built_editor(tmp_path / "somewhere-else")

        resolved = editor_assets.editor_dir({"OPENSTATEGRAPH_STATIC_DIR": str(explicit)})

        assert resolved == explicit

    def test_an_explicit_directory_that_is_not_a_build_resolves_to_nothing(
        self, tmp_path: Path
    ) -> None:
        """Loud, not silently falling back. Someone who names a directory and
        gets a *different* editor has a debugging session ahead of them."""
        (tmp_path / "empty").mkdir()

        assert editor_assets.editor_dir({"OPENSTATEGRAPH_STATIC_DIR": str(tmp_path / "empty")}) is None

    def test_the_packaged_copy_is_used_when_no_one_says_otherwise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        packaged = built_editor(tmp_path / "packaged")
        monkeypatch.setattr(editor_assets, "PACKAGED_EDITOR", packaged)

        assert editor_assets.editor_dir({}) == packaged

    def test_a_checkout_falls_back_to_its_own_dist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`npm run build` in a clone writes `dist/` at the repository root and
        nothing copies it into the package — a source checkout must still be
        able to serve what it just built."""
        monkeypatch.setattr(editor_assets, "PACKAGED_EDITOR", tmp_path / "absent")
        checkout = tmp_path / "checkout"
        built_editor(checkout / "dist")
        monkeypatch.setattr(editor_assets, "checkout_root", lambda: checkout)

        assert editor_assets.editor_dir({}) == checkout / "dist"

    def test_nothing_built_anywhere_resolves_to_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(editor_assets, "PACKAGED_EDITOR", tmp_path / "absent")
        monkeypatch.setattr(editor_assets, "checkout_root", lambda: None)

        assert editor_assets.editor_dir({}) is None


class TestMounting:
    def test_off_unless_asked_for(self, tmp_path: Path) -> None:
        """The dev stack's contract: uvicorn on :8000 serves the API and
        nothing else, because Vite on :5273 is serving the editor."""
        app = FastAPI()

        mounted = editor_assets.mount_editor(app, {"OPENSTATEGRAPH_STATIC_DIR": str(built_editor(tmp_path / "d"))})

        assert mounted is None
        assert TestClient(app).get("/").status_code == 404

    def test_the_built_editor_is_served_at_the_root(self, tmp_path: Path) -> None:
        directory = built_editor(tmp_path / "d")
        app = FastAPI()

        editor_assets.mount_editor(
            app,
            {"OPENSTATEGRAPH_SERVE_STATIC": "1", "OPENSTATEGRAPH_STATIC_DIR": str(directory)},
        )

        response = TestClient(app).get("/")
        assert response.status_code == 200
        assert '<div id="root"></div>' in response.text

    def test_routes_declared_before_the_mount_still_win(self, tmp_path: Path) -> None:
        """`/chat` and `/api/*` are the product too. StaticFiles is mounted at
        `/` and would swallow them if it were allowed to match first."""
        app = FastAPI()

        @app.get("/chat")
        def chat() -> dict[str, str]:
            return {"surface": "chat"}

        editor_assets.mount_editor(
            app,
            {
                "OPENSTATEGRAPH_SERVE_STATIC": "1",
                "OPENSTATEGRAPH_STATIC_DIR": str(built_editor(tmp_path / "d")),
            },
        )

        assert TestClient(app).get("/chat").json() == {"surface": "chat"}

    def test_a_source_checkout_that_never_built_gets_a_sentence_not_a_404(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(editor_assets, "PACKAGED_EDITOR", tmp_path / "absent")
        monkeypatch.setattr(editor_assets, "checkout_root", lambda: None)
        app = FastAPI()

        mounted = editor_assets.mount_editor(app, {"OPENSTATEGRAPH_SERVE_STATIC": "1"})

        response = TestClient(app).get("/")
        assert mounted is None
        # 503, not 404: the route exists and the service behind it does not
        # yet. A 404 says "no such thing", which is a different and wrong fact.
        assert response.status_code == 503
        assert "npm run build" in response.text
        assert "/chat" in response.text

    def test_the_missing_page_is_a_file_not_a_python_string(self) -> None:
        """Same rule `chat_page.py` already follows — markup lives in markup."""
        assert editor_assets.EDITOR_MISSING_PAGE.is_file()
        assert "npm run build" in editor_assets.editor_missing_html()
