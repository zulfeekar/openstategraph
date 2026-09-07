"""The search-backend ladder: `ISearchBackend` -> `AbstractSearchBackend` ->
`BaseSearchBackend` -> `DuckDuckGoBackend` / `TavilyBackend`, held in a
`SearchBackendRegistry` (workflow-gallery 67).

Every test here is offline — a fake `requester` stands in for the network,
exactly as `WebFetchTool`'s tests use a fake `fetcher`. The one live check
this ticket also requires (a real Tavily call, and DuckDuckGo's live block)
is done by hand during verification, not committed as a network-touching
test.
"""

from __future__ import annotations

import json

import pytest

from openstategraph.search_backends import (
    DuckDuckGoBackend,
    SearchBackendRegistry,
    SearchHit,
    SearchOutcome,
    TavilyBackend,
    default_search_registry,
)

FAKE_RESULTS = '''
<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example <b>Title</b></a>
<a class="result__snippet">A useful snippet about the thing.</a>
'''

#: Copied from a live response rather than imagined — see `prebuilt_web`'s
#: module docstring for why that matters.
CHALLENGE_PAGE = (
    '<!DOCTYPE html><html lang="en"><head><title>DuckDuckGo</title></head><body>'
    "<p>Unfortunately, bots use DuckDuckGo too. Please complete the following "
    "challenge to confirm this search was made by a human.</p>"
    "</body></html>"
)


class TestDuckDuckGoBackend:
    def test_parses_titles_urls_and_snippets(self) -> None:
        backend = DuckDuckGoBackend(requester=lambda url, **kw: (200, FAKE_RESULTS))
        outcome = backend.search("anything", max_results=6)
        assert outcome.ok
        assert outcome.hits == (
            SearchHit(
                title="Example Title",
                url="https://example.com/page",
                snippet="A useful snippet about the thing.",
            ),
        )

    def test_no_results_is_ok_with_no_hits(self) -> None:
        """Distinguishing this from a block only matters if a genuine
        zero-result page is still read as `ok` — ship-it 26's rule cuts both
        ways."""
        outcome = DuckDuckGoBackend(requester=lambda url, **kw: (200, "<html></html>")).search(
            "zzz", max_results=6
        )
        assert outcome.ok
        assert outcome.hits == ()

    def test_the_query_reaches_the_transport(self) -> None:
        seen: list[bytes | None] = []

        def requester(url: str, **kwargs: object) -> tuple[int, str]:
            seen.append(kwargs.get("data"))
            return 200, FAKE_RESULTS

        DuckDuckGoBackend(requester=requester).search("population of Tokyo", max_results=6)
        assert seen == [b"q=population+of+Tokyo"]

    @pytest.mark.parametrize("status", [202, 403, 429, 500])
    def test_any_non_200_is_blocked_not_empty(self, status: int) -> None:
        outcome = DuckDuckGoBackend(requester=lambda url, **kw: (status, "<html></html>")).search(
            "q", max_results=6
        )
        assert not outcome.ok
        assert outcome.hits == ()
        assert str(status) in outcome.blocked_reason  # type: ignore[arg-type]

    def test_a_challenge_served_with_200_is_still_blocked(self) -> None:
        """The status is the primary signal; the page saying so is the
        backstop for the day the block arrives with a 200."""
        outcome = DuckDuckGoBackend(requester=lambda url, **kw: (200, CHALLENGE_PAGE)).search(
            "q", max_results=6
        )
        assert not outcome.ok
        assert "block" in outcome.blocked_reason.lower() or "challeng" in outcome.blocked_reason.lower()  # type: ignore[union-attr]


class TestTavilyBackend:
    def _ok_response(self, results: list[dict]) -> tuple[int, str]:
        return 200, json.dumps({"results": results})

    def test_reports_blocked_when_no_key_is_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        outcome = TavilyBackend(requester=lambda url, **kw: (200, "{}")).search(
            "q", max_results=5
        )
        assert not outcome.ok
        assert "TAVILY_API_KEY" in outcome.blocked_reason  # type: ignore[operator]

    def test_reads_the_key_by_name_and_sends_it_as_a_bearer_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret-value")
        seen: dict[str, object] = {}

        def requester(url: str, **kwargs: object) -> tuple[int, str]:
            seen["url"] = url
            seen["headers"] = kwargs.get("extra_headers")
            seen["data"] = kwargs.get("data")
            return self._ok_response([])

        TavilyBackend(requester=requester).search("chinook revenue", max_results=5)
        assert seen["url"] == "https://api.tavily.com/search"
        assert seen["headers"] == {"Authorization": "Bearer tvly-secret-value"}
        body = json.loads(seen["data"])  # type: ignore[arg-type]
        assert body == {"query": "chinook revenue", "max_results": 5}

    def test_never_puts_the_key_anywhere_but_the_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-should-not-leak")
        captured: dict[str, object] = {}

        def requester(url: str, **kwargs: object) -> tuple[int, str]:
            captured.update(kwargs)
            return self._ok_response([])

        TavilyBackend(requester=requester).search("q", max_results=5)
        assert b"tvly-should-not-leak" not in captured.get("data", b"")  # type: ignore[arg-type]

    def test_parses_title_url_content_into_hits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        response = self._ok_response(
            [
                {"title": "Result One", "url": "https://a.example/1", "content": "first snippet", "score": 0.9},
                {"title": "Result Two", "url": "https://b.example/2", "content": "second snippet", "score": 0.5},
            ]
        )
        outcome = TavilyBackend(requester=lambda url, **kw: response).search("q", max_results=5)
        assert outcome.ok
        assert outcome.hits == (
            SearchHit(title="Result One", url="https://a.example/1", snippet="first snippet"),
            SearchHit(title="Result Two", url="https://b.example/2", snippet="second snippet"),
        )

    def test_a_non_200_status_is_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        outcome = TavilyBackend(requester=lambda url, **kw: (401, "{}")).search("q", max_results=5)
        assert not outcome.ok
        assert "401" in outcome.blocked_reason  # type: ignore[operator]

    def test_an_unparseable_body_is_blocked_not_a_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
        outcome = TavilyBackend(requester=lambda url, **kw: (200, "not json")).search(
            "q", max_results=5
        )
        assert not outcome.ok


class TestAbstractSearchBackendNormalising:
    def test_a_raised_transport_error_becomes_blocked_reason_not_a_crash(self) -> None:
        def boom(url: str, **kw: object) -> tuple[int, str]:
            raise OSError("no route to host")

        outcome = DuckDuckGoBackend(requester=boom).search("q", max_results=6)
        assert not outcome.ok
        assert "no route to host" in outcome.blocked_reason  # type: ignore[operator]

    def test_hits_are_capped_to_max_results(self) -> None:
        class Wide(DuckDuckGoBackend):
            def _search_raw(self, query: str, *, max_results: int) -> SearchOutcome:
                return SearchOutcome(
                    hits=tuple(SearchHit(title=str(i), url=f"https://x/{i}") for i in range(10))
                )

        outcome = Wide().search("q", max_results=3)
        assert len(outcome.hits) == 3

    def test_hits_with_no_url_are_dropped(self) -> None:
        class Sparse(DuckDuckGoBackend):
            def _search_raw(self, query: str, *, max_results: int) -> SearchOutcome:
                return SearchOutcome(hits=(SearchHit(title="no url", url=""),))

        assert Sparse().search("q", max_results=6).hits == ()


class TestSearchBackendRegistry:
    def test_a_fresh_registry_is_empty(self) -> None:
        assert SearchBackendRegistry().list() == ()

    def test_register_then_list_preserves_order(self) -> None:
        registry = SearchBackendRegistry()
        ddg, tavily = DuckDuckGoBackend(), TavilyBackend()
        registry.register(ddg)
        registry.register(tavily)
        assert registry.list() == (ddg, tavily)

    def test_a_duplicate_name_raises(self) -> None:
        registry = SearchBackendRegistry()
        registry.register(DuckDuckGoBackend())
        with pytest.raises(ValueError):
            registry.register(DuckDuckGoBackend())

    def test_upsert_replaces_without_raising(self) -> None:
        registry = SearchBackendRegistry()
        first = DuckDuckGoBackend()
        second = DuckDuckGoBackend()
        registry.register(first)
        registry.upsert(second)
        assert registry.get("duckduckgo") is second
        assert len(registry.list()) == 1

    def test_two_registries_do_not_share_state(self) -> None:
        a, b = SearchBackendRegistry(), SearchBackendRegistry()
        a.register(DuckDuckGoBackend())
        assert b.list() == ()

    def test_default_registry_is_duckduckgo_then_tavily(self) -> None:
        names = [backend.name for backend in default_search_registry().list()]
        assert names == ["duckduckgo", "tavily"]

    def test_default_registry_is_fresh_each_call(self) -> None:
        a, b = default_search_registry(), default_search_registry()
        a.upsert(TavilyBackend())  # no-op replace, just proves independence below
        assert a.get("tavily") is not b.get("tavily")
