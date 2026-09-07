"""`launch-readiness/143`: the finding, followed all the way to a customer.

**Why this file exists separately from `test_tool_findings.py`.** That file
proves the sentence is safe where it is composed. This one proves it is still
safe where it is *read* — through `NarrationMiddleware`, onto the `custom`
channel, through `api/streaming.py`'s fold with `Audience.CUSTOMER`, and out
as the `progress` SSE frame a customer chat renders.

`launch-readiness/112` is the reason the distinction is not pedantry. Its two
leaks — an internal URL and an `/offload/` path — were both caught *in a
browser*, by a person reading a customer chat, while the unit tests for the
composing function were green. Both were composed correctly and read
somewhere nobody had looked.

A result summary is a far richer leak surface than a call summary: the
payloads below carry warehouse table names, an ODBC driver message, a request
id, a user's own search term and a model-directed instruction. Nothing here
mocks the fold — `_stream_run` is the real one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ScriptedGraph, drive_fold  # noqa: E402

from openstategraph.abc.narration import build_narration_middleware  # noqa: E402
from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.streaming import _stream_run  # noqa: E402
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402
from tests.test_tool_findings import (  # noqa: E402
    CANONICAL_MISS,
    EXECUTE_SQL,
    EXECUTE_SQL_FAILED,
    GREP_COUNT,
    INTERNALS,
    LIST_LENSES,
    LS,
    READ_MISSING,
    READ_OFFLOADED,
    READ_SHORT,
    SEARCH_TABLES,
    SKILL_GREP,
    WRITE_OK,
)

KNOWN = {"agent1": "agent-1", "in1": "in1"}


class _State(TypedDict, total=False):
    step: int


class _Graph:
    """Replays the `custom` chunks a real run would have produced."""

    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        return iter(self._chunks)

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _narrate(tool_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything the shipped `"narration"` slot puts on the wire for one call.

    The *shipped* one — `build_narration_middleware()`, the single place both
    tables are wired in — rather than a hand-built middleware, so this cannot
    pass while the thing agents actually run behaves differently.
    """
    middleware = build_narration_middleware()
    request = ToolCallRequest(
        tool_call={"name": tool_name, "args": {"term": "Persian Gulf"}, "id": "call_abc123"},
        tool=None,
        state={},
        runtime=None,
    )
    result = ToolMessage(content=json.dumps(payload), tool_call_id="call_abc123")

    def handler(_req: ToolCallRequest) -> ToolMessage:
        return result

    def node(state: _State, runtime=None):
        middleware.wrap_tool_call(request, handler)
        return {"step": 1}

    graph = (
        StateGraph(_State)
        .add_node("agent1", node)
        .add_edge(START, "agent1")
        .add_edge("agent1", END)
        .compile()
    )
    return list(graph.stream({"step": 0}, stream_mode="custom"))


def _customer_frames(chunks: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    """The chunks, folded for a customer, as `(event, data)` — the real fold."""
    runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
    out: list[tuple[str, Any]] = []
    replay = [{"type": "custom", "ns": (), "data": chunk} for chunk in chunks]
    for frame in drive_fold(
        _stream_run(
            ScriptedGraph(_Graph(replay)),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            runtime,
            "t1",
            Audience.CUSTOMER,
        )
    ):
        name = frame.split("\n")[0][len("event: ") :]
        out.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return out


def _narrate_text(tool_name: str, content: str) -> list[dict[str, Any]]:
    """`_narrate`, for a tool whose result is prose rather than an envelope.

    `launch-readiness/144`. The deep-agent harness's own file tools answer
    with plain text carrying a path — `"Updated file /new.txt"`, a listing
    that is nothing *but* paths — so they need following to the customer for
    the same reason `143`'s findings did: `112`'s two leaks were both composed
    correctly and caught in a browser.
    """
    middleware = build_narration_middleware()
    request = ToolCallRequest(
        tool_call={
            "name": tool_name,
            "args": {"file_path": "/offload/mcp_list_lenses/call_eeR8/3LoOli2.txt"},
            "id": "call_abc123",
        },
        tool=None,
        state={},
        runtime=None,
    )
    result = ToolMessage(content=content, tool_call_id="call_abc123")

    def handler(_req: ToolCallRequest) -> ToolMessage:
        return result

    def node(state: _State, runtime=None):
        middleware.wrap_tool_call(request, handler)
        return {"step": 1}

    graph = (
        StateGraph(_State)
        .add_node("agent1", node)
        .add_edge(START, "agent1")
        .add_edge("agent1", END)
        .compile()
    )
    return list(graph.stream({"step": 0}, stream_mode="custom"))


def _customer_lines_for_text(tool_name: str, content: str) -> list[str]:
    return [
        data["message"]
        for event, data in _customer_frames(_narrate_text(tool_name, content))
        if event == "progress"
    ]


def _customer_lines(tool_name: str, payload: dict[str, Any]) -> list[str]:
    return [
        data["message"]
        for event, data in _customer_frames(_narrate(tool_name, payload))
        if event == "progress"
    ]


CASES = (
    ("mcp_list_lenses", LIST_LENSES),
    ("mcp_execute_sql", EXECUTE_SQL),
    ("mcp_execute_sql", EXECUTE_SQL_FAILED),
    ("mcp_search_tables", SEARCH_TABLES),
    ("mcp_skill_grep", SKILL_GREP),
    ("mcp_lookup_canonical_value", CANONICAL_MISS),
)


class TestTheFindingActuallyArrives:
    def test_a_customer_sees_what_the_query_found(self) -> None:
        assert _customer_lines("mcp_execute_sql", EXECUTE_SQL)[-1] == (
            "Found 68 rows across 2 columns."
        )

    def test_a_failure_is_no_longer_indistinguishable_from_silence(self) -> None:
        assert _customer_lines("mcp_execute_sql", EXECUTE_SQL_FAILED)[-1] == "That did not work."

    def test_every_call_now_carries_an_account_of_itself(self) -> None:
        # Before this ticket the after-line was `None` for every one of these:
        # the finding is derived from a JSON *string*, and the shape floor
        # could only read a Python list.
        for name, payload in CASES:
            assert len(_customer_lines(name, payload)) == 2, name


class TestNothingInternalCrossesToACustomer:
    def test_no_internal_from_any_payload_appears_in_the_finding(self) -> None:
        # The *finding* — the line this ticket adds, and the one composed from
        # a payload. The before-line beside it is `launch-readiness/112`'s and
        # deliberately shows the user's own search term, which is a value they
        # typed rather than an internal; its own safety is pinned in
        # `test_tool_sentences.py`.
        for name, payload in CASES:
            finding = _customer_lines(name, payload)[-1]
            for internal in INTERNALS:
                assert internal.lower() not in finding.lower(), (name, internal, finding)

    def test_not_even_the_users_own_term_is_repeated_back_from_a_result(self) -> None:
        # A result *echoes* the term (`"user_term": "Persian Gulf"`). The
        # before-line may show it because the user typed it; a finding read
        # off a payload must not, because by then it is a value a server chose
        # to put in a field and the distinction has been lost.
        assert (
            "Persian Gulf" not in _customer_lines("mcp_lookup_canonical_value", CANONICAL_MISS)[-1]
        )

    def test_the_drivers_error_text_never_reaches_the_chat(self) -> None:
        line = " ".join(_customer_lines("mcp_execute_sql", EXECUTE_SQL_FAILED)).lower()
        for fragment in ("odbc", "sqlexecdirectw", "incorrect syntax", "internal_error", "42000"):
            assert fragment not in line

    def test_the_two_leaks_112_caught_live_cannot_recur_through_a_result(self) -> None:
        # A server that puts a URL and an offload path in its result values.
        hostile = {
            "ok": True,
            "data": {
                "lenses": [
                    {"lens_id": "http://localhost:8080/mcp/"},
                    {"lens_id": "/offload/mcp_list_lenses/call_eeR8/3LoOli2BeA5Cqk4p6ik.txt"},
                ]
            },
        }
        for line in _customer_lines("mcp_list_lenses", hostile):
            assert "http" not in line
            assert "/offload/" not in line
        assert _customer_lines("mcp_list_lenses", hostile)[1] == "Found 2 views of the data."

    def test_the_line_a_customer_sees_is_the_line_a_developer_sees(self) -> None:
        # Not an assumption worth leaving implicit: `progress.message` crosses
        # audiences intact by design (`api/streaming.py`), which is exactly
        # why the safety has to be in the composition rather than in a filter.
        chunks = _narrate("mcp_execute_sql", EXECUTE_SQL)
        runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
        replay = [{"type": "custom", "ns": (), "data": c} for c in chunks]
        developer = [
            json.loads(f.split("\n")[1][len("data: ") :])["message"]
            for f in drive_fold(
                _stream_run(
                    ScriptedGraph(_Graph(replay)),
                    {},
                    {},
                    SimpleNamespace(warnings=[]),
                    KNOWN,
                    runtime,
                    "t1",
                    Audience.DEVELOPER,
                )
            )
            if f.startswith("event: progress")
        ]
        assert developer == _customer_lines("mcp_execute_sql", EXECUTE_SQL)


HARNESS_CASES = (
    ("read_file", READ_SHORT),
    ("read_file", READ_OFFLOADED),
    ("read_file", READ_MISSING),
    ("ls", LS),
    ("grep", GREP_COUNT),
    ("write_file", WRITE_OK),
)


class TestTheHarnessFileToolsReachTheCustomerToo:
    """`launch-readiness/144`, followed to the same place `143` was.

    These are the most frequent lines on a deep-tier run, and every one of
    their results is *made of paths*. `144`'s scope note is that a path is not
    automatically safe to speak; this is where that stops being a claim.
    """

    def test_a_customer_sees_what_the_read_found(self) -> None:
        assert _customer_lines_for_text("read_file", READ_SHORT)[-1] == "Read 3 lines."

    def test_a_failed_read_is_no_longer_indistinguishable_from_silence(self) -> None:
        assert _customer_lines_for_text("read_file", READ_MISSING)[-1] == "That did not work."

    def test_every_harness_call_now_carries_an_account_of_itself(self) -> None:
        # Two lines: what it is doing, then what it found. Before `144` the
        # second one did not exist for any of these.
        for name, content in HARNESS_CASES:
            assert len(_customer_lines_for_text(name, content)) == 2, name

    def test_no_path_reaches_the_customer_from_either_line(self) -> None:
        # The argument is an `/offload/` path on every one of these calls —
        # the exact string `launch-readiness/112` caught in a customer chat.
        # Neither the before-line (which declares no argument for these tools)
        # nor the finding may show it.
        for name, content in HARNESS_CASES:
            for line in _customer_lines_for_text(name, content):
                assert "/offload/" not in line, (name, line)
                assert ".txt" not in line, (name, line)
                assert "3LoOli2" not in line, (name, line)

    def test_a_files_own_contents_never_reach_the_customer(self) -> None:
        secret = "1  api_key = sk-not-a-real-key\n2  password = hunter2"
        for line in _customer_lines_for_text("read_file", secret):
            assert "sk-" not in line
            assert "hunter2" not in line


def _developer_frames(chunks: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    """The same chunks, folded for a developer. Same fold, one argument apart."""
    runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
    out: list[tuple[str, Any]] = []
    replay = [{"type": "custom", "ns": (), "data": chunk} for chunk in chunks]
    for frame in drive_fold(
        _stream_run(
            ScriptedGraph(_Graph(replay)),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            runtime,
            "t1",
            Audience.DEVELOPER,
        )
    ):
        name = frame.split("\n")[0][len("event: ") :]
        out.append((name, json.loads(frame.split("\n")[1][len("data: ") :])))
    return out


def _developer_progress(tool_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        data for event, data in _developer_frames(_narrate(tool_name, payload)) if event == "progress"
    ]


def _customer_progress(tool_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        data for event, data in _customer_frames(_narrate(tool_name, payload)) if event == "progress"
    ]


class TestTheDeveloperGetsTheToolsOwnError:
    """`launch-readiness/163`, at the layer both audiences are decided.

    The owner watched a run fail six times and read `"That did not work."`
    six times — `143`'s customer sentence, doing exactly its job on the wrong
    surface. He had to paste the raw payload into a conversation before
    anybody could see `Invalid column name 'loading_time'`, which had been in
    the envelope the whole time.

    Every assertion here goes through the real `_stream_run`, twice, one
    argument apart. A unit test on the composing function would have been
    green for both of `112`'s live leaks.
    """

    def test_a_developer_sees_the_drivers_own_words(self) -> None:
        detail = _developer_progress("mcp_execute_sql", EXECUTE_SQL_FAILED)[-1]["detail"]
        assert detail is not None
        assert "Incorrect syntax near '1'" in detail
        assert "internal_error" in detail

    def test_a_customer_sees_none_of_them(self) -> None:
        assert _customer_progress("mcp_execute_sql", EXECUTE_SQL_FAILED)[-1]["detail"] is None

    def test_the_sentence_is_the_same_for_both_and_the_evidence_is_not(self) -> None:
        # The half `143` settled must survive untouched: the *message* still
        # crosses audiences intact, and the split is made beside it rather
        # than inside it.
        developer = _developer_progress("mcp_execute_sql", EXECUTE_SQL_FAILED)
        customer = _customer_progress("mcp_execute_sql", EXECUTE_SQL_FAILED)
        assert [f["message"] for f in developer] == [f["message"] for f in customer]
        assert developer[-1]["message"] == "That did not work."

    def test_the_drivers_text_still_cannot_reach_a_customer_by_any_field(self) -> None:
        # The negative one, and the one that matters. Not "the detail is
        # None" — every value of every key on every customer frame.
        blob = json.dumps(_customer_frames(_narrate("mcp_execute_sql", EXECUTE_SQL_FAILED))).lower()
        for fragment in ("odbc", "sqlexecdirectw", "incorrect syntax", "internal_error", "42000"):
            assert fragment not in blob, fragment

    def test_a_successful_call_carries_no_evidence_to_either_audience(self) -> None:
        # Silence by default. A field that fires on every line is noise a
        # reader learns to skip, which is the failure `tool_notes` names.
        for frame in _developer_progress("mcp_execute_sql", EXECUTE_SQL):
            assert frame["detail"] is None
        for frame in _customer_progress("mcp_execute_sql", EXECUTE_SQL):
            assert frame["detail"] is None

    def test_the_before_line_never_carries_evidence(self) -> None:
        # Two frames per call; only the finding can have anything to explain.
        assert _developer_progress("mcp_execute_sql", EXECUTE_SQL_FAILED)[0]["detail"] is None

    def test_a_failed_harness_read_explains_itself_to_a_developer(self) -> None:
        frames = [
            data
            for event, data in _developer_frames(_narrate_text("read_file", READ_MISSING))
            if event == "progress"
        ]
        assert frames[-1]["message"] == "That did not work."
        assert frames[-1]["detail"]

    def test_a_failed_harness_read_explains_nothing_to_a_customer(self) -> None:
        frames = [
            data
            for event, data in _customer_frames(_narrate_text("read_file", READ_MISSING))
            if event == "progress"
        ]
        assert frames[-1]["detail"] is None
