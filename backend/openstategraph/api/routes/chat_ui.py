"""The two routes that serve the bundled `/chat` page, not the API.

`include_in_schema=False` on both, and ticket 15 noted why they are their own
module: `/chat/mermaid.js` is not an API route at all — it serves an asset, and
it belongs in none of the routers named after an API subject.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/chat", include_in_schema=False)
def chat_page() -> Any:
    """The customer chat surface (ticket 64) — one self-contained page."""

    from openstategraph.api.chat_page import chat_page_html

    # Read per request, not the import-time constant: chat.html is not a
    # .py file, so uvicorn's reloader never picks up edits to it — a
    # cached constant serves stale markup until a coincidental restart.
    return HTMLResponse(chat_page_html())


@router.get("/chat/mermaid.js", include_in_schema=False)
def chat_mermaid_asset() -> Any:
    """Mermaid for the /chat live-flow view (ticket 68) — never a CDN.

    Two homes, one behaviour: the wheel carries its own copy as package
    data (scale-and-adopt ticket 01, `hatch_build.py`), and a checkout
    serves the repo's own `node_modules` so the page cannot version-skew
    against the editor's copy. A checkout with no `npm install` still 404s
    here, and `/chat` degrades to "flow view unavailable" rather than
    breaking.
    """
    from fastapi.responses import FileResponse

    from openstategraph.api.editor_assets import PACKAGED_MERMAID

    asset = PACKAGED_MERMAID
    if not asset.is_file():
        asset = Path(__file__).resolve().parent.parent.parent.parent / (
            "node_modules/mermaid/dist/mermaid.min.js"
        )
    if not asset.is_file():
        raise HTTPException(status_code=404, detail="mermaid asset not installed")
    return FileResponse(asset, media_type="text/javascript")
