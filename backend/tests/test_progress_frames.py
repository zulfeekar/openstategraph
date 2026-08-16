"""A slow tool is a silent gap, and `custom` is the mode that closes it (22).

Nothing in this backend used the `custom` stream mode or `get_stream_writer()`.
The consequence is a sentence `docs/api.md` already has to spend a paragraph
on: an `update` frame fires when a node *completes*, so between two of them
the only thing arriving is model tokens — and a tool that spends forty seconds
paging an API produces none of those either. The run looks stopped.

`custom` is the documented channel for a step to say something about itself
while it works, and it is also the escape hatch for any model that is not a
LangChain chat model.

**Why this frame has a Pydantic model when the other six do not.** Every other
frame is assembled here from values this process produced — LangGraph's own
chunks, the compiler's maps, our resolvers. `custom` carries *whatever a tool
wrote*, which is arbitrary third-party code, and it is a shared channel:
deepagents and any middleware may write to it too. So this is the one frame
with a genuine validating boundary to defend, which is what `Progress` is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.streaming import PROGRESS_EVENTS, RUN_EVENTS, _stream_run  # noqa: E402
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402
from openstategraph.progress import (  # noqa: E402
    PROGRESS_KEY,
    Progress,
    progress_report,
    report_progress,
)

KNOWN = {"agent_sql": "agent-sql", "in1": "in1"}


class _Graph:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks
        self.stream_kwargs: dict[str, Any] = {}

    def stream(self, *_args: Any, **kwargs: Any) -> Any:
        self.stream_kwargs = kwargs
        return iter(self._chunks)

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(
    chunks: list[Any], audience: Audience = Audience.DEVELOPER
) -> tuple[list[tuple[str, Any]], _Graph]:
    graph = _Graph(chunks)
    runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
    out: list[tuple[str, Any]] = []
    for frame in _stream_run(
        graph, {}, {}, SimpleNamespace(warnings=[]), KNOWN, runtime, "t1", audience
    ):
        name = frame.split("\n")[0][len("event: ") :]
        out.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return out, graph


def _custom(value: Any, ns: tuple[str, ...] = ()) -> Any:
    return {"type": "custom", "ns": ns, "data": value}


class TestTheVocabularyGrewByOne:
    def test_progress_is_a_run_event(self) -> None:
        assert "progress" in RUN_EVENTS

    def test_it_is_progress_rather_than_terminal(self) -> None:
        # The guarantee a client depends on: after any of these, keep waiting.
        # A progress frame that landed in TERMINAL_EVENTS would end streams.
        assert "progress" in PROGRESS_EVENTS


class TestTheModeIsRequested:
    def test_custom_joins_the_stream_modes(self) -> None:
        _, graph = _frames([])

        assert "custom" in graph.stream_kwargs["stream_mode"]

    def test_the_modes_we_already_had_are_still_there(self) -> None:
        _, graph = _frames([])

        assert set(graph.stream_kwargs["stream_mode"]) >= {"updates", "messages"}


class TestWritingProgress:
    def test_a_report_becomes_a_frame(self) -> None:
        events, _ = _frames(
            [_custom({PROGRESS_KEY: Progress(message="Read 40 of 100", node="agent_sql").model_dump()})]
        )
        name, data = next((n, d) for n, d in events if n == "progress")

        assert name == "progress"
        assert data["message"] == "Read 40 of 100"
        assert data["node"] == "agent-sql"

    def test_counts_ride_along_when_given(self) -> None:
        events, _ = _frames(
            [
                _custom(
                    {
                        PROGRESS_KEY: Progress(
                            message="Paging", current=40, total=100, node="agent_sql"
                        ).model_dump()
                    }
                )
            ]
        )
        data = next(d for n, d in events if n == "progress")

        assert (data["current"], data["total"]) == (40, 100)

    def test_counts_are_null_rather_than_invented(self) -> None:
        # `int | None`, never a sentinel and never a non-finite float —
        # CLAUDE.md's rule about what may live in a serialisable field.
        events, _ = _frames([_custom({PROGRESS_KEY: Progress(message="Working").model_dump()})])
        data = next(d for n, d in events if n == "progress")

        assert data["current"] is None
        assert data["total"] is None

    def test_a_frame_says_where_the_run_is(self) -> None:
        # The same three fields every mid-node frame carries, for the same
        # reason `token` carries them: this is a frame that arrives while a
        # node is STILL WORKING, which is the only kind that can move a
        # highlight at the start of a step rather than the end.
        events, _ = _frames(
            [_custom({PROGRESS_KEY: Progress(message="x", node="agent_sql").model_dump()})]
        )
        data = next(d for n, d in events if n == "progress")

        assert data["activeNode"] == "agent-sql"
        assert data["path"] == ["agent-sql"]
        assert data["pathSlugs"] == [""]


class TestTheChannelIsShared:
    """`custom` is not ours, so a stranger's data must not become a user's line.

    Requesting the mode means we now receive everything anyone writes to it —
    deepagents, a middleware, a library we have not met. Turning one of those
    dicts into a visible progress line is exactly the leak this codebase keeps
    closing (a tool's payload in the answer area, a branch name in a
    customer's prose). A step that wants to be seen calls `report_progress`.
    """

    def test_someone_elses_custom_data_produces_no_frame(self) -> None:
        events, _ = _frames([_custom({"deepagents": {"todo": "…"}}), _custom("a bare string")])

        assert [n for n, _ in events] == ["done"]

    def test_a_malformed_report_is_skipped_rather_than_fatal(self) -> None:
        # A tool is third-party code; a bad payload costs its own frame and
        # not the run. The stream's one job is to always reach a terminal.
        events, _ = _frames(
            [
                _custom({PROGRESS_KEY: {"current": "lots"}}),
                _custom({PROGRESS_KEY: Progress(message="fine").model_dump()}),
            ]
        )

        assert [n for n, _ in events] == ["progress", "done"]

    def test_reading_a_report_off_a_payload_is_total(self) -> None:
        assert progress_report({PROGRESS_KEY: {"message": "hi"}}).message == "hi"
        assert progress_report({"other": 1}) is None
        assert progress_report("string") is None
        assert progress_report(None) is None
        assert progress_report({PROGRESS_KEY: "not a mapping"}) is None


class TestATooldWritesItWithoutKnowingAnyOfThis:
    def test_report_progress_outside_a_run_is_a_no_op(self) -> None:
        """The property that keeps a package's `tests/` real.

        `get_stream_writer()` raises `RuntimeError: Called get_config outside
        of a runnable context` when there is no run around it — and CLAUDE.md's
        whole claim for `tools/` and `tests/` being real code is that a tool is
        importable from a script and testable with pytest. A progress line that
        detonates a unit test would make that false.
        """
        assert report_progress("nobody is listening") is False

    def test_it_reaches_the_writer_inside_a_real_graph(self) -> None:
        from typing import TypedDict

        from langgraph.graph import END, START, StateGraph

        class _State(TypedDict):
            x: str

        def slow(_state: _State) -> dict[str, str]:
            assert report_progress("Read 40 of 100", current=40, total=100) is True
            return {"x": "done"}

        graph = StateGraph(_State)
        graph.add_node("slow", slow)
        graph.add_edge(START, "slow")
        graph.add_edge("slow", END)

        reports = [
            progress_report(part["data"])
            for part in graph.compile().stream(
                {"x": ""}, stream_mode=["custom"], subgraphs=True, version="v2"
            )
            if part["type"] == "custom"
        ]

        assert [r.message for r in reports if r] == ["Read 40 of 100"]
        # Stamped by us, not by the author: the writer is ambient, so a tool
        # cannot name its own node and should not have to.
        assert [r.node for r in reports if r] == ["slow"]

    def test_the_authoring_import_is_the_blessed_one(self) -> None:
        # A tool author is told `from openstategraph.abc import BaseTool, …`.
        # A second import path for the one thing a tool does *while* running
        # would be a surface nobody finds.
        from openstategraph.abc import Progress as ExportedProgress
        from openstategraph.abc import report_progress as exported

        assert exported is report_progress
        assert ExportedProgress is Progress
