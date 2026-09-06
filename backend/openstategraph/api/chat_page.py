"""The customer chat surface — served from a real file (ticket 72).

The page itself lives in ``static/chat.html`` — an honest asset that editors
highlight, linters could parse, and Playwright can exercise — after living
its first days as a 365-line Python string (named in the OOP audit as the
repo's biggest style violation). The module keeps its import surface so
``main.py`` did not have to change.
"""

from pathlib import Path

_ASSET = Path(__file__).resolve().parent / "static" / "chat.html"


def chat_page_html() -> str:
    return _ASSET.read_text()


#: Backwards-compatible constant — evaluated at import, same behaviour.
CHAT_PAGE = chat_page_html()
