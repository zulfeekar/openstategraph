"""Web tools: keyless search + SSRF-guarded fetch, offline-tested.

## Why the search half is shaped the way it is (ticket 26)

Web Search shipped returning nothing, on every query, while Web Fetch worked.
The tests here were green throughout, and that is the finding worth keeping:
they injected a hand-written SERP fragment, so they proved the *regex* and
never the request. DuckDuckGo had meanwhile started answering every plain GET
to `html.duckduckgo.com/html/` with **HTTP 202 and an anti-bot challenge
page** — real HTML, no `result__a` in it — which the parser read as "zero
results" and reported to the agent as `No results for '...'`.

Two defects, and the second is the one this project keeps closing: an empty
result presented as an answer. So the double is now a `(status, body)` pair
rather than a bare string, and a search whose *transport* failed says so in
different words from one that genuinely found nothing.
"""

from __future__ import annotations

import pytest

from openstategraph.prebuilt_web import WebFetchTool, WebSearchTool, _blocked_host

FAKE_RESULTS = '''
<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example <b>Title</b></a>
<a class="result__snippet">A useful snippet about the thing.</a>
'''

#: What the endpoint actually returned, trimmed: a 202 with a duck-selection
#: CAPTCHA where the results should be. Copied from a live response rather
#: than imagined, because imagining it is how the bug survived.
CHALLENGE_PAGE = (
    '<!DOCTYPE html><html lang="en"><head><title>DuckDuckGo</title></head><body>'
    "<p>Unfortunately, bots use DuckDuckGo too. Please complete the following "
    "challenge to confirm this search was made by a human.</p>"
    "</body></html>"
)


class TestSearch:
    def test_parses_titles_urls_and_snippets(self) -> None:
        tool = WebSearchTool(searcher=lambda url, query: (200, FAKE_RESULTS))
        result = tool.run(query="anything")
        assert result.error is None
        assert "Example Title" in result.content
        assert "https://example.com/page" in result.content
        assert "useful snippet" in result.content

    def test_no_results_is_a_readable_failure(self) -> None:
        tool = WebSearchTool(searcher=lambda url, query: (200, "<html></html>"))
        assert tool.run(query="zzz").error is not None

    def test_the_query_reaches_the_transport(self) -> None:
        """It rides the form body now, not the URL — so it must be passed on.

        The endpoint serves the challenge to GETs and answers its own form's
        POST; a search that quietly stopped sending the query would look
        exactly like the bug being fixed.
        """
        seen: list[tuple[str, str]] = []

        def searcher(url: str, query: str) -> tuple[int, str]:
            seen.append((url, query))
            return 200, FAKE_RESULTS

        WebSearchTool(searcher=searcher).run(query="population of Tokyo")
        assert seen == [("https://html.duckduckgo.com/html/", "population of Tokyo")]


class TestABlockIsNotAnEmptyResult:
    """The ticket's real defect: a refusal reported as an answer.

    An agent told `No results for 'population of Tokyo'` concludes the web has
    nothing to say and moves on — which is what the shipped Web Researcher
    did, honestly and wrongly. A blocked search must read as broken, because
    it is.
    """

    def _blocked(self, status: int, body: str = CHALLENGE_PAGE) -> str:
        result = WebSearchTool(searcher=lambda url, query: (status, body)).run(
            query="population of Tokyo"
        )
        assert result.error is not None
        return result.error

    def test_a_202_challenge_does_not_read_as_no_results(self) -> None:
        error = self._blocked(202)
        assert "No results" not in error

    def test_it_names_the_status_so_the_failure_is_diagnosable(self) -> None:
        assert "202" in self._blocked(202)

    @pytest.mark.parametrize("status", [403, 429, 500])
    def test_any_non_200_is_a_refusal_not_a_silence(self, status: int) -> None:
        assert "No results" not in self._blocked(status, "<html></html>")

    def test_a_genuine_200_with_nothing_in_it_still_says_no_results(self) -> None:
        """The distinction has to cut both ways to be worth anything."""
        result = WebSearchTool(searcher=lambda url, query: (200, "<html></html>")).run(
            query="zzz"
        )
        assert result.error is not None and "No results" in result.error

    def test_a_challenge_served_with_a_200_is_still_a_block(self) -> None:
        """Status is the primary signal; the page saying so is the backstop.

        The endpoint has changed shape repeatedly, and a 200-with-a-challenge
        is the next shape it can take without warning.
        """
        error = self._blocked(200)
        assert "No results" not in error


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
