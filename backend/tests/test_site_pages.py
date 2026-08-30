"""The story pages are reachable from a `pip install`, not only from GitHub.

Production-ready ticket 28. `site/gallery.html` had existed for a day and the
owner could not find it, because the only route to it was GitHub Pages and
`pages.yml` has failed on every run it has ever had, each one ending
`HttpError: Not Found` out of `actions/configure-pages`, because no Pages
site exists on the repository to deploy to. These routes are the answer
that depends on no plan and no network: the pages ship inside the wheel and
`openstategraph serve` hands them out.

What each test pins, and the defect it prevents:

1. **`/gallery` and `/behind-the-scenes` exist and land on the page.** The
   named routes are the whole deliverable; without them the ticket is a
   directory of HTML nobody has a URL for.
2. **They redirect into `/site/`, and the redirect is the point.** Both pages
   cross-link by *filename* (`href="gallery.html"`), because they are also
   served by Pages as plain files. A page served at bare `/gallery` would
   resolve those links against `/`, where the editor's `StaticFiles` mount
   lives, and every link on it would land on the SPA. So the canonical URL is
   `/site/<page>.html` and the friendly names are redirects.
3. **The page set is an allow-list.** A route that turns a URL segment into a
   filesystem path is a directory-traversal defect waiting for someone to
   type `..`.
4. **Resolution mirrors `editor_assets`.** Environment, then package data,
   then the checkout — the project's standing precedence rule, and the same
   order the editor already uses, rather than a second scheme to learn.
5. **These routes are *not* behind `OPENSTATEGRAPH_SERVE_STATIC`.** That gate
   exists because the editor mounts `StaticFiles` at `/` and would swallow a
   Vite dev server. These are three named paths that can swallow nothing, and
   a user who has to discover an environment variable to find the gallery is
   back where ticket 28 started.
6. **They still win against the editor mount.** `mount_editor` claims `/`
   last; a route declared before it must survive that.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openstategraph.api import site_pages
from openstategraph.api.routes import site as site_routes


def built_site(root: Path) -> Path:
    """The smallest directory `site_dir` will accept as the real thing."""
    root.mkdir(parents=True, exist_ok=True)
    for page in site_pages.SITE_PAGES:
        (root / f"{page}.html").write_text(f"<!doctype html><title>{page}</title>")
    return root


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(site_routes.router)
    return TestClient(app)


class TestTheNamedRoutes:
    def test_gallery_lands_on_the_gallery(self, client: TestClient) -> None:
        response = client.get("/gallery")

        assert response.status_code == 200
        assert "OpenStateGraph" in response.text

    def test_behind_the_scenes_lands_on_the_walkthrough(self, client: TestClient) -> None:
        response = client.get("/behind-the-scenes")

        assert response.status_code == 200
        assert "One workflow, five artifacts" in response.text

    def test_the_friendly_name_redirects_rather_than_serving_in_place(
        self, client: TestClient
    ) -> None:
        """The reason is the pages' own links, not tidiness.

        They are written to be served as files by GitHub Pages too, so every
        cross-link is a bare filename. Served at `/gallery`, `href="index.html"`
        would resolve to `/index.html` — the editor.
        """
        response = client.get("/gallery", follow_redirects=False)

        assert response.status_code in (301, 302, 307, 308)
        assert response.headers["location"] == "/site/gallery.html"

    def test_the_canonical_url_serves_the_page_directly(self, client: TestClient) -> None:
        response = client.get("/site/gallery.html")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    def test_site_root_is_the_landing_page(self, client: TestClient) -> None:
        assert client.get("/site").url.path == "/site/index.html"


class TestOnlyTheDeclaredPages:
    def test_an_undeclared_name_is_a_404(self, client: TestClient) -> None:
        assert client.get("/site/secrets.html").status_code == 404

    @pytest.mark.parametrize(
        "attempt",
        [
            "/site/..%2f..%2fetc%2fpasswd.html",
            "/site/....//workflow.html",
            "/site/%2e%2e%2fpyproject.html",
        ],
    )
    def test_a_url_segment_never_becomes_a_path(self, client: TestClient, attempt: str) -> None:
        """The allow-list is the defence, not sanitising the input."""
        assert client.get(attempt).status_code in (307, 404)


class TestWhereThePagesComeFrom:
    def test_the_environment_wins(self, tmp_path: Path) -> None:
        directory = built_site(tmp_path / "elsewhere")

        assert site_pages.site_dir({site_pages.SITE_DIR_ENV: str(directory)}) == directory

    def test_an_environment_pointing_at_nothing_is_not_a_quiet_fallback(
        self, tmp_path: Path
    ) -> None:
        """Same rule as `editor_dir`: a deployment that names a directory and
        gets a *different* one silently is worse than getting nothing."""
        empty = tmp_path / "empty"
        empty.mkdir()

        assert site_pages.site_dir({site_pages.SITE_DIR_ENV: str(empty)}) is None

    def test_a_source_checkout_finds_its_own_site_directory(self) -> None:
        found = site_pages.site_dir({})

        assert found is not None
        assert (found / "gallery.html").is_file()

    def test_the_packaged_copy_is_preferred_over_the_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What a wheel ships wins, so an installed user never depends on a
        checkout that happens to be next door."""
        packaged = built_site(tmp_path / "packaged")
        monkeypatch.setattr(site_pages, "PACKAGED_SITE", packaged)

        assert site_pages.site_dir({}) == packaged

    def test_no_site_anywhere_is_a_sentence_not_a_stack_trace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(site_pages, "PACKAGED_SITE", tmp_path / "nope")
        monkeypatch.setattr(site_pages, "checkout_root", lambda: None)

        app = FastAPI()
        app.include_router(site_routes.router)
        response = TestClient(app).get("/site/gallery.html")

        assert response.status_code == 404
        assert "openstategraph" in response.json()["detail"].lower()


class TestItDoesNotDependOnTheEditorGate:
    def test_the_gallery_works_without_serve_static(self, tmp_path: Path) -> None:
        """`OPENSTATEGRAPH_SERVE_STATIC` guards a `StaticFiles` mount at `/`.
        Three named paths need no such guard, and requiring one would put the
        gallery back behind something nobody knows to set."""
        from openstategraph.api import editor_assets

        assert not editor_assets.serving_enabled({})

        app = FastAPI()
        app.include_router(site_routes.router)
        assert TestClient(app).get("/gallery").status_code == 200

    def test_the_routes_survive_the_editor_mount(self, tmp_path: Path) -> None:
        """`mount_editor` claims `/` with `StaticFiles` and is called last.
        Anything declared before it must still match first."""
        from openstategraph.api import editor_assets

        editor = tmp_path / "dist"
        editor.mkdir()
        (editor / "index.html").write_text("<title>the editor SPA</title>")

        app = FastAPI()
        app.include_router(site_routes.router)
        editor_assets.mount_editor(
            app,
            {
                editor_assets.SERVE_STATIC_ENV: "1",
                editor_assets.STATIC_DIR_ENV: str(editor),
            },
        )

        client = TestClient(app)
        assert "the editor SPA" in client.get("/").text
        assert "One workflow, five artifacts" in client.get("/behind-the-scenes").text


class TestTheGalleryCountsItselfHonestly:
    """A number in prose is the first thing to rot, and this page carries seven
    of them. They had rotted twice: ticket 45 was "the gallery says twenty-one
    and ships twenty-two", and ticket 47 was the same sentence one higher.

    **Ticket 45's fix was to edit the numbers, and that is why it drifted
    again.** `expected = {"twenty-two"}` sat in this file as a literal, so the
    page and the test agreed with each other and neither agreed with what ships.
    The expectation is *derived* now — from `examples/index.json`, the same file
    the wheel packages and `openstategraph examples list` reads — so the only
    way to make this pass is to make the page true.

    **What the word counts is packages, not sections**, and ticket 45 chose the
    other one. 23 examples ship; 22 have a `class="ex"` section of their own,
    because `nested-mounts-mid` is shown inside its parent's. A reader meeting
    "twenty-three examples, each with the graph it compiles to" is told the
    truth — every one of the 23 has its diagram on this page, which
    `test_the_page_shows_every_shipped_example` asserts — while "all
    twenty-two are validate-clean" was simply wrong about a package that is.
    """

    #: Cardinals big enough that they can only be a claim about the gallery.
    #: "three kinds of loop" and "eleven knowledge docs" are safe from this.
    CARDINALS = re.compile(
        r"\b(nineteen|twent(?:y|ieth)(?:-(?:one|two|three|four|five))?)\b",
        re.IGNORECASE,
    )

    #: Only as far as the regex above can reach. A twenty-sixth example is a
    #: `KeyError` here rather than a silent pass, which is the right failure.
    WORDS = {
        19: "nineteen",
        20: "twenty",
        21: "twenty-one",
        22: "twenty-two",
        23: "twenty-three",
        24: "twenty-four",
        25: "twenty-five",
    }

    @classmethod
    def _shipped_word(cls) -> str:
        """The cardinal the pages must use, read from what actually ships."""
        import json

        index = json.loads(
            (
                Path(site_pages.__file__).resolve().parent.parent / "examples" / "index.json"
            ).read_text()
        )
        return cls.WORDS[len(index["examples"])]

    @staticmethod
    def _entries(page: str) -> int:
        return len(re.findall(r'class="ex"', page))

    def test_the_page_shows_every_shipped_example(self) -> None:
        """Twenty-two entries for twenty-three packages, and the difference is
        one nested child shown inside its parent's section rather than a
        missing example. If that ever stops being the reason, this fails."""
        import json

        directory = site_pages.site_dir({})
        assert directory is not None
        page = (directory / "gallery.html").read_text()
        index = json.loads(
            (
                Path(site_pages.__file__).resolve().parent.parent
                / "examples"
                / "index.json"
            ).read_text()
        )

        shown = set(re.findall(r'class="ex" id="([a-z0-9-]+)"', page))
        packaged = {entry["slug"] for entry in index["examples"]}
        drawn = set(re.findall(r"<!--mmd:([a-z0-9-]+)-->", page))

        assert packaged - shown == {"nested-mounts-mid"}
        assert packaged <= drawn, "a shipped example with no diagram on the page"

    def test_every_cardinal_on_the_page_is_what_actually_ships(self) -> None:
        directory = site_pages.site_dir({})
        assert directory is not None
        page = (directory / "gallery.html").read_text()
        expected = self._shipped_word()

        found = {match.lower() for match in self.CARDINALS.findall(page)}

        assert found == {expected}, (
            f"gallery.html says {sorted(found)}; {expected} ship. "
            f"This is derived from examples/index.json — fix the page, not this number."
        )

    def test_the_landing_page_agrees_with_the_gallery(self) -> None:
        directory = site_pages.site_dir({})
        assert directory is not None
        index_page = (directory / "index.html").read_text()

        found = {match.lower() for match in self.CARDINALS.findall(index_page)}

        assert found == {self._shipped_word()}

    def test_a_section_count_is_not_the_claim_the_prose_makes(self) -> None:
        """The two numbers this page could mean, kept apart on purpose.

        22 sections and 23 packages, and the difference is `nested-mounts-mid`
        shown inside its parent's section. Ticket 45 made the prose mean
        *sections* and the lead went on saying "all twenty-two are
        validate-clean" about 23 packages. Pinned so a future reader knows the
        gap is a decision rather than an off-by-one nobody noticed.
        """
        directory = site_pages.site_dir({})
        assert directory is not None
        sections = self._entries((directory / "gallery.html").read_text())

        assert sections == 22
        assert self._shipped_word() == "twenty-three"


class TestOneHeaderNav:
    """workflow-gallery ticket 47 §2 and §3.

    Two defects with one cause: three pages each carrying their own copy of
    the header. `/gallery` had an FAQ link and `/behind-the-scenes` did not;
    `/index` had an *Examples* link neither of the others had; and the rule
    hiding the links on a phone was written three times at **two different
    breakpoints** (720px twice, 860px once). All three hid the nav with
    nothing in its place, so at 390px the only navigation was a footer at the
    bottom of a page 50 543px tall.

    Three static files and no templating step, so "one shared component" is
    enforced here rather than generated: the navs are compared to each other,
    and a fourth page added by copy-paste has to match or fail.
    """

    NAV = re.compile(r"<nav>(.*?)</nav>", re.S)
    LINK = re.compile(r'<a href="([^"]+)"[^>]*>([^<]+)</a>')

    @staticmethod
    def _page(name: str) -> str:
        directory = site_pages.site_dir({})
        assert directory is not None
        return (directory / name).read_text()

    def _links(self, name: str) -> list[tuple[str, str]]:
        body = self.NAV.search(self._page(name))
        assert body is not None, f"{name} has no header nav at all"
        return self.LINK.findall(body.group(1))

    @pytest.mark.parametrize("page", ["index.html", "gallery.html", "behind-the-scenes.html"])
    def test_every_page_offers_the_same_destinations(self, page: str) -> None:
        """Compared modulo `aria-current`, which is the one thing that may
        legitimately differ — it says which of them you are on."""
        assert self._links(page) == self._links("gallery.html")

    @pytest.mark.parametrize("page", ["index.html", "gallery.html", "behind-the-scenes.html"])
    def test_the_links_reach_every_page_of_the_site(self, page: str) -> None:
        targets = {href.split("#")[0] for href, _ in self._links(page) if href.split("#")[0]}

        for name in site_pages.SITE_PAGES:
            assert f"{name}.html" in targets, f"{page}'s nav cannot reach {name}"

    @pytest.mark.parametrize("page", ["index.html", "gallery.html", "behind-the-scenes.html"])
    def test_a_phone_is_not_left_with_no_navigation(self, page: str) -> None:
        """`display: none` on the links with no replacement is the defect.

        The links stay in the layout and scroll inside their own strip — the
        answer this site already gives for wide code and diagrams, so the body
        still never scrolls sideways.
        """
        source = self._page(page)

        assert ".nav nav { display: none; }" not in source
        assert "overflow-x: auto" in source

    @pytest.mark.parametrize("page", ["index.html", "gallery.html", "behind-the-scenes.html"])
    def test_the_three_pages_break_at_the_same_width(self, page: str) -> None:
        """720px on two pages and 860px on the third is three copies drifting,
        which is the same defect as the nav contents drifting."""
        breakpoints = set(re.findall(r"@media \(max-width: (\d+)px\) \{\s*\.nav ", self._page(page)))

        assert breakpoints == {"860"}


class TestTheWheelCarriesThem:
    def test_every_declared_page_is_packaged(self) -> None:
        """The build hook treats the pages as optional — a missing `site/` is
        not worth failing a build over. That leniency is exactly how a wheel
        could ship with no gallery and nobody notice, so this repository's own
        build is pinned here instead."""
        from hatch_build import SITE_DEST, site_force_include

        backend = Path(__file__).resolve().parent.parent
        packaged = site_force_include(backend)

        for page in site_pages.SITE_PAGES:
            assert f"{SITE_DEST}/{page}.html" in packaged.values()

    def test_the_packaged_location_is_where_the_server_looks(self) -> None:
        """Two constants naming one directory, in two files that never import
        each other — so they are compared rather than trusted."""
        from hatch_build import SITE_DEST

        assert site_pages.PACKAGED_SITE.as_posix().endswith(SITE_DEST)


class TestTheRealAppServesThem:
    def test_a_pip_install_reaches_the_gallery_from_the_app_it_gets(self) -> None:
        """The router being correct is not the claim — the claim is that the
        app `openstategraph serve` starts has it wired in."""
        from openstategraph.api.main import create_app

        client = TestClient(create_app())

        assert client.get("/gallery").status_code == 200
        assert client.get("/behind-the-scenes").status_code == 200
