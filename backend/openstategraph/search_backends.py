"""The search ladder: ``ISearchBackend`` -> ``AbstractSearchBackend`` ->
``BaseSearchBackend`` -> concrete vendors, held in a ``SearchBackendRegistry``.

## Why a second family, not a bigger `ProviderSpec` (workflow-gallery 67)

`ProviderSpec` (`providers.py`) is explicit that it is *data, not a class to
subclass* — everything a chat provider needs is a value `init_chat_model`
consumes, and none of it is behaviour. A search vendor is the opposite shape:
it needs a client — a request to build, a response to parse, a "was I
blocked" judgement to make — which is exactly what `ProviderSpec` refuses to
carry. And `CLAUDE.md`'s boundary rule is direct about it: sharing *within* a
family is a base class, sharing *across* families is composition. A chat
provider and a search backend are different families with nothing in common
but "reaches a vendor", so this is its own ladder, not an extension of the
one that already exists.

## `tool.web-search` had exactly one backend, and it is refusing

`html.duckduckgo.com/html/` answers every request — GET or the form POST this
module still uses — with HTTP 202 and an `anomaly.js` challenge page, as
measured 2026-08-21 and again while this ticket was worked. A keyless search
tool with one keyless backend was therefore a tool that returns nothing,
correctly reporting *why* (`ship-it` 26) but not doing what it is for.

**DuckDuckGo stays the keyless default** — the product must work with no
signup — and its whole job now is to *say so* when it is blocked rather than
read as an empty answer, exactly as `ship-it` 26 already made it do; nothing
about that half changes here, it is only moved into `DuckDuckGoBackend`.

**Tavily is the keyed second rung.** `TAVILY_API_KEY`, read by name from this
module (never ambient) exactly as `CLAUDE.md`'s Ollama correction requires —
"never restore a spec that reaches a vendor without naming a variable someone
can set, see and revoke." A plain HTTPS POST to `https://api.tavily.com/search`
via `web_transport._request`, which is `tavily-python`'s entire job for one
JSON call — `backend/pyproject.toml` defends its four-dependency floor with a
comment, and spending it on that would be wrong. Reusing `_request` also means
the SSRF guard, the redirect re-validation, the certifi context and the
timeout are declared exactly once, in `web_transport.py`, and this module never
duplicates them.

## Structured return, always — no output-format dropdown

A search result is a list of `{title, url, snippet}` and stays one, on every
backend and every call. `CLAUDE.md`: "If a port sometimes carries a scalar and
sometimes a list, its type changes at runtime and the executor must branch —
which is what typed ports exist to prevent." Config here may tune *volume*
(how many hits) because that does not change the shape; there is no format
picker and there should not be one — it would let a wired consumer of
`web_search` break silently the day someone flips it. `SearchHit` is the one
shape both backends produce.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from openstategraph.web_transport import FETCH_TIMEOUT, USER_AGENT, _request, _strip_html

#: `(url, *, data, user_agent, content_type, extra_headers) -> (status, body)`.
#: Injected by every concrete backend's constructor so tests never touch the
#: network — the same shape `web_transport._request` already has, so the
#: production default needs no adapter.
Requester = Callable[..., "tuple[int, str]"]

#: DuckDuckGo's HTML endpoint and the method its own form uses — moved here
#: unchanged from the old `prebuilt_web`, along with the User-Agent and challenge
#: markers, because they are `DuckDuckGoBackend`'s own transport now.
DUCKDUCKGO_SEARCH_URL = "https://html.duckduckgo.com/html/"
DUCKDUCKGO_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_CHALLENGE_MARKERS = ("confirm this search was made by a human", "anomaly.js")

#: Read by name, per `CLAUDE.md`'s Ollama correction — a vendor is reached
#: only through a variable someone can set, see and revoke. Never printed,
#: never logged; `TavilyBackend` reads it once per call and puts it in one
#: request header.
TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"


@dataclass(frozen=True)
class SearchHit:
    """One result. The only shape either backend produces — see the module
    docstring's "no output-format dropdown" section."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class SearchOutcome:
    """What one backend's `search()` returns.

    `blocked_reason` is the whole point of this ladder existing:
    `None` means the backend genuinely ran (`hits` may still be empty — that
    is a real "nothing found"), while a string means it was refused,
    rate-limited or unconfigured and the caller must not read the empty
    `hits` as an answer about the web. Exactly `ship-it` 26's distinction,
    generalised from one backend to every backend a ladder can hold.
    """

    hits: tuple[SearchHit, ...] = ()
    blocked_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.blocked_reason is None


@runtime_checkable
class ISearchBackend(Protocol):
    """The contract `WebSearchTool`'s ladder depends on.

    A `Protocol`, matching `ITool` and `INodeFamily`'s own reasoning: a
    backend assembled some other way satisfies this without inheriting from
    us.
    """

    name: str

    def search(self, query: str, *, max_results: int) -> SearchOutcome: ...


class AbstractSearchBackend(ABC):
    """Shared behaviour every backend needs: a timeout, a network-error guard,
    and normalising whatever a concrete backend parsed into `SearchOutcome`'s
    own rules (cap to `max_results`, drop hits with no URL).

    A concrete backend implements `_search_raw` only — it may raise, and may
    return more hits than asked for; both are handled once, here, rather than
    in every vendor's own parser.
    """

    #: Vendor id, e.g. `"duckduckgo"` — what `SearchBackendRegistry` keys on
    #: and what a combined refusal message names.
    name: str

    #: Per-request timeout, seconds. Shared rather than re-declared per
    #: backend, per `CLAUDE.md`'s anti-duplication rule for a family's shared
    #: concerns.
    timeout: int = FETCH_TIMEOUT

    def search(self, query: str, *, max_results: int) -> SearchOutcome:
        try:
            outcome = self._search_raw(query, max_results=max_results)
        except Exception as exc:  # network error, malformed response, etc.
            return SearchOutcome(blocked_reason=f"{self.name} search failed: {exc}")
        if outcome.blocked_reason is not None:
            return outcome
        hits = tuple(hit for hit in outcome.hits if hit.url)[:max_results]
        return SearchOutcome(hits=hits)

    @abstractmethod
    def _search_raw(self, query: str, *, max_results: int) -> SearchOutcome:
        """One vendor's actual request + parse. May raise; may over-return."""
        ...


class BaseSearchBackend(AbstractSearchBackend):
    """A usable default: an injectable `Requester`, so every concrete backend
    gets offline-testability for free instead of re-declaring it.

    The production default is `web_transport._request` — the one guarded
    transport (SSRF check, redirect re-validation, certifi context, timeout)
    every fetch and search in this package already shares.
    """

    def __init__(self, requester: Requester | None = None) -> None:
        self._requester = requester or _request


#: An `<a class="result__a" href="...">title</a>` possibly followed by a
#: `result__snippet` anchor. Unchanged from the tool this backend was moved
#: out of.
_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(?:.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>)?',
    re.S,
)


class DuckDuckGoBackend(BaseSearchBackend):
    """Keyless. A form POST to DuckDuckGo's own HTML endpoint — the request
    its own `<form>` makes, per `web_transport`'s docstring, moved from `prebuilt_web` (ticket 26).

    Its whole job, restated for this ladder: report a challenge as a
    challenge. `_search_raw` never lets a 202-with-`anomaly.js` reach the
    caller as "zero results" — it is `blocked_reason`, so `WebSearchTool`'s
    ladder falls to the next rung instead of concluding the web is empty.
    """

    name = "duckduckgo"

    def _search_raw(self, query: str, *, max_results: int) -> SearchOutcome:
        status, page = self._requester(
            DUCKDUCKGO_SEARCH_URL,
            data=urllib.parse.urlencode({"q": query}).encode(),
            user_agent=DUCKDUCKGO_USER_AGENT,
        )
        if status != 200 or any(marker in page for marker in _CHALLENGE_MARKERS):
            return SearchOutcome(
                blocked_reason=(
                    f"DuckDuckGo refused this request (HTTP {status}) — it is "
                    "rate-limiting or challenging automated searches."
                )
            )
        hits = []
        for match in _RESULT.finditer(page):
            href, title, snippet = match.groups()
            # DDG wraps targets in a redirect: uddg carries the real URL.
            target = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get(
                "uddg", [href]
            )[0]
            hits.append(SearchHit(title=_strip_html(title), url=target, snippet=_strip_html(snippet or "")[:200]))
            if len(hits) >= max_results:
                break
        return SearchOutcome(hits=tuple(hits))


class TavilyBackend(BaseSearchBackend):
    """Keyed. A plain HTTPS POST to `https://api.tavily.com/search` — no
    `tavily-python` dependency, per the module docstring.

    Request: `{"query": ..., "max_results": ...}`, `Authorization: Bearer
    <TAVILY_API_KEY>`. Response: `{"results": [{"title", "url", "content",
    ...}], ...}` — `content` is Tavily's field name for what this ladder
    calls a snippet. Schema confirmed against Tavily's own API reference
    (2026-08-23); it is a JSON POST, so the tolerant/strict rule applies the
    same as everywhere else that reads a service's answer: read the fields
    that are there, trust only the shape that is documented.
    """

    name = "tavily"

    def _search_raw(self, query: str, *, max_results: int) -> SearchOutcome:
        api_key = os.environ.get(TAVILY_API_KEY_ENV, "").strip()
        if not api_key:
            return SearchOutcome(
                blocked_reason=(
                    f"Tavily has no credential — set {TAVILY_API_KEY_ENV} in .env "
                    "(see .env.example)."
                )
            )
        payload = json.dumps({"query": query, "max_results": max_results}).encode()
        status, body = self._requester(
            TAVILY_SEARCH_URL,
            data=payload,
            user_agent=USER_AGENT,
            content_type="application/json",
            extra_headers={"Authorization": f"Bearer {api_key}"},
        )
        if status != 200:
            # Never the body verbatim: a 401's JSON can echo request framing
            # back, and the rule is the key is never printed, not "usually".
            return SearchOutcome(blocked_reason=f"Tavily refused this request (HTTP {status}).")
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return SearchOutcome(blocked_reason="Tavily returned an unreadable response.")
        raw_results = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(raw_results, list):
            return SearchOutcome(blocked_reason="Tavily's response had no results field.")
        hits = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title") or ""),
                    url=url,
                    snippet=str(item.get("content") or "")[:200],
                )
            )
        return SearchOutcome(hits=tuple(hits))


class SearchBackendRegistry:
    """The backends one `WebSearchTool` ladders through, in registration
    order.

    `CLAUDE.md`'s registry behaviour, the same shape as
    `compile.node_types.NodeTypeRegistry`: a duplicate id raises (two claims
    on one name is ambiguity, not precedence), `upsert` is how a caller says
    it meant to replace one, `list()` enumerates in the order a ladder should
    try them, and a fresh instance is always constructible so a test's
    registrations never leak into another test's.
    """

    def __init__(self) -> None:
        self._backends: dict[str, ISearchBackend] = {}

    def register(self, backend: ISearchBackend) -> None:
        if backend.name in self._backends:
            raise ValueError(
                f'Search backend "{backend.name}" is already registered. Two claims on '
                "one name is ambiguity, not precedence — use upsert() if you meant to "
                "replace it."
            )
        self._backends[backend.name] = backend

    def upsert(self, backend: ISearchBackend) -> None:
        self._backends[backend.name] = backend

    def get(self, name: str) -> ISearchBackend | None:
        return self._backends.get(name)

    def list(self) -> tuple[ISearchBackend, ...]:
        return tuple(self._backends.values())


def default_search_registry() -> SearchBackendRegistry:
    """DuckDuckGo first (keyless, the product's default), Tavily second (keyed,
    tried only when DuckDuckGo's rung is blocked or Tavily is asked for
    directly). A fresh registry per call — no module-level singleton, so a
    test that mutates one instance cannot affect another.
    """
    registry = SearchBackendRegistry()
    registry.register(DuckDuckGoBackend())
    registry.register(TavilyBackend())
    return registry
