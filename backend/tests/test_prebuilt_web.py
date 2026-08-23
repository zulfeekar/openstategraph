"""Web tools: search ladder + SSRF-guarded fetch, offline-tested.

## Why the search half is shaped the way it is (ticket 26, then workflow-gallery 67)

Web Search shipped returning nothing, on every query, while Web Fetch worked.
The tests here were green throughout, and that is the finding worth keeping:
they injected a hand-written SERP fragment, so they proved the *regex* and
never the request. DuckDuckGo had meanwhile started answering every plain GET
to `html.duckduckgo.com/html/` with **HTTP 202 and an anti-bot challenge
page** — real HTML, no `result__a` in it — which the parser read as "zero
results" and reported to the agent as `No results for '...'`.

Two defects, and the second is the one this project keeps closing: an empty
result presented as an answer. Ticket 26 fixed that for one backend. It
turned out to be structural, not incidental — the endpoint still refuses
every request, six days later and again today — so `tool.web-search` is now
a *ladder* of backends (`search_backends.py`) rather than one hardcoded
transport, and this file's job narrows to what belongs at this layer: does
`WebSearchTool` fall through a blocked rung to the next one, and does it
still fail loudly when every rung refuses? The DuckDuckGo- and
Tavily-specific parsing/blocking behaviour now belongs to
`test_search_backends.py`, one layer down, so neither test proves the other.
"""

from __future__ import annotations

import pytest

from openstategraph.prebuilt_web import WebFetchTool, WebSearchTool, _blocked_host
from openstategraph.search_backends import SearchBackendRegistry, SearchHit, SearchOutcome


class _FakeBackend:
    """A minimal `ISearchBackend` — no inheritance needed, per the Protocol's
    own reasoning (`search_backends.ISearchBackend`'s docstring)."""

    def __init__(self, name: str, outcome: SearchOutcome) -> None:
        self.name = name
        self._outcome = outcome
        self.calls: list[str] = []

    def search(self, query: str, *, max_results: int) -> SearchOutcome:
        self.calls.append(query)
        return self._outcome


def _registry(*backends: _FakeBackend) -> SearchBackendRegistry:
    registry = SearchBackendRegistry()
    for backend in backends:
        registry.register(backend)
    return registry


class TestSearchLadder:
    """The orchestration `WebSearchTool` now owns: which rung answers, and
    what happens when one, or all, refuse."""

    def test_the_first_backends_hits_are_returned(self) -> None:
        hit = SearchHit(title="Example Title", url="https://example.com/page", snippet="A snippet")
        first = _FakeBackend("first", SearchOutcome(hits=(hit,)))
        tool = WebSearchTool(registry=_registry(first))
        result = tool.run(query="anything")
        assert result.error is None
        assert "Example Title" in result.content
        assert "https://example.com/page" in result.content
        assert "A snippet" in result.content

    def test_a_blocked_first_rung_falls_through_to_the_second(self) -> None:
        hit = SearchHit(title="From Tavily", url="https://example.com/x")
        blocked = _FakeBackend("duckduckgo", SearchOutcome(blocked_reason="blocked (HTTP 202)"))
        works = _FakeBackend("tavily", SearchOutcome(hits=(hit,)))
        result = WebSearchTool(registry=_registry(blocked, works)).run(query="q")
        assert result.error is None
        assert "From Tavily" in result.content
        assert blocked.calls == ["q"] and works.calls == ["q"]

    def test_a_successful_rung_with_no_hits_is_a_readable_failure_and_stops_the_ladder(self) -> None:
        """A backend that genuinely ran and found nothing is a real answer —
        `ship-it` 26's distinction cuts both ways, so this is `No results`,
        not a fall-through to the next rung."""
        ran_but_empty = _FakeBackend("first", SearchOutcome(hits=()))
        never_called = _FakeBackend("second", SearchOutcome(hits=(SearchHit(title="t", url="https://x"),)))
        result = WebSearchTool(registry=_registry(ran_but_empty, never_called)).run(query="zzz")
        assert result.error is not None and "No results" in result.error
        assert never_called.calls == []

    def test_every_backend_refusing_is_a_refusal_not_a_silence(self) -> None:
        """The ticket's real defect, generalised: a refusal reported as an
        answer. An agent told `No results for 'q'` concludes the web has
        nothing to say and moves on — a blocked search must read as broken,
        because it is, on every rung."""
        a = _FakeBackend("duckduckgo", SearchOutcome(blocked_reason="blocked (HTTP 202)"))
        b = _FakeBackend("tavily", SearchOutcome(blocked_reason="no credential"))
        result = WebSearchTool(registry=_registry(a, b)).run(query="q")
        assert result.error is not None
        assert "No results" not in result.error
        assert "duckduckgo" in result.error and "blocked (HTTP 202)" in result.error
        assert "tavily" in result.error and "no credential" in result.error

    def test_a_backend_that_raises_is_treated_as_a_refusal_not_a_crash(self) -> None:
        class Boom:
            name = "boom"

            def search(self, query: str, *, max_results: int) -> SearchOutcome:
                raise RuntimeError("kaboom")

        result = WebSearchTool(registry=_registry(Boom())).run(query="q")
        assert result.error is not None
        assert "kaboom" in result.error


class TestFetch:
    def test_strips_html_to_readable_text(self) -> None:
        tool = WebFetchTool(fetcher=lambda url: "<html><script>x()</script><p>Hello <b>world</b></p></html>")
        result = tool.run(url="https://example.com")
        assert result.error is None
        assert result.content == "Hello world"

    def test_network_errors_are_data(self) -> None:
        def boom(url): raise ValueError("nope")
        assert WebFetchTool(fetcher=boom).run(url="https://example.com").error is not None


class TestSsrfGuard:
    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.0.0.8", "169.254.1.1"])
    def test_private_and_loopback_hosts_are_blocked(self, host: str) -> None:
        assert _blocked_host(host) is True

    def test_the_real_fetcher_refuses_non_http_schemes(self) -> None:
        from openstategraph.prebuilt_web import _get
        with pytest.raises(ValueError):
            _get("file:///etc/passwd")


class TestRedirectGuard:
    def test_a_redirect_to_an_internal_host_is_refused(self) -> None:
        from openstategraph.prebuilt_web import _GuardedRedirects
        with pytest.raises(ValueError):
            _GuardedRedirects().redirect_request(
                None, None, 302, "Found", {}, "http://127.0.0.1/latest/meta-data")
