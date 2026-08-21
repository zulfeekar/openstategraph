"""Prebuilt web tools — the root assistant's window on the open internet.

The concierge's mental model (ticket 67, user): a generic chat where anything
can be asked. Domain questions route to specialist workflows; the rest lands
on the root's own agent, which therefore needs the open web — search and
fetch, both read-only GETs, both keyless.

Guard rails, structural as always:
- ``web_fetch`` refuses private/loopback/link-local addresses (SSRF), only
  http(s), and truncates hard — a fetch is a briefing, not an archive.
- ``web_fetch`` keeps the page's links, written inline as ``text (url)``
  (`workflow-gallery` 34, and ``_inline_links`` below for the narrowness).
- ``web_search`` uses DuckDuckGo's HTML endpoint (no key, no tracking
  params); results are titles + URLs + snippets, and the model follows up
  with ``web_fetch`` on what looks right.

## The search transport, and why it is not a plain GET (ticket 26)

Web Search shipped returning nothing on every query while Web Fetch worked,
and the offline tests stayed green the whole time: they inject a hand-written
SERP fragment, so they prove the regex and never the request.

Measured against the live endpoint: ``html.duckduckgo.com/html/`` now answers
**every GET with HTTP 202 and an anti-bot challenge page** — real HTML,
`result__a` nowhere in it — regardless of User-Agent. It answers a **form
POST** (`q=...`, `application/x-www-form-urlencoded`) with a real 200 SERP
that the existing parser reads perfectly. That is the request the endpoint's
own `<form>` makes, so this is using the page as published rather than
working around anything; nothing here solves or evades a challenge, and a
challenge that is served anyway is reported as the failure it is.

Which is the second half, and the more important one. `_get` returned only a
body, so a hard block and an empty result were the same value by the time
`_execute` saw them, and the tool told the agent `No results for '...'` — an
empty result presented as an answer, the defect class this project keeps
closing. The search transport returns `(status, body)` and the two failures
are now spelled differently.
"""

from __future__ import annotations

import html
import ssl
import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from typing import Any, Callable

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.progress import report_progress

USER_AGENT = "openstategraph/0.1 (+local dev tool)"
FETCH_TIMEOUT = 15
MAX_FETCH_CHARS = 8_000
MAX_RESULTS = 6

#: How many distinct URLs one fetched page may spell out inline.
#:
#: A cap rather than "all of them" because a page can be mostly links — a
#: nav-heavy aggregator or an ad farm — and the tool's whole job is to hand a
#: model the *readable* part of a page inside a budget. Past this many, the
#: remaining anchors render as their text alone, exactly as they always did.
MAX_FETCH_LINKS = 50

#: A URL longer than this is a session blob or a tracking payload, not
#: something a model is going to act on; its anchor keeps its text and loses
#: its address.
MAX_LINK_URL_CHARS = 200

#: DuckDuckGo's HTML endpoint and the method its own form uses. Named here
#: rather than built inline so the tool's transport is one readable fact.
SEARCH_URL = "https://html.duckduckgo.com/html/"

#: Sent only to `SEARCH_URL`. The honest UA above is what every ordinary
#: fetch still carries; this endpoint declines to serve its form results to
#: it, so a keyless search is either this or no keyless search at all.
SEARCH_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

#: Words that only appear on the challenge page, never on a SERP. The status
#: code is the primary signal; this is the backstop for the day the block
#: arrives with a 200, which is the next shape this endpoint can take without
#: telling anyone.
_CHALLENGE_MARKERS = ("confirm this search was made by a human", "anomaly.js")


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
) -> tuple[int, str]:
    """One read of one URL, as `(status, body)`.

    The status is returned rather than discarded because a caller that cannot
    see it cannot tell a refusal from an empty answer — which is exactly what
    made a 202 challenge page read as "no results" for the whole of ticket 26.

    `content_type` defaults to the form encoding `web_search` posts, because
    that was the only POST here until the YouTube atom needed a JSON one
    (`prebuilt_youtube`). It is a parameter rather than a second transport so
    that the SSRF guard, the redirect re-validation, the certifi context and
    the timeout stay declared exactly once.
    """
    _validate_url(url)
    opener = urllib.request.build_opener(
        _GuardedRedirects(), urllib.request.HTTPSHandler(context=_ssl_context())
    )
    headers = {"User-Agent": user_agent}
    if data is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers)
    with opener.open(request, timeout=FETCH_TIMEOUT) as resp:
        body: str = resp.read(600_000).decode("utf-8", errors="replace")
        return int(getattr(resp, "status", 200) or 200), body


def _get(url: str) -> str:
    """A page's text. `web_fetch`'s transport, unchanged — an ordinary GET."""
    return _request(url)[1]


def _search(url: str, query: str) -> tuple[int, str]:
    """`web_search`'s transport: the form POST the endpoint's own page makes.

    A GET to the same URL is answered with a 202 challenge whatever the
    User-Agent — measured, not assumed. See the module docstring.
    """
    return _request(
        url,
        data=urllib.parse.urlencode({"q": query}).encode(),
        user_agent=SEARCH_USER_AGENT,
    )


#: An `<a>` open tag carrying an `href`, and everything up to its close.
#: Deliberately the only thing here that yields a URL: nothing scans the
#: *text* for URL-shaped substrings, because that is how ordinary prose
#: ("see example.com/watch?v=x") turns into a link that does not exist.
_ANCHOR = re.compile(r'(?is)<a\b[^>]*?\bhref\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>')


def _inline_links(raw: str, base_url: str) -> str:
    """Rewrite `<a href=U>text</a>` to `text (U)` before the tags are stripped.

    `workflow-gallery` 34. `_strip_html` deletes a tag *with its attributes*,
    so a document whose value is "this title points there" arrived as titles
    and nothing else, and a `watch?v=` id could not be recovered from a
    ranking that plainly contained one.

    Tolerant in reading — single or double quotes, any attribute order, a
    relative href resolved against the page it came from. Strict in trusting —
    the URL is taken only from an `href` attribute of an `<a>`, it must be
    http(s) *after* resolution (so `javascript:` and `mailto:` keep their text
    and lose nothing else), each address is spelled out at most once, and the
    whole page gets `MAX_FETCH_LINKS` of them.
    """
    seen: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        href, inner = match.group(1), match.group(2)
        try:
            url = urllib.parse.urljoin(base_url, html.unescape(href.strip()))
        except ValueError:
            return inner
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return inner
        if len(url) > MAX_LINK_URL_CHARS or url in seen:
            return inner
        if len(seen) >= MAX_FETCH_LINKS:
            return inner
        seen.add(url)
        return f"{inner} ({url})"

    return _ANCHOR.sub(replace, raw)


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

    #: Injectable for offline tests. `(url, query) -> (status, body)`: the
    #: query is a parameter rather than baked into the url because it rides
    #: the form body now, and the status is returned because without it the
    #: tool cannot tell a block from a silence (ticket 26).
    def __init__(
        self, searcher: Callable[[str, str], tuple[int, str]] | None = None
    ) -> None:
        self._search = searcher or _search

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, SearchArgs)
        query = args.query.strip()
        if not query:
            return ToolResult.failure("Give a non-empty query.")
        # Before the round trip, not after it: the line exists to fill the
        # wait, and the longest wait is the request that ends in a timeout.
        # Nothing is reported for the empty-query refusal above, because
        # nothing is about to be slow.
        report_progress(f'Searching the web for "{query}"')
        try:
            status, page = self._search(SEARCH_URL, query)
        except Exception as exc:
            return ToolResult.failure(f"Search failed: {exc}")
        # Before the parser, deliberately. A challenge page parses to zero
        # results and is not a search that found nothing — it is a search that
        # never happened, and the agent has to be able to act on the
        # difference (it can retry, or say the web is unavailable, instead of
        # concluding the web is empty).
        if status != 200 or any(marker in page for marker in _CHALLENGE_MARKERS):
            return ToolResult.failure(
                f"The search endpoint refused this request (HTTP {status}) — it is "
                "rate-limiting or challenging automated searches, so the web could "
                "not be searched at all. This is not an empty result: do not "
                "conclude anything about what is on the web. Say the search is "
                "unavailable, or fetch a URL directly with web_fetch."
            )
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
        "Fetch one public web page and return its readable text (truncated), "
        "with each link written inline as `text (url)`. Use after "
        "web_search, when the user gives a URL, or to pick a link out of a "
        "page you were pointed at."
    )
    Args = FetchArgs

    def __init__(self, fetcher: Callable[[str], str] | None = None) -> None:
        self._fetch = fetcher or _get

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FetchArgs)
        url = args.url.strip()
        # The host, never the whole URL. This string is the one field of the
        # frame that crosses to a *customer's* surface as prose, and a full
        # URL there is both unreadable and the shape that carries a token in
        # its query string.
        host = urllib.parse.urlparse(url).hostname or url
        report_progress(f"Reading {host}")
        try:
            raw = self._fetch(url)
        except Exception as exc:
            return ToolResult.failure(f"Fetch failed: {exc}")
        # Links first, then the tags: `_strip_html` is shared with the search
        # parser, which strips *fragments* (a title, a snippet) where an
        # inlined URL would be noise. Only a whole fetched page gets this.
        text = _strip_html(_inline_links(raw, url))
        if not text:
            return ToolResult.failure("The page had no readable text.")
        suffix = " …(truncated)" if len(text) > MAX_FETCH_CHARS else ""
        return ToolResult(content=text[:MAX_FETCH_CHARS] + suffix)


WEB_TOOLS = [WebSearchTool(), WebFetchTool()]


# ## The link, and why it is inline (`workflow-gallery` 34)
#
# `_strip_html` deletes a tag *with its attributes*, which is right for a
# fragment and wrong for a page: the flagship gallery example fetched 8 013
# characters of a YouTube ranking and could not recover one `watch?v=` id,
# because every id lived in an `href`. A fetch that silently discards every
# URL in the document it just read is lying about what it fetched.
#
# **Inline, not appended.** A link index at the end of the text was the
# obvious alternative and is the wrong one twice over: `MAX_FETCH_CHARS`
# truncates the *tail*, so on exactly the long pages that carry a hundred
# links the index is the half that gets cut; and an index separates the URL
# from the row it belongs to, which is the association the model actually
# needs ("the id for *that* title").
#
# **Rejected: a `links=` argument.** It moves the decision to the model, and
# the model that needs this is the one that does not know to ask — example 16
# asked for a ranking, not for a link mode. It also widens a tool schema that
# `extra="forbid"` keeps deliberately small.
#
# **Rejected: returning structured JSON.** Every consumer of `web_fetch` is a
# prompt, and this is the tool every shipped example binds.
