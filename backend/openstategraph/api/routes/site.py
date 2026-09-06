"""The routes that serve the hand-written story pages, not the API.

Production-ready ticket 28. `include_in_schema=False` throughout, and its own
module for the same reason `chat_ui.py` is one: these serve *assets*, and they
belong to no API subject.

Two shapes of route, and the split is not cosmetic:

- **`/site/<page>.html`** is canonical, and it is where a browser actually
  sits. The pages cross-link by bare filename because they are also served as
  plain files; a browser at `/site/gallery.html` resolves `href="index.html"`
  to `/site/index.html`, which is right.
- **`/gallery` and `/behind-the-scenes`** are the names a human is given, and
  they redirect. Serving them in place would put the browser at `/gallery`,
  where that same `href="index.html"` resolves to `/index.html` — the editor's
  `StaticFiles` mount — and every link on the page would land on the SPA.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from openstategraph.api.site_pages import SITE_PAGES, SITE_PREFIX, page_path

router = APIRouter()

#: The friendly names, and the page each one means. `index` deliberately has
#: none: `/` is the editor, and a second landing page competing for the root of
#: an installed product would be a worse answer than a link in the nav.
FRIENDLY = {
    "/gallery": "gallery",
    "/behind-the-scenes": "behind-the-scenes",
}


def _redirect(page: str) -> RedirectResponse:
    # 307, not 301: a permanent redirect is cached by the browser essentially
    # forever, and these paths are one release away from being reconsidered.
    return RedirectResponse(f"{SITE_PREFIX}/{page}.html", status_code=307)


@router.get(SITE_PREFIX, include_in_schema=False)
def site_root() -> Any:
    """`/site` is a directory in spirit; send it to the page that opens it."""
    return _redirect("index")


@router.get(f"{SITE_PREFIX}/{{page}}.html", include_in_schema=False)
def site_page(page: str) -> Any:
    """One declared page, served from wherever this install keeps them.

    `page` is checked against the allow-list before it is ever joined to a
    path — `page_path` does that, and it is the only reason a URL segment
    reaching the filesystem is safe here.
    """
    found = page_path(page)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no such page: {page!r}. This build of openstategraph serves "
                f"{', '.join(SITE_PAGES)}; if one of those is missing, the "
                "install did not ship its site/ directory."
            ),
        )
    return FileResponse(found, media_type="text/html")


for _path, _page in FRIENDLY.items():
    # Declared in a loop so the friendly names stay a table rather than three
    # near-identical function bodies drifting apart.
    router.add_api_route(
        _path,
        (lambda page=_page: _redirect(page)),  # type: ignore[misc]
        methods=["GET"],
        include_in_schema=False,
    )
