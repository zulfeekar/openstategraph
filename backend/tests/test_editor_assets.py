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


def built_editor(directory: Path, marker: str = '<div id="root"></div>') -> Path:
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

        assert (
            editor_assets.editor_dir({"OPENSTATEGRAPH_STATIC_DIR": str(tmp_path / "empty")}) is None
        )

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

        mounted = editor_assets.mount_editor(
            app, {"OPENSTATEGRAPH_STATIC_DIR": str(built_editor(tmp_path / "d"))}
        )

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

    def test_a_mistyped_share_link_lands_in_the_editor(self, tmp_path: Path) -> None:
        """`/w/some-slug` served `{"detail":"Not Found"}` as plain text in the
        browser (production-ready 55.3). The real share URL is `?w=<slug>`, so
        the guessed form — and every typo of the real one — put a raw JSON body
        in front of someone who was trying to open a workflow.

        The editor is where they were going, so that is where they land. It
        reads `?w=` and finds nothing, which is the ordinary empty canvas.
        """
        app = FastAPI()
        editor_assets.mount_editor(
            app,
            {
                "OPENSTATEGRAPH_SERVE_STATIC": "1",
                "OPENSTATEGRAPH_STATIC_DIR": str(built_editor(tmp_path / "d")),
            },
        )

        response = TestClient(app).get("/w/some-slug")

        assert response.status_code == 200
        assert '<div id="root"></div>' in response.text

    def test_an_unknown_api_path_is_still_a_404(self, tmp_path: Path) -> None:
        """The fallback must not swallow the API. An unknown `/api/...` reaches
        the mount too — every real route is declared before it — and answering
        HTML there would turn a typo'd endpoint into a 200 nobody can debug."""
        app = FastAPI()
        editor_assets.mount_editor(
            app,
            {
                "OPENSTATEGRAPH_SERVE_STATIC": "1",
                "OPENSTATEGRAPH_STATIC_DIR": str(built_editor(tmp_path / "d")),
            },
        )

        assert TestClient(app).get("/api/nonesuch").status_code == 404

    def test_a_missing_asset_is_still_a_404(self, tmp_path: Path) -> None:
        """A stale `<script src>` must fail as a script, not arrive as HTML —
        a bundle that 200s with a document is the confusing half-hour."""
        app = FastAPI()
        editor_assets.mount_editor(
            app,
            {
                "OPENSTATEGRAPH_SERVE_STATIC": "1",
                "OPENSTATEGRAPH_STATIC_DIR": str(built_editor(tmp_path / "d")),
            },
        )

        assert TestClient(app).get("/assets/gone.js").status_code == 404

    def test_the_rule_is_a_function_anyone_can_read(self) -> None:
        """Pure, so the four cases above are decidable without an HTTP client."""
        html = "text/html,application/xhtml+xml"

        assert editor_assets.serves_the_editor("w/some-slug", html)
        assert editor_assets.serves_the_editor("anything/at/all", html)
        # What curl sends, and a browser navigation with no opinion.
        assert editor_assets.serves_the_editor("w/some-slug", "*/*")
        assert not editor_assets.serves_the_editor("api/nonesuch", html)
        assert not editor_assets.serves_the_editor("assets/gone.js", html)
        # Not a browser navigating: a fetch that asked for JSON gets the 404 it
        # can act on rather than a page it cannot parse.
        assert not editor_assets.serves_the_editor("w/some-slug", "application/json")

    def test_the_missing_page_is_a_file_not_a_python_string(self) -> None:
        """Same rule `chat_page.py` already follows — markup lives in markup."""
        assert editor_assets.EDITOR_MISSING_PAGE.is_file()
        assert "npm run build" in editor_assets.editor_missing_html()


class TestTheChatMermaidAsset:
    """`/chat/mermaid.js` 404'd in every source checkout (production-ready 56).

    The route's own docstring describes two homes and one behaviour — the
    wheel's package data, else the repository's `node_modules` — and the
    second half never worked, because the path was hand-counted from
    `api/routes/chat_ui.py` and landed one directory short of the repository
    root, on `backend/node_modules/`. Nothing in this repository has ever
    installed anything there.

    It is the exact defect `workflows_root.py` was written for and opens its
    docstring with: a root computed as a fixed number of `parents[...]` hops
    from whichever file happens to be asking. `checkout_root()` is the one
    answer to that question, and it is also the answer for *installed*, where
    there is no checkout and the packaged copy is the only home.

    The visible cost was not a stack trace. `/chat` degrades on a 404 to
    "flow view unavailable", so the live flow diagram was simply absent for
    every developer running from source, and looked like a decision.
    """

    def _fake_checkout(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A checkout that has run `npm install`, built rather than assumed.

        The first version of these two tests read the ambient repository and
        asserted `node_modules/mermaid` was there, on the stated reasoning
        that `npm run verify` needs it anyway. True of a developer's machine
        and false of CI's **backend** job, which installs Python and no Node
        at all — so the suite was green here and red there, which is the one
        thing a gate must never be. What is under test is the resolution
        rule, so the tree it resolves against is now built by the test.
        """
        vendored = tmp_path / "node_modules" / "mermaid" / "dist" / "mermaid.min.js"
        vendored.parent.mkdir(parents=True)
        vendored.write_text("/* a checkout's copy */")
        monkeypatch.setattr(editor_assets, "PACKAGED_MERMAID", tmp_path / "absent.js")
        monkeypatch.setattr(editor_assets, "checkout_root", lambda: tmp_path)
        return vendored

    def test_the_asset_resolves_in_a_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vendored = self._fake_checkout(tmp_path, monkeypatch)

        assert editor_assets.mermaid_asset() == vendored

    def test_it_is_not_looking_inside_backend(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The bug, named. `backend/node_modules` is not a directory anything
        # creates, so a path pointing there can only ever miss.
        self._fake_checkout(tmp_path, monkeypatch)
        resolved = editor_assets.mermaid_asset()

        assert resolved is not None
        assert "backend/node_modules" not in resolved.as_posix()
        assert resolved.parent.parent.parent.name == "node_modules"

    def test_this_repository_really_does_carry_it(self) -> None:
        """The one test that reads the machine — and skips rather than fails.

        Worth keeping: the tests above prove the rule, and this proves the
        rule meets a real tree. It is a skip and not a failure where Node was
        never installed, because "this job has no `node_modules`" is a fact
        about the job, not a defect in the asset.
        """
        root = editor_assets.checkout_root()
        if root is None or not (root / "node_modules" / "mermaid").is_dir():
            pytest.skip("no node_modules/mermaid here — nothing to check against")

        resolved = editor_assets.mermaid_asset()

        assert resolved is not None and resolved.is_file()

    def test_the_packaged_copy_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The wheel's own copy, written by `hatch_build.py`. It comes first
        # so an installed adopter never depends on a checkout existing.
        packaged = tmp_path / "mermaid.min.js"
        packaged.write_text("/* the wheel's copy */")
        monkeypatch.setattr(editor_assets, "PACKAGED_MERMAID", packaged)

        assert editor_assets.mermaid_asset() == packaged

    def test_an_install_with_no_package_data_resolves_to_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Installed, and the build hook found no `node_modules` to vendor
        # from. There is no third place to look, and inventing one would be
        # how a CDN gets back in.
        monkeypatch.setattr(editor_assets, "PACKAGED_MERMAID", tmp_path / "absent.js")
        monkeypatch.setattr(editor_assets, "checkout_root", lambda: None)

        assert editor_assets.mermaid_asset() is None

    def test_the_route_serves_it(self) -> None:
        from openstategraph.api.main import app

        # Same reasoning as `test_this_repository_really_does_carry_it`: this
        # one drives the real route against whatever the machine has, so a
        # machine with no Node is a skip rather than a red gate.
        if editor_assets.mermaid_asset() is None:
            pytest.skip("no mermaid on this machine — the 404 branch is tested below")

        response = TestClient(app).get("/chat/mermaid.js")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/javascript")
        assert len(response.content) > 100_000

    def test_the_route_404s_with_a_sentence_when_there_is_nothing_to_serve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph.api.main import app

        monkeypatch.setattr(editor_assets, "PACKAGED_MERMAID", tmp_path / "absent.js")
        monkeypatch.setattr(editor_assets, "checkout_root", lambda: None)

        response = TestClient(app).get("/chat/mermaid.js")

        assert response.status_code == 404
        assert "mermaid" in response.json()["detail"]

    def test_the_wheel_and_the_checkout_ask_one_function(self) -> None:
        # The route must not re-derive a path of its own: two answers to
        # "where is mermaid" is how this shipped broken while a test of the
        # other one would have passed.
        from openstategraph.api.routes import chat_ui

        source = Path(chat_ui.__file__).read_text(encoding="utf-8")

        assert "mermaid_asset" in source
        # The mechanism, not the word: a path counted off this file's own
        # location is what miscounted. The prose above may name the old path;
        # the code must not build one.
        assert "Path(__file__)" not in source
