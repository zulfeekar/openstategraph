"""Where the hand-written story pages come from.

**Tier 3, internal.** Production-ready ticket 28.

`site/` holds three self-contained pages — the landing page, the gallery of
worked examples, and the five-artifact walk-through. They had exactly one route
to a reader, GitHub Pages, and that route has never once worked: `pages.yml`
has failed on every run it has ever had, each with `HttpError: Not Found` from
`actions/configure-pages`, because the repository has no Pages site to deploy
to. The gallery existed for a day before its own owner could not find it.

So the product serves them. A `pip install openstategraph[server]` already ships
an HTTP API and the built editor; three more files is nothing, and it puts the
story one URL from the canvas for every installed user, deployed or not.

**Resolution order** mirrors `editor_assets` exactly — the project's standing
precedence rule (convention < config < environment), with no config-file tier:

1. `OPENSTATEGRAPH_SITE_DIR` — an explicit answer, for a deployment that keeps
   the pages somewhere unguessable. Naming a directory that is not a site
   yields *nothing*, never a quiet fallback to a different one.
2. The copy inside this package — what a wheel ships.
3. `<checkout>/site` — the committed source, so a clone serves what it edits.

**Two differences from the editor, both deliberate.**

The editor is gated behind `OPENSTATEGRAPH_SERVE_STATIC` because it mounts
`StaticFiles` at `/` and would otherwise swallow a Vite dev server's routes.
These are named paths that can swallow nothing, and a gallery you must set an
environment variable to reach is the defect ticket 28 opened with. Ungated.

And a missing site is a 404 with a sentence, not the editor's 503 page. The
editor's 503 exists because "you have not run `npm run build`" is a normal
state of a checkout with a normal fix. These pages need no build step — they
are committed HTML — so their absence means a broken install, which is the same
shape as `/chat/mermaid.js` with no `npm install`, and gets the same answer.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Mapping

from openstategraph.workflows_root import checkout_root

logger = logging.getLogger(__name__)

#: An explicit directory of pages. Wins over everything.
SITE_DIR_ENV = "OPENSTATEGRAPH_SITE_DIR"

#: The wheel's own copy, written at build time by `backend/hatch_build.py`.
#: Absent in a source checkout, which is why (3) above exists.
PACKAGED_SITE = Path(__file__).resolve().parent / "static" / "site"

#: The pages this server will serve, and the whole of it. A route that turned a
#: URL segment into a filename would be a directory traversal with extra steps;
#: adding a page is one entry here, which is the registry rule applied to the
#: smallest possible registry.
#:
#: `index` is included so the pages' own cross-links resolve — every one of them
#: is a bare filename, because these files are also served as plain files.
SITE_PAGES: tuple[str, ...] = ("index", "gallery", "behind-the-scenes")

#: Where the friendly names land. `/gallery` redirects here rather than serving
#: in place: the pages link to each other by filename, so the browser's URL has
#: to sit *inside* this prefix or `href="index.html"` resolves to `/index.html`,
#: which is the editor.
SITE_PREFIX = "/site"


def _is_site(directory: Path) -> bool:
    """`gallery.html` is the marker, not `index.html`.

    Every built frontend in this repository has an `index.html`, the editor
    included — so testing for it would happily accept the SPA's `dist/` as a
    site and serve the wrong thing at a 200.
    """
    return (directory / "gallery.html").is_file()


def site_dir(env: Mapping[str, str] | None = None) -> Path | None:
    """The directory holding the story pages, or None if this install has none."""
    environment = os.environ if env is None else env

    explicit = environment.get(SITE_DIR_ENV, "").strip()
    if explicit:
        directory = Path(explicit).expanduser()
        if _is_site(directory):
            return directory
        logger.warning("%s=%s does not contain a gallery.html", SITE_DIR_ENV, explicit)
        return None

    if _is_site(PACKAGED_SITE):
        return PACKAGED_SITE

    checkout = checkout_root()
    if checkout is not None and _is_site(checkout / "site"):
        return checkout / "site"

    return None


def page_path(name: str, env: Mapping[str, str] | None = None) -> Path | None:
    """The file for a declared page, or None — for an unknown name *or* a
    missing install. The route tells those apart in the sentence it returns."""
    if name not in SITE_PAGES:
        return None

    directory = site_dir(env)
    if directory is None:
        return None

    page = directory / f"{name}.html"
    return page if page.is_file() else None


# No `__all__`: everything under `openstategraph/api/` is Tier 3, internal, and
# `__all__` reads as a stability promise this module does not make.
