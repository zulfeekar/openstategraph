"""A finished run keeps its cadence, so a replay does not have to invent one.

`memory-and-replay` 47. Of the seven SSE frame kinds, `token` is the one that
arrives *while a node is still working*, and it survived nowhere: the settled
message reached the checkpoint's `messages` channel and the chunks, their
order, their `block` and their `withheld` went with the connection. So a play
button built on the old store could only re-type a stored paragraph at a rate
it made up, and a viewer reads motion as duration.

**The grain, and the finding that chose it.** The ticket offered three answers
and assumed a tradeoff: (a) a row per chunk — perfect cadence, most disk; (b)
coalesced bursts — cadence "to within a frame", far less disk; (c) nothing.
Measured against four real `ollama:gpt-oss:120b-cloud` runs of `stress-review`
and `cpl-nl2sql`, the tradeoff does not exist. What (a) costs is not the
cadence, it is the **row**: 242 to 1014 rows each repeating one node's
identity. Pack the identity once per burst and carry the per-chunk offsets as
a delta blob, and the same information costs 5–13x less than (a) and, in two
of three runs, less than lossy (b). So this store keeps grain (b) at grain
(a)'s fidelity — one row per contiguous burst, exact per-chunk cadence inside
it — and `docs/decisions/keeping-the-cadence-2026-08-29.md` carries the
numbers.

The classes below pin each decision that argument rests on.
"""

from __future__ import annotations

import ast
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openstategraph.api.burst_recorder import BURST_CAP, BurstRecorder  # noqa: E402
from openstategraph.run_sinks import (  # noqa: E402
    JsonlRunSink,
    RunRecord,
    SqliteRunSink,
    read_run_bursts,
)

BACKEND = Path(__file__).resolve().parent.parent


def _chunk(
    seq: int,
    elapsed: int,
    content: str,
    *,
    node: str = "agent",
    block: str = "text",
    kind: str = "model",
    namespace: tuple[str, ...] = (),
    withheld: bool = False,
) -> dict[str, Any]:
    return {
        "node": node,
        "namespace": list(namespace),
        "content": content,
        "block": block,
        "kind": kind,
        "withheld": withheld,
        "seq": seq,
        "elapsedMs": elapsed,
    }


class TestCadenceSurvivesExactly:
    """Coalescing is a packing, not a summary — the claim the grain rests on."""

    def test_every_chunk_comes_back_with_its_own_offset(self):
        chunks = [
            _chunk(0, 100, "Hel"),
            _chunk(1, 104, "lo "),
            _chunk(2, 640, "world"),  # a half-second stall inside one burst
            _chunk(3, 641, "!"),
        ]
        recorder = BurstRecorder()
        for chunk in chunks:
            recorder.chunk(chunk)
        (burst,) = recorder.bursts()
        assert burst.replay() == [(100, "Hel"), (104, "lo "), (640, "world"), (641, "!")]

    def test_a_burst_carries_its_own_span_and_count(self):
        recorder = BurstRecorder()
        for i, text in enumerate(["a", "b", "c"]):
            recorder.chunk(_chunk(i, 10 * i, text))
        (burst,) = recorder.bursts()
        assert (burst.first_ms, burst.last_ms, burst.chunks, burst.chars) == (0, 20, 3, 3)
        assert (burst.first_seq, burst.last_seq) == (0, 2)

    def test_a_stall_is_a_measurement_and_not_an_average(self):
        """The whole point. A uniform re-type would put the fourth chunk at
        213 ms; it actually arrived at 640, and the record says so."""
        recorder = BurstRecorder()
        for chunk in (
            _chunk(0, 0, "a"),
            _chunk(1, 1, "b"),
            _chunk(2, 2, "c"),
            _chunk(3, 640, "d"),
        ):
            recorder.chunk(chunk)
        (burst,) = recorder.bursts()
        assert [offset for offset, _ in burst.replay()] == [0, 1, 2, 640]


class TestABurstIsOneNodeOneBlock:
    """What breaks a burst — the identity a row pays for once."""

    def test_a_new_node_starts_a_new_burst(self):
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "a", node="one"))
        recorder.chunk(_chunk(1, 5, "b", node="two"))
        assert [b.node for b in recorder.bursts()] == ["one", "two"]

    def test_reasoning_and_answer_are_different_bursts(self):
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "thinking", block="reasoning"))
        recorder.chunk(_chunk(1, 5, "answer", block="text"))
        assert [b.block for b in recorder.bursts()] == ["reasoning", "text"]

    def test_a_tool_result_is_not_folded_into_the_models_prose(self):
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "rows", kind="tool"))
        recorder.chunk(_chunk(1, 5, "so ", kind="model"))
        assert [b.kind for b in recorder.bursts()] == ["tool", "model"]

    def test_a_mounted_childs_namespace_is_its_own_burst(self):
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "a", namespace=()))
        recorder.chunk(_chunk(1, 5, "b", namespace=("child:1",)))
        assert [b.namespace for b in recorder.bursts()] == [[], ["child:1"]]


class TestTheAudienceBoundaryIsUpstream:
    """`38` found this once on the replay door. It cannot recur here, and the
    reason is structural rather than a filter: the recorder reads the **wire**,
    and `_token_frame` has already emptied a withheld frame's content before a
    byte of it is built. There is nothing withheld to store."""

    def test_a_withheld_chunk_stores_no_text(self):
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "", withheld=True))
        (burst,) = recorder.bursts()
        assert burst.withheld is True
        assert burst.text == ""
        assert burst.chars == 0

    def test_a_withheld_burst_still_says_when_the_node_was_working(self):
        """Emptied, not dropped — the same rule the frame itself obeys, so a
        customer's replay still shows the stall rather than a hole."""
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 100, "", withheld=True))
        recorder.chunk(_chunk(1, 900, "", withheld=True))
        (burst,) = recorder.bursts()
        assert (burst.first_ms, burst.last_ms, burst.chunks) == (100, 900, 2)

    def test_the_run_that_produced_the_bursts_names_its_audience(self):
        """A developer run's bursts carry developer content. A reader serving a
        customer has to be able to refuse them, which needs the fact stored."""
        recorder = BurstRecorder(audience="developer")
        recorder.chunk(_chunk(0, 0, "internal"))
        assert recorder.bursts()[0].audience == "developer"


class TestTheHotPathDoesNoWork:
    """Async-first: a chunk is a list append, and the disk is touched once, at
    the end of the turn, by the sink that already writes the row."""

    def test_recording_a_chunk_opens_no_connection(self, tmp_path: Path):
        sink = SqliteRunSink(tmp_path / "runs.sqlite")
        recorder = BurstRecorder()
        for i in range(500):
            recorder.chunk(_chunk(i, i, "x"))
        assert not (tmp_path / "runs.sqlite").exists()
        sink.record(RunRecord(thread_id="t", bursts=recorder.bursts()))
        assert (tmp_path / "runs.sqlite").exists()

    def test_a_runaway_run_is_bounded_in_memory_and_says_so(self):
        recorder = BurstRecorder()
        for i in range(BURST_CAP + 50):
            recorder.chunk(_chunk(i, i, "x", node=f"node-{i}"))
        bursts = recorder.bursts()
        assert len(bursts) == BURST_CAP
        assert bursts[-1].capped is True
        assert not any(b.capped for b in bursts[:-1])


class TestOneStoreTwoTables:
    """`RunRecord` is one row per turn and `IRunSink` has two members by
    decision. The cadence reaches a sink as a **field on the record** — the
    module's own declared extension point — so a third-party sink shipped
    against today's Protocol receives it without a line changing."""

    def test_the_bursts_round_trip_through_the_store(self, tmp_path: Path):
        recorder = BurstRecorder(audience="developer")
        for i, text in enumerate(["Hel", "lo ", "world"]):
            recorder.chunk(_chunk(i, i * 7, text))
        written = recorder.bursts()
        sink = SqliteRunSink(tmp_path / "runs.sqlite")
        sink.record(
            RunRecord(kind="run", at="2026-08-29T10:00:00+0200", thread_id="t1",
                      workflow_slug="w", answer="Hello world", bursts=written)
        )
        sink.close()
        read = read_run_bursts(tmp_path / "runs.sqlite", thread_id="t1")
        assert read == written
        assert read[0].replay() == [(0, "Hel"), (7, "lo "), (14, "world")]

    def test_two_turns_in_one_thread_keep_their_own_cadence(self, tmp_path: Path):
        sink = SqliteRunSink(tmp_path / "runs.sqlite")
        for turn, text in enumerate(["first", "second"]):
            recorder = BurstRecorder()
            recorder.chunk(_chunk(0, turn, text))
            sink.record(RunRecord(thread_id="t", at=f"2026-08-29T10:0{turn}:00+0200",
                                  bursts=recorder.bursts()))
        sink.close()
        assert [b.text for b in read_run_bursts(tmp_path / "runs.sqlite", thread_id="t")] == [
            "first",
            "second",
        ]

    def test_a_run_with_no_chunks_writes_no_burst_rows(self, tmp_path: Path):
        sink = SqliteRunSink(tmp_path / "runs.sqlite")
        sink.record(RunRecord(thread_id="t", answer="from a function node"))
        sink.close()
        assert read_run_bursts(tmp_path / "runs.sqlite", thread_id="t") == []

    def test_reading_a_store_that_predates_this_ticket_is_not_an_error(
        self, tmp_path: Path
    ):
        """Every store will have runs recorded before capture existed. That is
        *no cadence*, which is an answer — never a crash and never a zero."""
        path = tmp_path / "runs.sqlite"
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE runs (kind TEXT, at TEXT, thread_id TEXT)")
        connection.commit()
        connection.close()
        assert read_run_bursts(path, thread_id="t") == []


class TestTheTextIsTheAnswersRule:
    """A chunk log is the most complete copy of a customer's data this system
    holds. It does not get a new privacy rule — it inherits `answer`'s, which
    `run_sinks` already argued: the local store keeps it, and the file a person
    commits, emails and pastes into an issue keeps only its length."""

    def test_the_jsonl_sink_writes_no_burst_text(self, tmp_path: Path):
        path = tmp_path / "trace.jsonl"
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "the customer's private answer"))
        sink = JsonlRunSink(path)
        sink.record(RunRecord(thread_id="t", answer="the customer's private answer",
                              bursts=recorder.bursts()))
        sink.close()
        written = path.read_text(encoding="utf-8")
        assert "private answer" not in written
        assert json.loads(written)["bursts"] == 1


class TestTheExportCarriesIt:
    """*Nothing sweeps* is only honest because `runs export` exists. A cadence
    the export could not carry would make truncation a loss the store had
    promised it would not be."""

    def test_a_record_survives_json_dumps(self):
        """`IRunSink` exists so a third party can write these rows anywhere,
        and the obvious way is `json.dumps(record.model_dump())` — which raises
        on `bytes`. A contract that cannot survive its own obvious use is a
        trap."""
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "a"))
        recorder.chunk(_chunk(1, 9, "b"))
        record = RunRecord(thread_id="t", bursts=recorder.bursts())
        written = json.dumps(record.model_dump())
        back = RunRecord(**json.loads(written))
        assert back.bursts[0].replay() == [(0, "a"), (9, "b")]

    def test_reading_a_store_with_bursts_keeps_each_turn_to_its_own(
        self, tmp_path: Path
    ):
        sink = SqliteRunSink(tmp_path / "runs.sqlite")
        for turn, text in enumerate(["first", "second"]):
            recorder = BurstRecorder()
            recorder.chunk(_chunk(0, turn, text))
            sink.record(
                RunRecord(thread_id="t", at=f"2026-08-29T10:0{turn}:00+0200",
                          bursts=recorder.bursts())
            )
        sink.close()
        from openstategraph.run_sinks import read_runs

        rows = read_runs(tmp_path / "runs.sqlite", thread_id="t", with_bursts=True)
        assert [[b.text for b in row.bursts] for row in rows] == [["second"], ["first"]]

    def test_a_listing_that_did_not_ask_does_not_pay_for_it(self, tmp_path: Path):
        """And says nothing false: `bursts == []` on a row nobody asked about
        is the same empty a run with no cadence has, so a caller that wants the
        cadence must ask for it rather than infer it from a listing."""
        sink = SqliteRunSink(tmp_path / "runs.sqlite")
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 0, "a"))
        sink.record(RunRecord(thread_id="t", bursts=recorder.bursts()))
        sink.close()
        from openstategraph.run_sinks import read_runs

        assert read_runs(tmp_path / "runs.sqlite", thread_id="t")[0].bursts == []
        assert read_runs(tmp_path / "runs.sqlite", thread_id="t", with_bursts=True)[
            0
        ].bursts


class TestNothingSweeps:
    """The default store is local and unbounded on purpose — *conversations are
    gold*, and `runs export` is the answer to a large file. A second table does
    not get to quietly reverse that, so the same rule is asserted over the same
    module a second time, and over the recorder as well."""

    def test_the_recorder_names_no_sweeper(self):
        source = (BACKEND / "openstategraph" / "api" / "burst_recorder.py").read_text(
            encoding="utf-8"
        )
        named = {
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        assert named, "found no definitions at all — this check would pass vacuously"
        for sweeper in ("prune", "sweep", "expire", "purge", "truncate"):
            assert not any(sweeper in name.lower() for name in named)


class TestARealRunLeavesItsCadenceBehind:
    """The seam, end to end: the fold streams, `_stream_run` records, the turn
    publishes, the store keeps it, and the reader hands it back."""

    def test_a_streamed_run_writes_its_bursts_beside_its_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from conftest import ScriptedGraph, drive_fold

        from openstategraph.api.audience import Audience
        from openstategraph.api.streaming import _stream_run
        from openstategraph.compile.diagnostics import CompileDiagnostics
        from openstategraph.run_sinks import RunSinkRegistry, read_runs

        store = SqliteRunSink(tmp_path / "runs.sqlite")
        registry = RunSinkRegistry()
        registry.register("sqlite", store)
        monkeypatch.setattr(
            "openstategraph.run_sinks._process_registry", registry, raising=False
        )

        def _ai(content: str) -> Any:
            return SimpleNamespace(type="AIMessageChunk", content=content)

        chunks = [
            {"type": "updates", "ns": (), "data": {"in1": {"outputs": {"in1": "hi"}}}},
            {"type": "messages", "ns": (), "data": (_ai("Hel"), {"langgraph_node": "agent_sql"})},
            {"type": "messages", "ns": (), "data": (_ai("lo "), {"langgraph_node": "agent_sql"})},
            {"type": "messages", "ns": (), "data": (_ai("world"), {"langgraph_node": "agent_sql"})},
            {"type": "updates", "ns": (), "data": {"out1": {"answer": "Hello world"}}},
        ]

        class Graph:
            def stream(self, *_: Any, **__: Any) -> Any:
                return iter(chunks)

            def get_state(self, _: Any) -> Any:
                return SimpleNamespace(next=(), tasks=(), values={"answer": "Hello world"})

            def get_graph(self, **_: Any) -> Any:
                return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

        frames = drive_fold(
            _stream_run(
                ScriptedGraph(Graph()),
                {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}},
                {"configurable": {"thread_id": "t-real", "workflow_slug": "w"}},
                SimpleNamespace(warnings=[]),
                {"in1": "in1", "agent_sql": "agent-sql", "out1": "out1"},
                SimpleNamespace(diagnostics=CompileDiagnostics()),
                "t-real",
                Audience.DEVELOPER,
            )
        )
        assert any(frame.startswith("event: done") for frame in frames)
        store.close()

        (row,) = read_runs(tmp_path / "runs.sqlite", thread_id="t-real")
        assert row.answer == "Hello world"
        bursts = read_run_bursts(tmp_path / "runs.sqlite", thread_id="t-real")
        assert [b.node for b in bursts] == ["agent-sql"]
        assert [text for _, text in bursts[0].replay()] == ["Hel", "lo ", "world"]
        assert bursts[0].audience == "developer"

    def test_a_run_that_streams_nothing_records_no_cadence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """*No cadence* is an answer. It must not become *an instant run*."""
        from conftest import ScriptedGraph, drive_fold

        from openstategraph.api.audience import Audience
        from openstategraph.api.streaming import _stream_run
        from openstategraph.compile.diagnostics import CompileDiagnostics
        from openstategraph.run_sinks import RunSinkRegistry

        store = SqliteRunSink(tmp_path / "runs.sqlite")
        registry = RunSinkRegistry()
        registry.register("sqlite", store)
        monkeypatch.setattr(
            "openstategraph.run_sinks._process_registry", registry, raising=False
        )

        class Graph:
            def stream(self, *_: Any, **__: Any) -> Any:
                return iter([{"type": "updates", "ns": (), "data": {"out1": {"answer": "done"}}}])

            def get_state(self, _: Any) -> Any:
                return SimpleNamespace(next=(), tasks=(), values={"answer": "done"})

            def get_graph(self, **_: Any) -> Any:
                return SimpleNamespace(draw_mermaid=lambda: "graph TD;")

        drive_fold(
            _stream_run(
                ScriptedGraph(Graph()),
                {"question": "hi", "attempts": 0, "decisions": {}, "outputs": {}},
                {"configurable": {"thread_id": "t-quiet", "workflow_slug": "w"}},
                SimpleNamespace(warnings=[]),
                {"out1": "out1"},
                SimpleNamespace(diagnostics=CompileDiagnostics()),
                "t-quiet",
                Audience.DEVELOPER,
            )
        )
        store.close()
        assert read_run_bursts(tmp_path / "runs.sqlite", thread_id="t-quiet") == []


class TestWhatAReplayMayClaim:
    """52 inherits a fact from here rather than a hope, and this is the fact:
    a burst's offsets are **measured**, so a play button may claim them; a run
    with no bursts has no cadence at all, and `None` never zero."""

    def test_a_burst_reports_the_measurement_it_actually_holds(self):
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 40, "a"))
        recorder.chunk(_chunk(1, 90, "b"))
        (burst,) = recorder.bursts()
        assert burst.duration_ms() == 50

    def test_one_chunk_is_an_instant_and_not_an_unknown(self):
        recorder = BurstRecorder()
        recorder.chunk(_chunk(0, 40, "a"))
        assert recorder.bursts()[0].duration_ms() == 0
