"""The two routes that serve the bundled `/chat` page, not the API.

`include_in_schema=False` on both, and ticket 15 noted why they are their own
module: `/chat/mermaid.js` is not an API route at all — it serves an asset, and
it belongs in none of the routers named after an API subject.
"""

from __future__ import annotations

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

    Where it comes from is `editor_assets.mermaid_asset()`, and this route
    knows nothing else about it. It used to compute the checkout's path here,
    by counting `parent` from this file — and counted one short, so the
    fallback pointed at `backend/node_modules/` and every source checkout
    404'd (production-ready 56).

    A `None` is still a 404, and `/chat` degrades to "flow view unavailable"
    rather than breaking — that part was right and is unchanged.
    """
    from fastapi.responses import FileResponse

    from openstategraph.api.editor_assets import mermaid_asset

    asset = mermaid_asset()
    if asset is None:
        raise HTTPException(status_code=404, detail="mermaid asset not installed")
    return FileResponse(asset, media_type="text/javascript")
