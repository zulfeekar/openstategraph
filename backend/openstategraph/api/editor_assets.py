"""Where the built editor comes from, and how one origin serves the product.

**Tier 3, internal.** Scale-and-adopt ticket 01.

`pip install openstategraph[server]` used to give you a compiler and an HTTP
API for a *visual* workflow builder with no visuals: the canvas existed only
inside a git clone or the Docker image. The wheel now carries the built SPA as
package data, and this module is the single place anything decides where those
files are.

**One serving path, not two.** The container already mounted `dist/` at `/`
through an env-guarded block at the end of `api/main.py`; that block moved
here and grew a resolution order rather than being forked. Docker keeps
setting `OPENSTATEGRAPH_SERVE_STATIC=1` and `OPENSTATEGRAPH_STATIC_DIR`, and
gets the same behaviour it had.

**Resolution order** — the project's standing precedence rule (convention <
config < environment < explicit argument), with no config-file tier because
there is nothing here worth a file:

1. `OPENSTATEGRAPH_STATIC_DIR` — the deployment's own answer, and the only one
   that works when the assets live somewhere unguessable. If it names
   something that is not a build, the answer is *nothing*, not a quiet
   fallback to a different editor.
2. The copy inside this package — what a wheel ships and what `pip install`
   gets.
3. `<checkout>/dist` — what `npm run build` writes in a clone, so a source
   checkout serves what it just built without a copy step.

**Missing assets are a sentence.** A developer running `serve` from a checkout
that never ran `npm run build` gets a page saying exactly that, at 503. A bare
404 at `/` is indistinguishable from a broken install, and it is the failure
this module exists to make impossible.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Mapping

from openstategraph.workflows_root import checkout_root

logger = logging.getLogger(__name__)

#: Set by the container, by `openstategraph serve`, and by nobody else.
SERVE_STATIC_ENV = "OPENSTATEGRAPH_SERVE_STATIC"

#: An explicit directory of built assets. Wins over everything.
STATIC_DIR_ENV = "OPENSTATEGRAPH_STATIC_DIR"

#: The wheel's own copy. Written at build time by `backend/hatch_build.py`;
#: absent in a source checkout, which is why (3) above exists.
PACKAGED_EDITOR = Path(__file__).resolve().parent / "static" / "editor"

#: The /chat live-flow view's Mermaid, written by the same build hook. Kept
#: outside `editor/` so that directory stays a faithful copy of `dist/`.
PACKAGED_MERMAID = Path(__file__).resolve().parent / "static" / "vendor" / "mermaid.min.js"

#: The page shown when no build exists anywhere. A file, not a Python string —
#: the same rule `chat_page.py` follows.
EDITOR_MISSING_PAGE = Path(__file__).resolve().parent / "static" / "editor_missing.html"


def _is_build(directory: Path) -> bool:
    """`index.html` is the SPA's entry point; without it there is no editor."""
    return (directory / "index.html").is_file()


def editor_dir(env: Mapping[str, str] | None = None) -> Path | None:
    """The directory holding the built editor, or None if nothing built it."""
    environment = os.environ if env is None else env

    explicit = environment.get(STATIC_DIR_ENV, "").strip()
    if explicit:
        directory = Path(explicit).expanduser()
        if _is_build(directory):
            return directory
        logger.warning("%s=%s does not contain an index.html", STATIC_DIR_ENV, explicit)
        return None

    if _is_build(PACKAGED_EDITOR):
        return PACKAGED_EDITOR

    checkout = checkout_root()
    if checkout is not None and _is_build(checkout / "dist"):
        return checkout / "dist"

    return None


def serving_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Off by default so `scripts/dev.sh` and pytest are untouched — Vite
    serves the editor there, and this process must stay a pure API."""
    environment = os.environ if env is None else env
    return environment.get(SERVE_STATIC_ENV) == "1"


def editor_missing_html() -> str:
    """Read per call, never cached — the same reason `chat_page_html()` is."""
    return EDITOR_MISSING_PAGE.read_text()


def mount_editor(app: Any, env: Mapping[str, str] | None = None) -> Path | None:
    """Serve the editor at `/`, and return where it came from.

    Called last, after every route is declared, so `/api/*`, `/chat` and
    `/chat/mermaid.js` still win — `StaticFiles` only ever sees what nothing
    else claimed. `html=True` serves `index.html` at `/`; the editor has no
    client-side router, so it needs no catch-all.
    """
    if not serving_enabled(env):
        return None

    directory = editor_dir(env)
    if directory is not None:
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=directory, html=True), name="editor")
        logger.info("editor served from %s", directory)
        return directory

    from fastapi.responses import HTMLResponse

    @app.get("/", include_in_schema=False)
    def editor_not_built() -> Any:
        # 503, not 404. The route exists; the thing behind it has not been
        # built yet, and those are different facts with different fixes.
        return HTMLResponse(editor_missing_html(), status_code=503)

    logger.warning(
        "no built editor found — serving the 'run npm run build' page at /. "
        "The API and /chat are unaffected."
    )
    return None

# No `__all__` here on purpose: everything under `openstategraph/api/` is Tier 3
# — internal, no stability guarantee — and `__all__` reads as a promise. The
# promises are `openstategraph.__all__` and `openstategraph.abc`.
