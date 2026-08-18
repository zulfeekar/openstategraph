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


#: Where a checkout keeps its copy, relative to the repository root. The same
#: string `hatch_build.MERMAID_SOURCE` vendors *from*, so the wheel and the
#: checkout are two locations of one file rather than two facts.
CHECKOUT_MERMAID = "node_modules/mermaid/dist/mermaid.min.js"


def mermaid_asset() -> Path | None:
    """The Mermaid bundle `/chat` renders its live flow diagram with.

    Two homes and one behaviour: the wheel's package data first, else the
    repository's own `node_modules` so the page cannot version-skew against
    the editor's copy. `None` is a real answer — an install whose build hook
    found nothing to vendor, or a checkout that has not run `npm install` —
    and the route turns it into a 404 the page degrades on. There is no third
    place to look, deliberately: the third place is a CDN, and shipping a
    user's graph past one is the thing this asset exists to avoid.

    **Here rather than in the route, because the route got it wrong**
    (production-ready 56). It counted `parent` four times from
    `api/routes/chat_ui.py` and arrived at `backend/`, so every source
    checkout 404'd and the flow diagram was simply missing. `checkout_root()`
    is this repository's one answer to "where is the repository", already
    load-bearing for `workflows_root` and the site pages, and it answers
    `None` when installed — which is exactly the branch that must not fall
    through to a guess.
    """
    if PACKAGED_MERMAID.is_file():
        return PACKAGED_MERMAID

    checkout = checkout_root()
    if checkout is not None and (checkout / CHECKOUT_MERMAID).is_file():
        return checkout / CHECKOUT_MERMAID

    return None


def serves_the_editor(path: str, accept: str) -> bool:
    """Should this unmatched path answer with the editor rather than a 404?

    The question a mistyped share link asks (production-ready 55.3).
    `?w=<slug>` is the real form, so `/w/<slug>` — the plausible guess — used
    to reach `StaticFiles`, miss, and put `{"detail":"Not Found"}` in front of
    a person in a browser. Three exclusions keep that from becoming a fallback
    that hides real failures:

    - **`api/`** — every real route is declared before the mount, so an unknown
      one lands here; HTML at a broken endpoint is a debugging session.
    - **anything with a file extension** — a stale `<script src>` must fail as
      a script. A bundle that 200s with a document is the confusing half-hour.
    - **a request that asked for something other than HTML** — a `fetch`
      naming `application/json` gets the 404 it can act on. `*/*` counts as
      willing: it is what curl sends, and what a browser sends for a
      navigation it has no opinion about.

    Pure, and takes the header rather than the request, so the rule is readable
    and testable without an HTTP client.
    """
    if path.startswith("api/") or path == "api":
        return False
    if "." in path.rsplit("/", 1)[-1]:
        return False
    return "text/html" in accept or "*/*" in accept or accept == ""


def serving_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Off by default so `scripts/dev.sh` and pytest are untouched — Vite
    serves the editor there, and this process must stay a pure API."""
    environment = os.environ if env is None else env
    return environment.get(SERVE_STATIC_ENV) == "1"


def editor_missing_html() -> str:
    """Read per call, never cached — the same reason `chat_page_html()` is."""
    return EDITOR_MISSING_PAGE.read_text()


def _editor_files(directory: Path) -> Any:
    """`StaticFiles` that answers a person before it answers a 404.

    The class is built inside the function for the same reason the import used
    to be: `fastapi` is the `[server]` extra, and importing it at module scope
    would make a compiler-only install pay for a web framework it never uses.

    Starlette signals a miss two ways depending on version and on `html=True`
    — a 404 response, or a raised `HTTPException` — so both are caught and
    asked the same question.
    """
    from fastapi.staticfiles import StaticFiles
    from starlette.datastructures import Headers

    # Starlette's, not FastAPI's. `fastapi.HTTPException` is a *subclass*, so
    # catching it would miss every miss `StaticFiles` itself raises — which is
    # exactly how the first version of this fallback silently never ran.
    from starlette.exceptions import HTTPException

    class EditorFiles(StaticFiles):
        async def get_response(self, path: str, scope: Any) -> Any:
            try:
                response = await super().get_response(path, scope)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                response = None
            if response is not None and response.status_code != 404:
                return response
            accept = Headers(scope=scope).get("accept", "")
            if not serves_the_editor(path, accept):
                if response is None:
                    raise HTTPException(status_code=404)
                return response
            return await super().get_response("index.html", scope)

    return EditorFiles(directory=directory, html=True)


def mount_editor(app: Any, env: Mapping[str, str] | None = None) -> Path | None:
    """Serve the editor at `/`, and return where it came from.

    Called last, after every route is declared, so `/api/*`, `/chat` and
    `/chat/mermaid.js` still win — `StaticFiles` only ever sees what nothing
    else claimed. `html=True` serves `index.html` at `/`; a path that matches
    no file falls back to the same page when `serves_the_editor` says a person
    in a browser is asking, and 404s exactly as before when it does not.
    """
    if not serving_enabled(env):
        return None

    directory = editor_dir(env)
    if directory is not None:
        app.mount("/", _editor_files(directory), name="editor")
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
