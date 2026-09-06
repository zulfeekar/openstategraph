"""A service that already exists mounts the product inside itself.

The adoption shape `docs/adoption.md` has never covered: a team's own FastAPI
application keeps every route it had, and gains the canvas, `/chat` and the
API under a path of its own choosing, reading the same `workflows/` the
service loads. One process, two surfaces.

Three things made that impossible without editing this package's source,
which is the bar an adopter is held to and therefore the bar this package is
held to:

1. **`create_app()` returned an app with no editor.** The mount was applied to
   the module-level singleton, *after* the factory returned, so every
   documented embedding path got the API and `/chat` and no canvas. A host
   could reach past the factory and mount `api.main.app`, but that is the
   process-wide instance with its own workflows root — not something a host
   should have to know about.
2. **Every URL in the built page was root-absolute.** `/assets/index-*.js` is
   a request to the *host's* origin root. The page loads and nothing in it
   works. Fixed on the other side of the seam — a relative build base plus the
   `<base href>` this module injects — and pinned in
   `src/theBundleCanBeMountedUnderAPath.test.ts` and
   `src/core/runtime/runtimeBaseUrl.test.ts`.
3. **A mounted sub-application's lifespan never runs.** Starlette does not
   propagate it, and ours is where the state directory is locked and where
   every sqlite handle is released (`api/main.single_server_lifespan`). Left
   alone, a host mount would silently hold the checkpointer open for the life
   of the process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openstategraph.api import editor_assets


def built_editor(directory: Path) -> Path:
    """The smallest thing that is recognisably a built SPA, with the relative
    asset URL the real build now emits."""
    (directory / "assets").mkdir(parents=True, exist_ok=True)
    (directory / "assets" / "app.js").write_text("export default 1;\n")
    (directory / "index.html").write_text(
        '<!doctype html><html><head>'
        '<script type="module" src="./assets/app.js"></script>'
        "</head><body><div id=\"root\"></div></body></html>"
    )
    return directory


@pytest.fixture()
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("OPENSTATEGRAPH_SERVE_STATIC", "1")
    monkeypatch.setenv("OPENSTATEGRAPH_STATIC_DIR", str(built_editor(tmp_path / "editor")))
    app = FastAPI()

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


class TestTheMount:
    def test_the_hosts_own_routes_are_untouched(self, host: FastAPI, tmp_path: Path) -> None:
        from openstategraph.api.embed import mount_openstategraph

        mount_openstategraph(host, "/osg", workflows_root=tmp_path / "workflows")

        assert TestClient(host).get("/healthz").json() == {"ok": True}

    def test_the_canvas_answers_under_the_mount(self, host: FastAPI, tmp_path: Path) -> None:
        from openstategraph.api.embed import mount_openstategraph

        mount_openstategraph(host, "/osg", workflows_root=tmp_path / "workflows")
        page = TestClient(host).get("/osg/", headers={"Accept": "text/html"})

        assert page.status_code == 200
        assert '<div id="root">' in page.text

    def test_the_page_states_the_prefix_it_was_mounted_at(
        self, host: FastAPI, tmp_path: Path
    ) -> None:
        """The one fact the bundle cannot know at build time. Everything the
        page loads afterwards — assets and API alike — is resolved against
        it."""
        from openstategraph.api.embed import mount_openstategraph

        mount_openstategraph(host, "/osg", workflows_root=tmp_path / "workflows")
        page = TestClient(host).get("/osg/", headers={"Accept": "text/html"})

        assert '<base href="/osg/">' in page.text

    def test_the_assets_the_page_names_are_reachable(
        self, host: FastAPI, tmp_path: Path
    ) -> None:
        from openstategraph.api.embed import mount_openstategraph

        mount_openstategraph(host, "/osg", workflows_root=tmp_path / "workflows")

        assert TestClient(host).get("/osg/assets/app.js").status_code == 200

    def test_the_api_answers_under_the_mount(self, host: FastAPI, tmp_path: Path) -> None:
        from openstategraph.api.embed import mount_openstategraph

        mount_openstategraph(host, "/osg", workflows_root=tmp_path / "workflows")

        assert TestClient(host).get("/osg/api/workflows").status_code == 200

    def test_a_deep_link_reaches_the_canvas_at_any_depth(
        self, host: FastAPI, tmp_path: Path
    ) -> None:
        """`/w/<slug>` is the plausible guess a share link makes, and under a
        mount it is two segments below the assets. The `<base href>` is what
        keeps those resolving; without it a relative build is worse than an
        absolute one."""
        from openstategraph.api.embed import mount_openstategraph

        mount_openstategraph(host, "/osg", workflows_root=tmp_path / "workflows")
        page = TestClient(host).get("/osg/w/anything", headers={"Accept": "text/html"})

        assert page.status_code == 200
        assert '<base href="/osg/">' in page.text

    def test_the_editor_reads_the_workflows_root_it_was_given(
        self, host: FastAPI, tmp_path: Path
    ) -> None:
        """The whole point of one process: the canvas lists what the service
        loads, not a directory of its own."""
        from openstategraph.api.embed import mount_openstategraph

        root = tmp_path / "workflows"
        (root / "theirs").mkdir(parents=True)
        (root / "theirs" / "workflow.json").write_text(
            '{"version": 1, "name": "Theirs", "nodes": [], "edges": []}'
        )
        mount_openstategraph(host, "/osg", workflows_root=root)

        rows = TestClient(host).get("/osg/api/workflows").json()

        assert [row["slug"] for row in rows] == ["theirs"]


class TestTheLifespan:
    def test_the_mounted_apps_lifespan_runs_inside_the_hosts(
        self, host: FastAPI, tmp_path: Path
    ) -> None:
        """Starlette does not propagate lifespan into a mounted sub-app, so
        the helper chains it onto the host's. Without this the state directory
        is never locked and no sqlite handle is ever released."""
        from openstategraph.api.embed import mount_openstategraph

        seen: list[str] = []
        mounted = mount_openstategraph(host, "/osg", workflows_root=tmp_path / "workflows")
        inner = mounted.router.lifespan_context

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def watched(app: Any) -> Any:
            seen.append("started")
            async with inner(app):
                yield
            seen.append("stopped")

        mounted.router.lifespan_context = watched

        with TestClient(host):
            assert seen == ["started"]

        assert seen == ["started", "stopped"]


class TestMountedAtTheRoot:
    def test_a_root_mount_states_the_root(self, host: FastAPI, tmp_path: Path) -> None:
        """`openstategraph serve` and the container are this case. A `<base
        href="/">` is what the browser already assumes, so nothing changes for
        them — but it is stated rather than omitted, so there is one code path
        and not two."""
        from openstategraph.api.embed import mount_openstategraph

        mount_openstategraph(host, "/", workflows_root=tmp_path / "workflows")
        page = TestClient(host).get("/", headers={"Accept": "text/html"})

        assert '<base href="/">' in page.text


class TestThePathIsChecked:
    @pytest.mark.parametrize("path", ["osg", "/osg/", ""])
    def test_a_path_that_is_not_a_rooted_prefix_is_refused(
        self, host: FastAPI, tmp_path: Path, path: str
    ) -> None:
        """Starlette accepts several of these and behaves differently for
        each. A refusal at mount time is a stack trace in a developer's
        terminal; the alternative is a page that half works in production."""
        from openstategraph.api.embed import mount_openstategraph

        with pytest.raises(ValueError):
            mount_openstategraph(host, path, workflows_root=tmp_path / "workflows")


class TestInjectionIsNotAStringReplace:
    def test_a_document_that_already_declares_a_base_is_not_given_a_second(
        self, tmp_path: Path
    ) -> None:
        """Two `<base>` tags is not a merge; the browser takes the first and
        the second is silent."""
        html = '<html><head><base href="/old/"><title>x</title></head></html>'

        assert editor_assets.with_base_href(html, "/osg/").count("<base") == 1
        assert '<base href="/osg/">' in editor_assets.with_base_href(html, "/osg/")

    def test_a_document_with_no_head_is_returned_unchanged(self) -> None:
        """Rather than guessing where to put it. This is not a build of ours,
        and a tag injected into the wrong place is worse than none."""
        html = "<!doctype html><body>hi</body>"

        assert editor_assets.with_base_href(html, "/osg/") == html
