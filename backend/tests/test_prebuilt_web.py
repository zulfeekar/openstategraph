"""Web tools: keyless search + SSRF-guarded fetch, offline-tested."""

from __future__ import annotations

import pytest

from openstategraph.prebuilt_web import WebFetchTool, WebSearchTool, _blocked_host

FAKE_RESULTS = '''
<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example <b>Title</b></a>
<a class="result__snippet">A useful snippet about the thing.</a>
'''


class TestSearch:
    def test_parses_titles_urls_and_snippets(self) -> None:
        tool = WebSearchTool(fetcher=lambda url: FAKE_RESULTS)
        result = tool.run(query="anything")
        assert result.error is None
        assert "Example Title" in result.content
        assert "https://example.com/page" in result.content
        assert "useful snippet" in result.content

    def test_no_results_is_a_readable_failure(self) -> None:
        tool = WebSearchTool(fetcher=lambda url: "<html></html>")
        assert tool.run(query="zzz").error is not None


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
