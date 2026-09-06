"""The one guarded HTTP transport, shared **across** two families.

`web_fetch`/`web_search` (`prebuilt_web.py`) and the search-backend ladder
(`search_backends.py`, `workflow-gallery` 67) both need to reach the open
internet, and both need the same guard rails: only http(s), no
private/loopback/link-local address (SSRF), every redirect re-validated, a
real certifi context, one timeout. That is `CLAUDE.md`'s cross-family
sharing rule in its plainest form — "shared **across** families ... is
composition, a shared middleware/registry" — so it is a module both import,
not a copy in each, and not something either family's own base class owns
(a search backend and a fetch tool are not one family; see
`search_backends`' module docstring for the fuller argument).

Extracted from `prebuilt_web.py` unchanged, so `TavilyBackend` reuses
`_validate_url`, `_blocked_host`, `_GuardedRedirects`, the certifi context and
`_request` itself rather than reimplementing any of them — exactly what the
ticket that created this module asked for ("reuse it; do not bypass it").
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import ssl
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "openstategraph/0.1 (+local dev tool)"
FETCH_TIMEOUT = 15


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _blocked_host(hostname: str) -> bool:
    """True when the host resolves anywhere a server-side fetch must not go."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return True
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            return True
    return False


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Re-validates every redirect target — without this, a public page
    302-ing to an internal address walks straight past the SSRF check
    (found in self-review, not hypothetically rare: metadata-service
    redirects are the classic SSRF escalation)."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http(s) URLs are fetchable, got '{parsed.scheme or 'none'}'")
    if not parsed.hostname or _blocked_host(parsed.hostname):
        raise ValueError("That host is not reachable from here.")


def _request(
    url: str,
    *,
    data: bytes | None = None,
    user_agent: str = USER_AGENT,
    content_type: str = "application/x-www-form-urlencoded",
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    """One read of one URL, as `(status, body)`.

    The status is returned rather than discarded because a caller that cannot
    see it cannot tell a refusal from an empty answer — which is exactly what
    made a 202 challenge page read as "no results" for the whole of ticket 26.

    `content_type` defaults to the form encoding `web_search`'s DuckDuckGo
    rung posts, because that was the only POST here until the YouTube atom
    needed a JSON one (`prebuilt_youtube`). It is a parameter rather than a
    second transport so that the SSRF guard, the redirect re-validation, the
    certifi context and the timeout stay declared exactly once.

    `extra_headers` exists for `search_backends.TavilyBackend`, which must
    send `Authorization: Bearer <key>`. It is a dict merged on top of the two
    headers above rather than a second transport, for the same reason
    `content_type` is a parameter: one guarded request function, not one per
    caller.
    """
    _validate_url(url)
    opener = urllib.request.build_opener(
        _GuardedRedirects(), urllib.request.HTTPSHandler(context=_ssl_context())
    )
    headers = {"User-Agent": user_agent}
    if data is not None:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=data, headers=headers)
    with opener.open(request, timeout=FETCH_TIMEOUT) as resp:
        body: str = resp.read(600_000).decode("utf-8", errors="replace")
        return int(getattr(resp, "status", 200) or 200), body


def _strip_html(raw: str) -> str:
    """Tags gone, entities decoded, whitespace collapsed. Shared by
    `prebuilt_web`'s page-fetch path and `search_backends.DuckDuckGoBackend`'s
    title/snippet parsing."""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()
