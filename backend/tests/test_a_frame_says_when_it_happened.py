"""Every run frame says *when* it was produced and *in what order*.

`memory-and-replay` 46. `streaming.py` emitted seven frame kinds and not one
of them carried a time or a sequence number. A grep for `datetime.now`,
`utcnow`, `perf_counter` or `time.monotonic` across that module returned
nothing, so the only clock in the whole run seam was `RunRecord.at` — one
stamp for the whole turn — and every duration the editor showed was measured
in the *browser*, on frame arrival, by `ExecutionEngine`. That measurement
exists only inside the tab that was watching: reload, and a run's shape
survives in the checkpointer while its cadence does not.

**Five decisions, each argued in `docs/decisions/a-frame-says-when-2026-08-29.md`
and each pinned below.**

1. **Server clock.** The stamp is minted where the frame is built, so it
   measures the run rather than the network. The browser's arrival clock stays
   where it is and keeps answering its own, different question.
2. **Monotonic cadence, wall anchor.** `elapsedMs` comes from
   `time.monotonic()`, so a run crossing an NTP correction cannot go backwards;
   the wall anchor a reader needs to correlate a run with a log line is
   `RunRecord.at`, which the same turn already records in ISO wall time.
   Nothing on the wire disagrees with the checkpoints, because nothing on the
   wire restates them.
3. **Relative.** An offset from the run's own start is smaller, is what a
   scrubber needs, and cannot say when the run happened — which is the point
   below about what the stamp must *not* smuggle.
4. **`seq` as well, and it was the cheap half.** Two frames can share a
   millisecond; a monotonic counter makes recorded order recoverable without
   relying on the clock at all, and makes a dropped frame visible.
5. **Minted in the one place a frame is built**, so the marginal cost to
   tickets 47 and 48 — which add fields, and may add a kind — is zero.

The last is what the final class holds: a frame kind cannot be added without
the stamp, because the emitter mints it and `FRAME_FIELDS` composes it in.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ScriptedGraph, drive_fold  # noqa: E402

from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.frame_clock import FRAME_CLOCK_FIELDS  # noqa: E402
from openstategraph.api.streaming import (  # noqa: E402
    FRAME_FIELDS,
    RUN_EVENTS,
    _stream_run,
)
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
STREAMING = BACKEND / "openstategraph" / "api" / "streaming.py"

KNOWN = {"in1": "in1", "agent_sql": "agent-sql", "out1": "out1"}


def _ai(content: str, **extra: Any) -> Any:
    return SimpleNamespace(type="AIMessageChunk", content=content, **extra)


def _chunks() -> list[dict[str, Any]]:
    """One run touching `updates`, `custom` and `messages` — the three modes
    the fold reads, so the frames below are four kinds rather than one."""
    from openstategraph.progress import PROGRESS_KEY, Progress

    return [
        {"type": "updates", "ns": (), "data": {"in1": {"outputs": {"in1": "hello"}}}},
        {
            "type": "custom",
            "ns": (),
            "data": {
                PROGRESS_KEY: Progress(message="Read 40 of 100", node="agent_sql").model_dump()
            },
        },
        {
            "type": "messages",
            "ns": ("agent_sql:task-1",),
            "data": (_ai("Checking."), {"langgraph_node": "agent_sql"}),
        },
        {"type": "updates", "ns": (), "data": {"out1": {"answer": "There are 347 albums."}}},
    ]


class _Graph:
    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        return iter(_chunks())

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


def _frames(audience: Audience = Audience.DEVELOPER) -> list[str]:
    runtime = SimpleNamespace(diagnostics=CompileDiagnostics())
    return drive_fold(
        _stream_run(
            ScriptedGraph(_Graph()),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            runtime,
            "t1",
            audience,
        )
    )


def _payloads(frames: list[str]) -> list[tuple[str, dict[str, Any]]]:
    read = []
    for frame in frames:
        head, _, body = frame.partition("\ndata: ")
        read.append((head[len("event: ") :], json.loads(body.rstrip("\n"))))
    return read


class TestEveryFrameIsDated:
    def test_the_run_produced_more_than_one_kind_of_frame(self) -> None:
        """Anti-vacuity: a run that only ever emitted `done` would make every
        assertion below a statement about one frame."""
        kinds = {name for name, _ in _payloads(_frames())}

        assert kinds >= {"update", "token", "progress", "done"}

    def test_not_one_of_them_arrives_undated(self) -> None:
        for name, payload in _payloads(_frames()):
            missing = [field for field in FRAME_CLOCK_FIELDS if field not in payload]
            assert not missing, f"a `{name}` frame carries no {missing}"

    def test_the_sequence_is_dense_and_starts_at_zero(self) -> None:
        """Dense, not merely increasing: a scrubber that can see a gap can
        tell a dropped frame from a quiet run, which is the whole reason a
        counter is carried beside a clock."""
        assert [p["seq"] for _, p in _payloads(_frames())] == list(range(len(_frames())))

    def test_the_clock_never_runs_backwards(self) -> None:
        elapsed = [p["elapsedMs"] for _, p in _payloads(_frames())]

        assert all(isinstance(value, int) and value >= 0 for value in elapsed), elapsed
        assert elapsed == sorted(elapsed)


class TestWhatTheStampDoesNotSay:
    """The audience boundary. A cadence is harmless; an absolute stamp is a
    fact about the server that a customer's frame has no reason to carry, and
    a recorded run replayed later would leak when it happened."""

    def test_a_customer_and_a_developer_are_clocked_alike(self) -> None:
        customer = [(name, p["seq"]) for name, p in _payloads(_frames(Audience.CUSTOMER))]
        developer = [(name, p["seq"]) for name, p in _payloads(_frames(Audience.DEVELOPER))]

        assert [seq for _, seq in customer] == list(range(len(customer)))
        assert [name for name, _ in customer] == [name for name, _ in developer]

    def test_no_frame_says_when_the_run_happened(self) -> None:
        """`elapsedMs` is an offset, so it is small. A wall stamp that leaked
        in as an epoch — in seconds or milliseconds — would not be."""
        for name, payload in _payloads(_frames(Audience.CUSTOMER)):
            for field in FRAME_CLOCK_FIELDS:
                assert payload[field] < 10**8, f"`{name}`.{field} looks like a wall clock"


class TestEachRunCarriesItsOwnClock:
    def test_a_second_run_starts_at_zero_again(self) -> None:
        """The counter belongs to the stream, not to the process. A module
        global would make the second run of a server's life start at 40."""
        first = _payloads(_frames())
        second = _payloads(_frames())

        assert first[0][1]["seq"] == 0
        assert second[0][1]["seq"] == 0


class TestAFrameKindCannotBeAddedWithoutOne:
    """Parsed over the module rather than asserted about the frames a scripted
    run happens to reach — the shape `test_a_runs_diagram_opens_its_mounts.py`
    uses for `draw_mermaid`. A kind emitted only on a path no fixture drives
    would otherwise join the wire undated and nothing would say so."""

    @staticmethod
    def _kinds_built_in(path: Path) -> set[str]:
        """Every literal event name handed to `_sse` in `path`."""
        names = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_sse"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                names.add(node.args[0].value)
        return names

    def test_the_parser_is_reading_something(self) -> None:
        assert len(self._kinds_built_in(STREAMING)) >= 4

    def test_every_kind_this_module_builds_is_one_the_contract_declares(self) -> None:
        undeclared = self._kinds_built_in(STREAMING) - set(RUN_EVENTS)

        assert not undeclared, (
            f"{sorted(undeclared)} is emitted and undeclared — add it to `RUN_EVENTS` "
            "and `_PAYLOAD_FIELDS`, which is what puts the clock on it"
        )

    def test_every_declared_kind_carries_the_clock(self) -> None:
        for name in RUN_EVENTS:
            assert set(FRAME_CLOCK_FIELDS) <= set(FRAME_FIELDS[name]), name

    def test_the_declaration_composes_the_clock_in_rather_than_repeating_it(self) -> None:
        """The structural half. `FRAME_FIELDS` is built from the payload table
        plus `FRAME_CLOCK_FIELDS`, so a new row cannot omit them; a hand-typed
        dict literal would make the test above something a contributor has to
        remember."""
        source = STREAMING.read_text()

        assert "FRAME_CLOCK_FIELDS" in source
        assert "FRAME_FIELDS: dict[str, tuple[str, ...]] = {\n    \"update\"" not in source

    def test_nothing_else_builds_an_sse_frame(self) -> None:
        """The seam, guarded. `_sse` is the one place a frame is built and now
        the one place the stamp is minted; a second builder anywhere under
        `openstategraph/` would be a frame that arrives undated."""
        offenders = []
        for path in sorted((BACKEND / "openstategraph").rglob("*.py")):
            relative = path.relative_to(BACKEND / "openstategraph").as_posix()
            if relative == "api/streaming.py":
                continue  # this module IS the builder
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.JoinedStr) and any(
                    isinstance(part, ast.Constant)
                    and isinstance(part.value, str)
                    # The wire separator itself — `\ndata: ` — rather than a
                    # bare `data: `, which `api/sse_contract.py` writes into the
                    # OpenAPI *description* while emitting nothing.
                    and "\ndata: " in part.value
                    for part in node.values
                ):
                    offenders.append(relative)
                    break
        assert not offenders, (
            f"these format an SSE frame themselves: {offenders} — call `_sse`, "
            "which is what dates it"
        )
