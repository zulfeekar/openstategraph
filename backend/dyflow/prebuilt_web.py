"""Prebuilt web tools — the root assistant's window on the open internet.

The concierge's mental model (ticket 67, user): a generic chat where anything
can be asked. Domain questions route to specialist workflows; the rest lands
on the root's own agent, which therefore needs the open web — search and
fetch, both read-only GETs, both keyless.

Guard rails, structural as always:
- ``web_fetch`` refuses private/loopback/link-local addresses (SSRF), only
  http(s), and truncates hard — a fetch is a briefing, not an archive.
- ``web_search`` uses DuckDuckGo's HTML endpoint (no key, no tracking
  params); results are titles + URLs + snippets, and the model follows up
  with ``web_fetch`` on what looks right.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.parse
import urllib.request

from pydantic import BaseModel, Field

from dyflow.abc.tool import BaseTool, ToolResult

USER_AGENT = "dyflow/0.1 (+local dev tool)"
FETCH_TIMEOUT = 15
MAX_FETCH_CHARS = 8_000
MAX_RESULTS = 6


def _ssl_context():
    import ssl

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

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http(s) URLs are fetchable, got '{parsed.scheme or 'none'}'")
    if not parsed.hostname or _blocked_host(parsed.hostname):
        raise ValueError("That host is not reachable from here.")


def _get(url: str) -> str:
    _validate_url(url)
    opener = urllib.request.build_opener(
        _GuardedRedirects(), urllib.request.HTTPSHandler(context=_ssl_context())
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=FETCH_TIMEOUT) as resp:
        return resp.read(600_000).decode("utf-8", errors="replace")


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


class SearchArgs(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(description="What to search the web for.")


class WebSearchTool(BaseTool):
    """Keyless web search via DuckDuckGo's HTML endpoint."""

    name = "web_search"
    node_type = "tool.web-search"
    description = (
        "Search the web. Returns titles, URLs and snippets; follow up with "
        "web_fetch on the most promising URL. Use for anything current or "
        "outside your knowledge."
    )
    Args = SearchArgs

    #: Injectable for offline tests.
    def __init__(self, fetcher=None) -> None:
        self._fetch = fetcher or _get

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, SearchArgs)
        query = args.query.strip()
        if not query:
            return ToolResult.failure("Give a non-empty query.")
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        try:
            page = self._fetch(url)
        except Exception as exc:
            return ToolResult.failure(f"Search failed: {exc}")
        results = []
        for match in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(?:.*?'
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>)?',
            page,
            re.S,
        ):
            href, title, snippet = match.groups()
            # DDG wraps targets in a redirect: uddg carries the real URL.
            target = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
            results.append(
                f"- **{_strip_html(title)}**\n  {target}\n  {_strip_html(snippet or '')[:200]}"
            )
            if len(results) >= MAX_RESULTS:
                break
        if not results:
            return ToolResult.failure(f"No results for '{query}'.")
        return ToolResult(content="\n".join(results))


class FetchArgs(BaseModel):
    model_config = {"extra": "forbid"}
    url: str = Field(description="The http(s) URL to read.")


class WebFetchTool(BaseTool):
    """Read one public web page as plain text."""

    name = "web_fetch"
    node_type = "tool.web-fetch"
    description = (
        "Fetch one public web page and return its readable text (truncated). "
        "Use after web_search, or when the user gives a URL."
    )
    Args = FetchArgs

    def __init__(self, fetcher=None) -> None:
        self._fetch = fetcher or _get

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FetchArgs)
        try:
            raw = self._fetch(args.url.strip())
        except Exception as exc:
            return ToolResult.failure(f"Fetch failed: {exc}")
        text = _strip_html(raw)
        if not text:
            return ToolResult.failure("The page had no readable text.")
        suffix = " …(truncated)" if len(text) > MAX_FETCH_CHARS else ""
        return ToolResult(content=text[:MAX_FETCH_CHARS] + suffix)


WEB_TOOLS = [WebSearchTool(), WebFetchTool()]
