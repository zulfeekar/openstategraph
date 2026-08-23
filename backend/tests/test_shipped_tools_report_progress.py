"""The `progress` frame gets producers that ship (production-ready 50).

`progress.py` opens by naming a tool that "spends forty seconds paging an API",
and until this file existed the only call site of `report_progress` in the
repository was that docstring's own example. The machinery was complete and the
silent gap was still there for every slow tool a person can drag out of the
palette.

**Which tools are honest places for it, and which are not.** The frame reaches
a client on `/api/runs/stream`, and `get_stream_writer()` only exists inside a
running graph. So the checkpoint has to sit on a code path that executes *while
a run is in flight*:

| named by the ticket | instrumented | why |
| --- | --- | --- |
| `tool.mcp` | yes | every call reopens a session — ~0.8 s before the server is even asked |
| Web Search / Web Fetch | yes | one network round trip per call, unbounded by us |
| YouTube Transcript | yes | a ladder of client fetches, then a caption fetch |
| Knowledge → *Build second brain* | **no** | it is not in a run at all |

The last row is the finding, not an omission. `run_build` is reached from
`openstategraph knowledge build` and from `POST /api/workflows/{slug}/knowledge`
— neither is a graph run, so `get_stream_writer()` raises and
`report_progress` returns `False` by design. Its live signal is a missing
*endpoint* concern (the request answers once, at the end), and pretending
otherwise by calling a no-op there would be worse than the silence: it would
read, from the source, as though the gap had been closed.

The tests run the real tools inside a real compiled `StateGraph`, because the
writer is ambient — a mock of `get_stream_writer` would assert against our own
double rather than against LangGraph.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.streaming import _stream_run  # noqa: E402
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402
from openstategraph.progress import Progress, progress_report  # noqa: E402


class _State(TypedDict):
    x: str


def _inside_a_run(body: Callable[[], Any]) -> list[Progress]:
    """Run `body` as a graph node and return whatever progress it reported."""
    from langgraph.graph import END, START, StateGraph

    def step(_state: _State) -> dict[str, str]:
        body()
        return {"x": "done"}

    graph = StateGraph(_State)
    graph.add_node("step", step)
    graph.add_edge(START, "step")
    graph.add_edge("step", END)

    reports = [
        progress_report(part["data"])
        for part in graph.compile().stream(
            {"x": ""}, stream_mode=["custom"], subgraphs=True, version="v2"
        )
        if part["type"] == "custom"
    ]
    return [report for report in reports if report is not None]


class TestWebFetch:
    def test_it_says_which_host_it_is_reading(self) -> None:
        from openstategraph.prebuilt_web import WebFetchTool

        tool = WebFetchTool(fetcher=lambda _url: "<p>hello</p>")
        messages = [
            r.message for r in _inside_a_run(lambda: tool.run(url="https://example.com/a/b"))
        ]

        # The host, not the whole URL: this line crosses to a customer's
        # surface intact, and a URL with a query string is both unreadable
        # there and the sort of thing that carries a token.
        assert messages == ["Reading example.com"]

    def test_a_bad_url_still_reports_before_it_fails(self) -> None:
        # The point of the line is the *wait*, so it is written before the
        # round trip rather than after it — a fetch that hangs and then fails
        # is exactly the case with the longest silence.
        from openstategraph.prebuilt_web import WebFetchTool

        def _boom(_url: str) -> str:
            raise TimeoutError("took too long")

        tool = WebFetchTool(fetcher=_boom)
        reports = _inside_a_run(lambda: tool.run(url="https://slow.example/x"))

        assert [r.message for r in reports] == ["Reading slow.example"]

    def test_outside_a_run_the_tool_is_unchanged(self) -> None:
        # CLAUDE.md's claim for a package's `tools/`: real code, importable
        # from a script and testable with pytest. A progress line must not
        # make that false.
        from openstategraph.prebuilt_web import WebFetchTool

        result = WebFetchTool(fetcher=lambda _url: "<p>hi</p>").run(url="https://example.com")

        assert result.ok and result.content == "hi"


class TestWebSearch:
    def _tool_with_one_blocked_backend(self) -> "object":
        # workflow-gallery 67: `web_search` is a ladder now, not one
        # transport — a single fake `ISearchBackend` that reports itself
        # blocked stands in for "the round trip happened and found nothing
        # usable", which is all this progress-line test needs.
        from openstategraph.prebuilt_web import WebSearchTool
        from openstategraph.search_backends import SearchBackendRegistry, SearchOutcome

        class _Blocked:
            name = "fake"

            def search(self, query: str, *, max_results: int) -> SearchOutcome:
                return SearchOutcome(blocked_reason="blocked")

        registry = SearchBackendRegistry()
        registry.register(_Blocked())
        return WebSearchTool(registry=registry)

    def test_it_says_what_it_is_searching_for(self) -> None:
        tool = self._tool_with_one_blocked_backend()
        messages = [r.message for r in _inside_a_run(lambda: tool.run(query="compiler design"))]

        assert messages == ['Searching the web for "compiler design"']

    def test_an_empty_query_reports_nothing(self) -> None:
        # Nothing is going to be slow, because nothing is going to happen.
        tool = self._tool_with_one_blocked_backend()

        assert _inside_a_run(lambda: tool.run(query="   ")) == []


class TestYouTubeTranscript:
    def test_it_names_the_video_it_is_reading(self) -> None:
        from openstategraph.prebuilt_youtube import YouTubeTranscriptTool

        tool = YouTubeTranscriptTool(transport=lambda *_a, **_k: (404, ""))
        messages = [
            r.message
            for r in _inside_a_run(
                lambda: tool.run(video="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            )
        ]

        assert messages == ["Reading captions for dQw4w9WgXcQ"]

    def test_an_unreadable_argument_reports_nothing(self) -> None:
        from openstategraph.prebuilt_youtube import YouTubeTranscriptTool

        tool = YouTubeTranscriptTool(transport=lambda *_a, **_k: (404, ""))

        assert _inside_a_run(lambda: tool.run(video="not a video")) == []


class TestMcp:
    """The slowest of the four, and the one whose own inspector says so."""

    @staticmethod
    def _fake_tool(name: str = "search_docs") -> Any:
        from pydantic import BaseModel

        class _Args(BaseModel):
            q: str = ""

        async def _coroutine(**_kwargs: Any) -> Any:
            return ("ok", None)

        return SimpleNamespace(
            name=name,
            description="",
            args_schema=_Args,
            coroutine=_coroutine,
            response_format="content_and_artifact",
            metadata=None,
        )

    def test_a_bound_tool_names_the_call_and_the_server(self) -> None:
        from openstategraph.prebuilt_mcp import _wrap_async_tool

        wrapped = _wrap_async_tool(self._fake_tool(), "langchain-docs")
        messages = [r.message for r in _inside_a_run(lambda: wrapped.func(q="agents"))]

        # Both halves matter: the server is what is being reconnected to, and
        # the tool name is what the agent chose to do.
        assert messages == ["Calling search_docs on langchain-docs"]

    def test_the_async_path_reports_too(self) -> None:
        # `StructuredTool` carries both a `func` and a `coroutine`, and an
        # async agent takes the second. Instrumenting only the sync shim would
        # have made this feature vanish under exactly the runtime that is
        # fastest to adopt.
        import asyncio

        from openstategraph.prebuilt_mcp import _wrap_async_tool

        wrapped = _wrap_async_tool(self._fake_tool("read_page"), "docs")
        messages = [
            r.message for r in _inside_a_run(lambda: asyncio.run(wrapped.coroutine(q="x")))
        ]

        assert messages == ["Calling read_page on docs"]

    def test_the_result_shape_is_untouched(self) -> None:
        from openstategraph.prebuilt_mcp import _wrap_async_tool

        wrapped = _wrap_async_tool(self._fake_tool(), "docs")

        # `content_and_artifact` is carried across deliberately — see the
        # wrapper's own docstring. A progress line must not cost that.
        assert wrapped.response_format == "content_and_artifact"
        assert wrapped.func(q="x") == ("ok", None)


class TestItReachesTheStreamDoor:
    """The end-to-end half the ticket asks for: a shipped tool → an SSE frame."""

    class _Graph:
        def __init__(self, chunks: list[Any]) -> None:
            self._chunks = chunks

        def stream(self, *_args: Any, **_kwargs: Any) -> Any:
            return iter(self._chunks)

        def get_state(self, _config: Any) -> Any:
            return SimpleNamespace(next=(), tasks=())

        def get_graph(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

    def test_a_web_fetch_becomes_a_progress_frame_on_the_wire(self) -> None:
        from openstategraph.prebuilt_web import WebFetchTool
        from openstategraph.progress import PROGRESS_KEY

        tool = WebFetchTool(fetcher=lambda _url: "<p>hi</p>")
        reports = _inside_a_run(lambda: tool.run(url="https://example.com/page"))
        assert reports, "the tool reported nothing, so there is nothing to stream"

        # The same payload the tool wrote, handed to the real stream assembler
        # rather than to a re-implementation of it.
        chunks = [
            {
                "type": "custom",
                "ns": (),
                "data": {PROGRESS_KEY: reports[0].model_dump()},
            }
        ]
        frames = list(
            _stream_run(
                self._Graph(chunks),
                {},
                {},
                SimpleNamespace(warnings=[]),
                {"step": "step"},
                SimpleNamespace(diagnostics=CompileDiagnostics()),
                "t1",
                Audience.CUSTOMER,
            )
        )
        progress = [
            json.loads(frame.split("\n")[1][len("data: ") :])
            for frame in frames
            if frame.startswith("event: progress")
        ]

        assert [p["message"] for p in progress] == ["Reading example.com"]

    def test_the_customer_sees_it_too(self) -> None:
        # Audience.CUSTOMER above, deliberately: the audience that cannot open
        # a trace is the one a silent gap is worst for.
        assert Audience.CUSTOMER is not Audience.DEVELOPER


class TestKnowledgeBuildIsNotOneOfThese:
    def test_a_build_is_not_a_run_so_the_line_would_be_a_no_op(self) -> None:
        # The recorded half of the table in this module's docstring. If
        # `run_build` ever grows a graph run around it, this fails and the
        # decision gets re-made rather than quietly inherited.
        from openstategraph.api import knowledge_build

        source = Path(knowledge_build.__file__).read_text(encoding="utf-8")

        assert "report_progress" not in source

    def test_report_progress_outside_a_run_is_still_false(self) -> None:
        from openstategraph.abc import report_progress

        assert report_progress("nobody is listening") is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
