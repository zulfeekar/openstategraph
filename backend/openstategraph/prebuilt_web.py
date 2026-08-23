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
- ``web_search`` is now a ladder of backends (``search_backends.py``,
  `workflow-gallery` 67) rather than one hardcoded transport: DuckDuckGo's
  HTML endpoint (no key, no tracking params) is tried first, Tavily
  (``TAVILY_API_KEY``) second when DuckDuckGo reports a block; results are
  always titles + URLs + snippets, and the model follows up with
  ``web_fetch`` on what looks right.

## The search transport, and why it is not a plain GET (ticket 26)

The paragraphs below describe ``DuckDuckGoBackend``'s transport, which now
lives in ``search_backends.py`` — kept here because the *finding* is about
this endpoint, not about which file the code sits in.

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
import re
import urllib.parse
from typing import Callable

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.progress import report_progress
from openstategraph.search_backends import SearchBackendRegistry, default_search_registry
from openstategraph.web_transport import _request, _strip_html
# Re-exported by name, not just imported: `_blocked_host`, `_GuardedRedirects`,
# `_ssl_context` and `_validate_url` moved to `web_transport.py`
# (workflow-gallery 67), and `test_prebuilt_web.py`'s SSRF/redirect tests
# still import them from here. `as X` is the explicit re-export idiom so
# ruff's unused-import check does not flag what is deliberately public again
# under the old name.
from openstategraph.web_transport import _blocked_host as _blocked_host
from openstategraph.web_transport import _GuardedRedirects as _GuardedRedirects
from openstategraph.web_transport import _ssl_context as _ssl_context
from openstategraph.web_transport import _validate_url as _validate_url

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

#: `_ssl_context`, `_blocked_host`, `_GuardedRedirects`, `_validate_url`,
#: `_request` and `_strip_html` all moved to `web_transport.py`
#: (workflow-gallery 67) — the guarded transport is now shared *across*
#: families (this module's tools, and `search_backends`' ladder) rather than
#: owned by this one. Imported above and re-exported by name so existing
#: callers of `openstategraph.prebuilt_web._blocked_host` etc. keep working.


def _get(url: str) -> str:
    """A page's text. `web_fetch`'s transport, unchanged — an ordinary GET."""
    return _request(url)[1]


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


class SearchArgs(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(description="What to search the web for.")


class WebSearchTool(BaseTool):
    """Web search — a ladder of backends, not one (workflow-gallery 67).

    DuckDuckGo is the keyless default and is tried first; Tavily is the
    keyed second rung, tried only when DuckDuckGo's own rung reports a
    block. See `search_backends`' module docstring for why this is a
    separate `ISearchBackend` family rather than a bigger `ProviderSpec`.
    """

    name = "web_search"
    node_type = "tool.web-search"
    description = (
        "Search the web. Returns titles, URLs and snippets; follow up with "
        "web_fetch on the most promising URL. Use for anything current or "
        "outside your knowledge."
    )
    Args = SearchArgs

    #: Injectable for offline tests — a whole registry, not one transport,
    #: because the thing under test is now the ladder itself as much as any
    #: one backend's parsing.
    def __init__(self, registry: "SearchBackendRegistry | None" = None) -> None:
        self._registry = registry or default_search_registry()

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
        blocks: list[str] = []
        for backend in self._registry.list():
            try:
                outcome = backend.search(query, max_results=MAX_RESULTS)
            except Exception as exc:  # a backend that raised instead of returning data
                blocks.append(f"{backend.name}: {exc}")
                continue
            # Before anything else, deliberately. A blocked rung parses to
            # zero results and is not a search that found nothing — it is a
            # search that never happened, and the agent has to be able to
            # act on the difference (`ship-it` 26). A blocked rung falls
            # through to the next one instead of ending the search.
            if not outcome.ok:
                blocks.append(f"{backend.name}: {outcome.blocked_reason}")
                continue
            if not outcome.hits:
                return ToolResult.failure(f"No results for '{query}'.")
            results = [
                f"- **{hit.title}**\n  {hit.url}\n  {hit.snippet}" for hit in outcome.hits
            ]
            return ToolResult(content="\n".join(results))
        # Every rung refused — the case ship-it 26 taught this tool to spell
        # differently from "found nothing". Every backend's own reason is
        # named, because a search that never happened is not an empty
        # result and the agent must not conclude anything about the web.
        return ToolResult.failure(
            "The web could not be searched — every backend refused this request: "
            + "; ".join(blocks)
            + ". This is not an empty result: do not conclude anything about what "
            "is on the web. Say the search is unavailable, or fetch a URL directly "
            "with web_fetch."
        )


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
