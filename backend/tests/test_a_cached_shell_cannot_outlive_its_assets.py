"""A shell a browser kept must not name assets the server no longer has.

`osg-agent-experience/77`. The owner upgraded a try project rc13 → rc15 and
restarted `openstategraph serve` on the same port. Chrome showed a white page;
a browser pane with an empty cache showed the editor. Measured on 8124: `GET /`
answered with `ETag` and `Last-Modified` and **no `Cache-Control` at all**, so a
browser is free to reuse the document heuristically — and the document it kept
names `assets/index-<oldhash>.js`, which the new build does not serve. The only
evidence was a 404 in a console nobody had open.

Two headers settle it, and they pull in opposite directions on purpose:

- **The shell revalidates every load.** `no-cache` does not mean "do not
  store"; it means "ask first". The `ETag` already present makes that a 304 in
  the common case, so the cost is one conditional request, not a re-download.
- **A content-hashed asset never revalidates.** Its name changes when its bytes
  do, so `immutable` for a year is the honest statement, and it is what makes
  the first header cheap enough to mean.

The rule lives in one function rather than in each response, because the shell
is served from three places — `StaticFiles` at `/`, the SPA fallback for
`/w/<slug>`, and the `/chat` route, which is not `StaticFiles` at all — and a
header set in two of the three is the defect back in a quieter form.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openstategraph.api import editor_assets
from openstategraph.api.editor_assets import (
    IMMUTABLE_CACHE_CONTROL,
    SHELL_CACHE_CONTROL,
    cache_control_for,
)

SERVE = {"OPENSTATEGRAPH_SERVE_STATIC": "1"}


def built_editor(directory: Path) -> Path:
    """A build with the two shapes that matter: a shell and a hashed asset."""
    (directory / "assets").mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text('<!doctype html><html><body><div id="root"></div></body></html>')
    (directory / "assets" / "index-WfQkFQo-.js").write_text("console.log(1)")
    (directory / "favicon.svg").write_text("<svg/>")
    return directory


def serving(tmp_path: Path) -> TestClient:
    app = FastAPI()
    from openstategraph.api.routes import chat_ui

    app.include_router(chat_ui.router)
    editor_assets.mount_editor(app, SERVE | {"OPENSTATEGRAPH_STATIC_DIR": str(built_editor(tmp_path / "dist"))})
    return TestClient(app)


class TestTheRule:
    def test_the_shell_is_asked_about_every_time(self) -> None:
        assert cache_control_for("index.html") == SHELL_CACHE_CONTROL
        assert cache_control_for("") == SHELL_CACHE_CONTROL
        assert cache_control_for("chat") == SHELL_CACHE_CONTROL

    def test_a_hashed_asset_is_never_asked_about_again(self) -> None:
        assert cache_control_for("assets/index-WfQkFQo-.js") == IMMUTABLE_CACHE_CONTROL
        assert cache_control_for("assets/index-a1b2c3d4.css") == IMMUTABLE_CACHE_CONTROL

    def test_a_file_whose_name_carries_no_hash_still_revalidates(self) -> None:
        """`favicon.svg` keeps its name across every release, so a year of
        `immutable` on it is a year of the wrong icon with no way back."""
        assert cache_control_for("favicon.svg") == SHELL_CACHE_CONTROL
        assert cache_control_for("assets/logo.svg") == SHELL_CACHE_CONTROL

    def test_the_two_values_say_what_the_ticket_asked_for(self) -> None:
        assert SHELL_CACHE_CONTROL == "no-cache"
        assert IMMUTABLE_CACHE_CONTROL == "public, max-age=31536000, immutable"


class TestWhatIsActuallyServed:
    def test_the_root_document_revalidates(self, tmp_path: Path) -> None:
        assert serving(tmp_path).get("/").headers["cache-control"] == SHELL_CACHE_CONTROL

    def test_index_html_by_name_revalidates(self, tmp_path: Path) -> None:
        assert serving(tmp_path).get("/index.html").headers["cache-control"] == SHELL_CACHE_CONTROL

    def test_the_spa_fallback_revalidates(self, tmp_path: Path) -> None:
        """`/w/<slug>` is the same document reached by a different path, and a
        header set only on `/` would leave the deep link cacheable."""
        response = serving(tmp_path).get("/w/some-slug", headers={"accept": "text/html"})

        assert response.status_code == 200
        assert response.headers["cache-control"] == SHELL_CACHE_CONTROL

    def test_the_chat_page_revalidates(self, tmp_path: Path) -> None:
        """Not `StaticFiles`, and that is the point — it is the third shell."""
        assert serving(tmp_path).get("/chat").headers["cache-control"] == SHELL_CACHE_CONTROL

    def test_a_hashed_asset_is_immutable(self, tmp_path: Path) -> None:
        response = serving(tmp_path).get("/assets/index-WfQkFQo-.js")

        assert response.status_code == 200
        assert response.headers["cache-control"] == IMMUTABLE_CACHE_CONTROL

    def test_the_unbuilt_page_revalidates_too(self, tmp_path: Path) -> None:
        """The 503 "run npm run build" page is the shell when there is no
        build; a browser that cached *it* would keep it after the build."""
        app = FastAPI()
        editor_assets.mount_editor(app, SERVE | {"OPENSTATEGRAPH_STATIC_DIR": str(tmp_path / "nothing")})

        response = TestClient(app).get("/")

        assert response.status_code == 503
        assert response.headers["cache-control"] == SHELL_CACHE_CONTROL


class TestOneSeam:
    def test_nothing_else_writes_a_cache_control_value(self) -> None:
        """A second spelling of either header is the drift this file exists to
        prevent — one function decides, everything else calls it."""
        package = Path(editor_assets.__file__).resolve().parents[1]
        offenders = [
            module.relative_to(package).as_posix()
            for module in package.rglob("*.py")
            if module.name != "editor_assets.py"
            and ("max-age=" in module.read_text() or '"no-cache"' in module.read_text())
        ]

        assert offenders == []
