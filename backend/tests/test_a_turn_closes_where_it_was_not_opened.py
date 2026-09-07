"""A turn is closed by whoever resumes the generator, not by whoever opened it.

`launch-readiness` 180, the half `108` did not reach.

`108` fixed the *reads*: `_stream_run` re-binds the frame clock on every
resumption, because the transport pulls each frame inside its own task and a
task runs on a **copy** of the context that created it. Measured on this base
over a real socket, that half is fixed — every frame of a real run is dated and
the sequence is dense.

The *release* was still broken, and by somebody else's token. `run_turn` enters
`langchain_core.callbacks.get_usage_metadata_callback()` on the same generator's
`ExitStack`, so that library context manager is exited in a context that never
saw its `set`. On `langchain-core` **1.5.3** its `finally` reads `set(None)` and
nothing happens. On **1.6.1** — which `backend/pyproject.toml`'s
`langchain-core>=1.0,<2` allows, and which is what a machine resolving the range
today installs — it reads `reset(token)`, which raises:

    ValueError: <Token ...> was created in a different Context

Reproduced on this base over a real socket against a real uvicorn: the four
frames of the run arrive, dated, and then `turn_stack.close()` raises out of
`stop_when_client_leaves` mid-body, so the client sees
`httpx.RemoteProtocolError: peer closed connection without sending complete
message body`. **The `ValueError` is the library's, not ours** — our own
`_open_turn` guard was already tolerant and was never the one raising.

**So this file injects the meter rather than trusting the installed one.**
`108`'s `test_the_frame_clock_survives_the_transport.py` does catch this — but
only on an interpreter that has 1.6.1, and this repository's system interpreter
has 1.5.3, so on a developer's machine the whole suite stays green while a
supported dependency takes every streamed run down. A version we cannot see is
not a contract; the *shape* is. The double below is 1.6.1's `finally` and
nothing else, so what is pinned is "a turn survives a meter that resets its own
token", which stays true of 1.7 and of a library that goes back to `set(None)`.

The strictness half is pinned too: a `ValueError` raised while the turn *is*
being closed in its opening context is a real error and still propagates. What
tells the two apart is not the message — a string match on someone else's
exception is not a contract either — but our own token, reset immediately
before, in the same context, as a measurement of which context this is.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import ScriptedGraph  # noqa: E402

from openstategraph import run_journal  # noqa: E402
from openstategraph.api.audience import Audience  # noqa: E402
from openstategraph.api.streaming import (  # noqa: E402
    _stream_run,
    stop_when_client_leaves,
)
from openstategraph.compile.diagnostics import CompileDiagnostics  # noqa: E402


class _ResettingMeter:
    """`get_usage_metadata_callback` as `langchain-core` 1.6.1 writes it.

    A fresh `ContextVar` per call, `set` on enter, and `reset(token)` in a
    `finally` on exit — which is the whole of the difference from 1.5.3, and
    the whole of the defect.
    """

    def __init__(self) -> None:
        self._var: contextvars.ContextVar[Any] = contextvars.ContextVar(
            "usage_metadata_callback", default=None
        )
        self._token: Any = None
        self.handler = SimpleNamespace(usage_metadata={})

    def __enter__(self) -> Any:
        self._token = self._var.set(self.handler)
        return self.handler

    def __exit__(self, *_exc: Any) -> bool:
        self._var.reset(self._token)
        return False


class _ExplodingMeter:
    """A meter whose exit raises a `ValueError` that has nothing to do with a
    context. Tolerance must not reach this one."""

    def __enter__(self) -> Any:
        return SimpleNamespace(usage_metadata={})

    def __exit__(self, *_exc: Any) -> bool:
        raise ValueError("the meter itself is broken")


@pytest.fixture
def resetting_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    import langchain_core.callbacks as callbacks

    monkeypatch.setattr(
        callbacks, "get_usage_metadata_callback", lambda *a, **k: _ResettingMeter()
    )


class TestATurnSurvivesTheContextItIsClosedIn:
    def test_the_double_reproduces_the_library_crash_on_its_own(self) -> None:
        """Anti-vacuity: if the double did not raise across contexts, every
        assertion below would pass against nothing."""
        meter = _ResettingMeter()
        contextvars.copy_context().run(meter.__enter__)

        with pytest.raises(ValueError, match="different Context"):
            meter.__exit__(None, None, None)

    def test_closing_in_another_context_does_not_raise(self, resetting_meter: None) -> None:
        turn = run_journal.run_turn(workflow_slug="w", thread_id="t1", question="q")
        contextvars.copy_context().run(turn.__enter__)

        turn.__exit__(None, None, None)  # the transport's context, not the opener's

    def test_closing_in_its_own_context_still_reports_a_real_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import langchain_core.callbacks as callbacks

        monkeypatch.setattr(
            callbacks, "get_usage_metadata_callback", lambda *a, **k: _ExplodingMeter()
        )
        turn = run_journal.run_turn(workflow_slug="w", thread_id="t1", question="q")
        turn.__enter__()

        with pytest.raises(ValueError, match="the meter itself is broken"):
            turn.__exit__(None, None, None)


KNOWN = {"in1": "in1", "agent_sql": "agent-sql", "out1": "out1"}


def _chunks() -> list[dict[str, Any]]:
    return [
        {"type": "updates", "ns": (), "data": {"in1": {"outputs": {"in1": "hello"}}}},
        {"type": "updates", "ns": (), "data": {"agent_sql": {"answer": "347."}}},
        {"type": "updates", "ns": (), "data": {"out1": {"answer": "There are 347 albums."}}},
    ]


class _Graph:
    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        return iter(_chunks())

    def get_state(self, _config: Any) -> Any:
        return SimpleNamespace(next=(), tasks=())

    def get_graph(self, **_kwargs: Any) -> Any:
        return SimpleNamespace(draw_mermaid=lambda: "graph TD;")


async def _still_here() -> dict:
    await asyncio.sleep(3600)
    return {"type": "http.request"}


def _through_the_transport() -> list[tuple[str, dict[str, Any]]]:
    """Every frame of one run, pulled the way `StreamingResponse` pulls them —
    each inside its own task, and therefore each in a context of its own."""

    async def go() -> list[str]:
        stream = _stream_run(
            ScriptedGraph(_Graph()),
            {},
            {},
            SimpleNamespace(warnings=[]),
            KNOWN,
            SimpleNamespace(diagnostics=CompileDiagnostics()),
            "t1",
            Audience.DEVELOPER,
        )
        return [frame async for frame in stop_when_client_leaves(stream, _still_here)]

    read: list[tuple[str, dict[str, Any]]] = []
    for frame in asyncio.run(go()):
        head, _, body = frame.partition("\ndata: ")
        read.append((head[len("event: ") :], json.loads(body.rstrip("\n"))))
    return read


class TestAStreamedRunCompletesOnAMeterThatResets:
    def test_the_run_reaches_its_terminal_frame(self, resetting_meter: None) -> None:
        """The symptom a client sees: not a wrong value, a truncated body. The
        stream died at `turn_stack.close()`, after its last frame and before
        the chunked terminator."""
        frames = _through_the_transport()

        assert frames, "the stream produced nothing at all"
        assert frames[-1][0] in {"done", "interrupt", "error"}

    def test_no_frame_of_it_is_an_error_frame(self, resetting_meter: None) -> None:
        assert [name for name, _ in _through_the_transport() if name == "error"] == []
