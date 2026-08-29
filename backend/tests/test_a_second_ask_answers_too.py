"""The second `ask` through the library door answers too (`launch-readiness/171`).

## The measurement this file replaces

A stranger installed the wheel and ran the README's headline shape — no context
manager, no editor, no server — and got this:

    lap0: 'banana'   lap1: ''   lap2: 'banana'   lap3: ''

**Every second call answered nothing, silently.** 5 of 10 on each of two
ten-lap trials, identical on `starter`, `chained-summarizer` and `sql-qa`, with
`RuntimeError: Event loop is closed` reachable only through
`result.warnings`. `str(result)` was `''`, so a reader printing the answer saw
a blank line.

## Why 6,072 green tests never saw it

**A scripted model holds no transport.** `async-first/12` moved the loop's
owner up to the run, which fixed a run whose *second node* found the first
node's loop closed. What it did not move is the **provider client**, which
`load_workflow` builds once and the workflow holds for its whole life. So the
loop's lifetime became the run and the client's stayed the workflow's, and the
second run reached a connection pool bound to the first run's closed loop.

Nothing in this suite could fail that way, because nothing in it kept a socket
open between calls. So the model here does: `Connected` holds one
`httpx.AsyncClient` and makes a real request to a real local server on every
generation, over a keep-alive connection. That is the whole lesson of the
ticket, and it is why the server below sets `protocol_version = "HTTP/1.1"` —
with HTTP/1.0 every request opens its own socket, nothing is left bound to a
loop, and this file goes green against the bug.
"""

from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest
from conftest import RespondingModel

from openstategraph.errors import RunProducedNothing
from openstategraph.loader import load_workflow
from openstategraph.results import RunResult, produced_nothing
from openstategraph.run_doors import RunLoop

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"


class _Handler(BaseHTTPRequestHandler):
    #: Keep-alive, and that is the point rather than a detail. A pooled
    #: connection is what a provider SDK holds and what binds to a loop.
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args: Any) -> None:
        """Silence: this server exists to hold a socket, not to narrate."""


class _CountingServer(ThreadingHTTPServer):
    """Counts accepted connections, so a test can prove the pool was reused."""

    connections = 0

    def get_request(self) -> Any:
        type(self).connections += 1
        return super().get_request()


@pytest.fixture()
def endpoint() -> Iterator[str]:
    server = _CountingServer(("127.0.0.1", 0), _Handler)
    type(server).connections = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


class Connected(RespondingModel):
    """A scripted model that **holds a connection between calls**.

    Everything else about it is `RespondingModel`; the only addition is the one
    property no other fake in this suite has, and the only one that can fail
    the way a real provider failed.
    """

    def __init__(self, url: str, reply: str = "A short summary.", delay: float = 0.0) -> None:
        super().__init__([], reply)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "delay", delay)
        object.__setattr__(self, "transport", None)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN201
        import asyncio

        import httpx

        if self.transport is None:
            object.__setattr__(self, "transport", httpx.AsyncClient())
        if self.delay:
            await asyncio.sleep(self.delay)
        await self.transport.get(self.url)
        return self._generate(messages)


def _package(tmp_path: Path, name: str = "chained-summarizer") -> Path:
    destination = tmp_path / name
    shutil.copytree(EXAMPLES / name, destination)
    return destination


class TestTenAsksInOneProcessAnswerTenTimes:
    """The stranger's own acceptance test, in a suite that can run offline."""

    def test_every_lap_answers(self, tmp_path: Path, endpoint: str) -> None:
        with load_workflow(_package(tmp_path), model=Connected(endpoint)) as workflow:
            answers = [
                str(workflow.ask("Summarise the release notes.", thread_id=f"lap-{lap}"))
                for lap in range(10)
            ]
        assert [bool(answer.strip()) for answer in answers] == [True] * 10

    def test_and_no_lap_reports_a_closed_loop(self, tmp_path: Path, endpoint: str) -> None:
        """The alternation was exact, so lap 1 is the whole regression."""
        with load_workflow(_package(tmp_path), model=Connected(endpoint)) as workflow:
            workflow.ask("Summarise the release notes.", thread_id="first")
            second = workflow.ask("Summarise the release notes.", thread_id="second")
        assert "Event loop is closed" not in " ".join(second.warnings)
        assert str(second).strip()


class TestTheConnectionPoolSurvivesTheFix:
    """Per-run clients would answer ten times too — and would pay a handshake a
    question, which `777e829` measured at 1.21 s → 0.54 s and fixed. So the
    lifetime chosen has to keep the pool, and this is what says it did."""

    def test_ten_laps_reuse_one_connection(self, tmp_path: Path, endpoint: str) -> None:
        with load_workflow(_package(tmp_path), model=Connected(endpoint)) as workflow:
            for lap in range(10):
                workflow.ask("Summarise the release notes.", thread_id=f"pool-{lap}")
        # `chained-summarizer` calls the model twice per run: 20 requests.
        assert _CountingServer.connections == 1


class TestTwoRunsAtOnceOnOneWorkflow:
    """The other half the lifetime has to survive. A workflow is a legitimate
    thing to hold in a server and ask from two threads at once, and the loop
    owning its client must interleave them rather than refuse the second."""

    def test_both_threads_answer(self, tmp_path: Path, endpoint: str) -> None:
        with load_workflow(
            _package(tmp_path), model=Connected(endpoint, delay=0.05)
        ) as workflow:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        workflow.ask, "Summarise the release notes.", thread_id=f"race-{n}"
                    )
                    for n in range(2)
                ]
                answers = [str(future.result()) for future in futures]
        assert [bool(answer.strip()) for answer in answers] == [True, True]


class TestARunThatProducedNothingIsNeverABlankLine:
    """The worse half of the ticket, and fixed independently of the cause.

    Whatever leaves a run with no answer, a door that returns `''` and puts the
    reason somewhere the README never mentions is a silent failure. The rule is
    the one `cli.run_exit_code` already gated on — *no answer **and** something
    went wrong* — moved to `results.produced_nothing` so the exit code and the
    library door cannot disagree about what a failed run is.
    """

    def test_an_empty_answer_with_a_reason_is_a_raise(self) -> None:
        result = RunResult(
            "",
            failures=['Node "agent1" failed and produced no result. RuntimeError: boom'],
        )
        assert produced_nothing(result) is True

    def test_an_empty_answer_with_nothing_wrong_is_still_legal(self) -> None:
        """A workflow may answer with nothing. Only the pair is a failure."""
        assert produced_nothing(RunResult("")) is False

    def test_a_pause_is_not_a_failure(self) -> None:
        """A run stopped at a gate has not failed — it is waiting."""
        result = RunResult("", failures=["something"], pause={"message": "ok?"})
        assert produced_nothing(result) is False

    def test_the_error_carries_the_whole_run(self) -> None:
        """`async-first/13`'s rule: a diagnosis names the fix and never
        replaces what it diagnosed. The `RunResult` is on the exception, so
        nothing a caller could have read is lost by raising."""
        result = RunResult("", failures=["Node \"agent1\" failed"])
        error = RunProducedNothing.of(result)
        assert error.result is result
        assert "agent1" in str(error)


class TestTheDiagnosisNoLongerPointsAtABrokenDoor:
    """`_WRONG_DOOR` tells a reader hitting `Event loop is closed` to use
    `workflow.ask(...)`. That advice was false when this ticket was filed. It
    is pinned here rather than merely re-read, because a comment asserting a
    property the code lacks is the defect class this repository has fixed four
    times this month."""

    def test_the_advice_names_ask(self) -> None:
        from openstategraph.compile.node_doors import _WRONG_DOOR

        assert "workflow.ask(...)" in _WRONG_DOOR

    def test_and_ask_survives_a_second_call(self, tmp_path: Path, endpoint: str) -> None:
        """The same assertion as above, made of the door rather than of prose."""
        with load_workflow(_package(tmp_path), model=Connected(endpoint)) as workflow:
            workflow.ask("Summarise the release notes.", thread_id="advice-1")
            assert str(workflow.ask("Summarise the release notes.", thread_id="advice-2")).strip()


class TestTheLoopIsOwnedByWhateverOwnsTheClient:
    """`RunLoop` is the collaborator that says so. Its lifetime is its owner's:
    a `CompiledWorkflow` holds one because a `CompiledWorkflow` holds the
    client, and the three doors that build a model per call keep the run-scoped
    loop they already had."""

    def test_one_loop_serves_many_runs(self) -> None:
        import asyncio

        loop = RunLoop()

        async def which() -> int:
            return id(asyncio.get_running_loop())

        try:
            assert loop.run(which) == loop.run(which)
        finally:
            loop.close()

    def test_a_closed_loop_is_closed_idempotently(self) -> None:
        loop = RunLoop()
        loop.run(_nothing)
        loop.close()
        loop.close()

    def test_it_propagates_the_callers_context(self) -> None:
        """`ask` counts tokens with `get_usage_metadata_callback`, which is a
        context variable set on the calling thread. A loop on a thread of its
        own that did not copy the context would leave every run's usage empty —
        `launch-readiness/110`'s blank panel with a green suite, again."""
        import contextvars

        marker: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="")
        marker.set("set-by-the-caller")
        loop = RunLoop()

        async def read() -> str:
            return marker.get()

        try:
            assert loop.run(read) == "set-by-the-caller"
        finally:
            loop.close()


async def _nothing() -> None:
    return None
