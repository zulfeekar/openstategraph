"""Live patrol events: the broadcaster, and the `/api/kanban/patrol/events`
endpoint — kanban-patrol/07.

Same split `test_catalogue_events.py` makes, for the sibling fan-out:

1. **The fan-out** (`patrol_events.PatrolBroadcaster`) — pure asyncio, no HTTP.
2. **The seam** — that `POST /api/kanban/patrol/run` emits `started`, that a
   card filed by the background patrol emits `progressed`, that the run
   finishing emits `finished`, that it failing emits `failed` with the plain
   reason, and that a subscriber sees none of it before it connects (no
   replay).
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from openstategraph.api.main import create_app
from openstategraph.api.patrol_events import PatrolBroadcaster, PatrolEvent
from openstategraph.patrol import PatrolResult


async def _take(subscriber, count: int, *, timeout: float = 1.0) -> list:
    received: list = []
    stream = subscriber.events()

    async def pump() -> None:
        async for event in stream:
            received.append(event)
            if len(received) >= count:
                return

    await asyncio.wait_for(pump(), timeout=timeout)
    await stream.aclose()
    return received


class TestFanOut:
    def test_every_subscriber_receives_every_event(self) -> None:
        async def scenario() -> list[list]:
            broadcaster = PatrolBroadcaster()
            with broadcaster.subscribe() as a, broadcaster.subscribe() as b:
                broadcaster.publish(PatrolEvent(kind="started"))
                broadcaster.publish(PatrolEvent(kind="finished", filed=1))
                return [await _take(s, 2) for s in (a, b)]

        for received in asyncio.run(scenario()):
            assert [e.kind for e in received] == ["started", "finished"]

    def test_a_progressed_event_carries_task_id_and_title(self) -> None:
        async def scenario():
            broadcaster = PatrolBroadcaster()
            with broadcaster.subscribe() as sub:
                broadcaster.publish(
                    PatrolEvent(kind="progressed", task_id="proj-x:thread-1", title="A bug")
                )
                return (await _take(sub, 1))[0]

        event = asyncio.run(scenario())
        assert event.as_dict()["task_id"] == "proj-x:thread-1"
        assert event.as_dict()["title"] == "A bug"

    def test_a_failed_event_carries_the_plain_reason(self) -> None:
        async def scenario():
            broadcaster = PatrolBroadcaster()
            with broadcaster.subscribe() as sub:
                broadcaster.publish(PatrolEvent(kind="failed", reason="sqlite disk I/O error"))
                return (await _take(sub, 1))[0]

        event = asyncio.run(scenario())
        assert event.as_dict()["reason"] == "sqlite disk I/O error"

    def test_publishing_with_no_subscribers_is_a_no_op(self) -> None:
        PatrolBroadcaster().publish(PatrolEvent(kind="started"))

    def test_a_late_subscriber_receives_nothing_from_before_it_connected(self) -> None:
        """The no-replay half of `07`'s own 'done when': a subscriber that
        connects after an event was published never sees it — the store
        (the job registry, `GET /api/kanban/patrol/status`) is the source of
        truth for what already happened, this stream is only a hint about
        what happens next."""

        async def scenario() -> bool:
            broadcaster = PatrolBroadcaster()
            broadcaster.publish(PatrolEvent(kind="started"))
            with broadcaster.subscribe() as sub:
                broadcaster.publish(PatrolEvent(kind="finished", filed=0))
                received = await _take(sub, 1)
            return received[0].kind == "finished"

        assert asyncio.run(scenario()) is True


# The default `_Surface.next_frame` deadline (2.0s) is for the fast, no real
# background work cases — a fan-out unit test, or an endpoint check with a
# stubbed/instant patrol. The two real-patrol cases wait under this larger
# ceiling instead, because the POST spawns a genuine `asyncio` background task
# through the real ASGI app.
#
# **It is a hung-server ceiling and nothing else, and that correction is the
# substance of `stable-beta-public/32`.** That ticket first read CI run
# 33993202005 as a loaded runner missing a 2s wall clock and raised the
# deadline to 30s; run 33995697649 then failed *with the 30s ceiling already
# in place*, which no amount of runner load explains. The real cause was the
# transport, not the clock — see `_call_once` below — and a frame that is
# never published does not arrive in thirty seconds or in thirty minutes.
REAL_PATROL_FRAME_CEILING = 30.0


class _Surface:
    """One open `/api/kanban/patrol/events` connection, driven through the
    raw ASGI interface — `test_catalogue_events.py`'s own `_Surface`, aimed
    at the sibling stream. See that class's docstring for why `TestClient`
    cannot hold an unbounded stream open."""

    def __init__(self, app) -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._chunks: list[str] = []
        self._buffer = ""
        self._disconnect = asyncio.Event()
        self.task = asyncio.ensure_future(app(_scope(), self._receive, self._send))

    async def _receive(self) -> dict:
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                self._chunks.append(body.decode())

    async def next_frame(self, *, timeout: float = 2.0) -> dict[str, str]:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            while "\n\n" in self._buffer or self._chunks:
                if "\n\n" not in self._buffer:
                    self._buffer += self._chunks.pop(0)
                    continue
                raw, self._buffer = self._buffer.split("\n\n", 1)
                if raw.startswith(":") or not raw.strip():
                    continue
                frame: dict[str, str] = {}
                for line in raw.split("\n"):
                    if line.startswith("event: "):
                        frame["event"] = line[7:]
                    elif line.startswith("data: "):
                        frame["data"] = line[6:]
                return frame
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("no event frame arrived in time")
            await asyncio.sleep(0.005)

    async def next_frames(self, count: int, *, timeout: float) -> list[dict[str, str]]:
        """The next `count` frames, or an `AssertionError` naming what did arrive.

        `next_frame`'s own message — *"no event frame arrived in time"* — is
        true of the third frame and of the first alike, and that is exactly how
        `stable-beta-public/32` was first misread: the CI log said no frame
        arrived, the reader inferred a slow *start*, and the run had in fact
        delivered `started` and `progressed` and lost only `finished`. A
        failure here says which kinds it already had.
        """
        frames: list[dict[str, str]] = []
        for _ in range(count):
            try:
                frames.append(await self.next_frame(timeout=timeout))
            except AssertionError:
                kinds = [json.loads(frame["data"])["kind"] for frame in frames]
                raise AssertionError(
                    f"waited {timeout}s for frame {len(frames) + 1} of {count}; "
                    f"received {kinds}"
                ) from None
        return frames

    async def opened(self, *, timeout: float = 2.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while self.status is None or not (self._chunks or self._buffer):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the stream never opened")
            await asyncio.sleep(0.005)

    async def hang_up(self) -> None:
        self._disconnect.set()
        await asyncio.wait_for(self.task, timeout=2.0)


def _scope(path: str = "/api/kanban/patrol/events", method: str = "GET") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }


async def _call_once(app, path: str, *, method: str = "POST") -> int:
    """One request, awaited on the caller's own event loop. Returns the status.

    **Why not `TestClient`, and this is `stable-beta-public/32`'s real cause.**
    A `TestClient` not held open as a context manager runs each request on a
    *per-request* `anyio` blocking portal: a fresh event loop, in a fresh
    thread, torn down the moment the response is returned. `POST
    /api/kanban/patrol/run` answers `202` and leaves a background task running
    — that is the whole point of `kanban-patrol/07` — and that task is created
    on whichever loop served the request. So the portal's teardown reached
    `asyncio.run`'s `_cancel_all_tasks` and cancelled the patrol coroutine
    while it sat in `await loop.run_in_executor(...)`.

    The two frames published *outside* that coroutine still arrived — `started`
    from the request handler itself, `progressed` from the executor thread the
    loop waits for on shutdown — and `finished` never did. Which is what CI saw
    twice: not a slow first frame, a third frame that was never published. It
    is a pure race between the response returning and the executor completing,
    so it is invisible on a fast machine and reproducible on a loaded one; with
    a 0.3s patrol it fails every single time.

    Calling the ASGI app directly puts the request, the background task and the
    subscriber on **one** loop — the scenario's own, which lives until the
    scenario ends. That is also the production shape: uvicorn's loop outlives
    any one response, which is why the product seam is right and only the test
    transport was wrong.
    """
    status = 0

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    await app(_scope(path, method), receive, send)
    return status


class TestTheEndpoint:
    def test_it_answers_as_an_event_stream(self, tmp_path: Path) -> None:
        async def scenario():
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app)
            await surface.opened()
            result = (surface.status, surface.headers.get("content-type", ""))
            await surface.hang_up()
            return result

        status, content_type = asyncio.run(scenario())
        assert status == 200
        assert content_type.startswith("text/event-stream")

    def test_a_real_patrol_emits_started_progressed_and_finished(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end: `POST /api/kanban/patrol/run` through to a subscriber
        already listening on `/api/kanban/patrol/events`. The patrol itself
        is stubbed — its own read-classify-file loop is `test_patrol.py`'s
        job — so this proves the wiring: the route's background task
        publishes what it says it publishes."""

        def fake_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            if on_card_filed is not None:
                on_card_filed("proj-x:thread-1", "A stubbed finding")
            return PatrolResult(filed=["proj-x:thread-1"], skipped=[], total_findings=1)

        monkeypatch.setattr("openstategraph.patrol.run_patrol", fake_patrol)

        async def scenario():
            from openstategraph.config_file import render_config_file, reset_active_config

            config_path = tmp_path / "openstategraph.yaml"
            config_path.write_text(render_config_file(project_id="proj-x"))
            monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config_path))
            reset_active_config()

            workflows_root = tmp_path / "workflows"
            workflows_root.mkdir()
            app = create_app(graph_factory=lambda _m: None, workflows_root=workflows_root)
            surface = _Surface(app)
            await surface.opened()

            status = await _call_once(app, "/api/kanban/patrol/run")

            frames = await surface.next_frames(3, timeout=REAL_PATROL_FRAME_CEILING)
            await surface.hang_up()
            reset_active_config()
            return status, frames

        status_code, frames = asyncio.run(scenario())
        assert status_code == 202
        kinds = [json.loads(frame["data"])["kind"] for frame in frames]
        assert kinds == ["started", "progressed", "finished"]
        progressed = json.loads(frames[1]["data"])
        assert progressed["task_id"] == "proj-x:thread-1"
        assert progressed["title"] == "A stubbed finding"
        finished = json.loads(frames[2]["data"])
        assert finished["filed"] == 1
        assert finished["total_findings"] == 1

    def test_a_failing_patrol_emits_failed_with_the_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            raise RuntimeError("sqlite disk I/O error")

        monkeypatch.setattr("openstategraph.patrol.run_patrol", broken_patrol)

        async def scenario():
            from openstategraph.config_file import render_config_file, reset_active_config

            config_path = tmp_path / "openstategraph.yaml"
            config_path.write_text(render_config_file(project_id="proj-x"))
            monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config_path))
            reset_active_config()

            workflows_root = tmp_path / "workflows"
            workflows_root.mkdir()
            app = create_app(graph_factory=lambda _m: None, workflows_root=workflows_root)
            surface = _Surface(app)
            await surface.opened()

            await _call_once(app, "/api/kanban/patrol/run")

            frames = await surface.next_frames(2, timeout=REAL_PATROL_FRAME_CEILING)
            await surface.hang_up()
            reset_active_config()
            return frames

        frames = asyncio.run(scenario())
        kinds = [json.loads(frame["data"])["kind"] for frame in frames]
        assert kinds == ["started", "failed"]
        assert "sqlite disk I/O error" in json.loads(frames[1]["data"])["reason"]

    def test_a_patrol_still_running_when_the_response_returns_still_finishes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ordering `stable-beta-public/32` actually turned on, forced.

        The two cases above stub an *instant* patrol, so whether the background
        task outlives the `202` is decided by scheduling — green on a fast
        machine, red on a loaded one, and no wall-clock ceiling can make that
        determinate. Here the patrol does not return until the test says so,
        **after** the response has come back. Every frame therefore has to be
        published by a task that outlived its own response, which is the
        promise `kanban-patrol/07` makes and the one the old test transport
        quietly broke: run it through a per-request `TestClient` portal and it
        loses `finished` every single time.
        """
        released = threading.Event()

        def slow_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            # A bounded wait, never an unbounded one: a broken run must fail
            # this test, not hang the suite.
            released.wait(timeout=REAL_PATROL_FRAME_CEILING)
            if on_card_filed is not None:
                on_card_filed("proj-x:thread-1", "A finding filed after the response")
            return PatrolResult(filed=["proj-x:thread-1"], skipped=[], total_findings=1)

        monkeypatch.setattr("openstategraph.patrol.run_patrol", slow_patrol)

        async def scenario():
            from openstategraph.config_file import render_config_file, reset_active_config

            config_path = tmp_path / "openstategraph.yaml"
            config_path.write_text(render_config_file(project_id="proj-x"))
            monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config_path))
            reset_active_config()

            workflows_root = tmp_path / "workflows"
            workflows_root.mkdir()
            app = create_app(graph_factory=lambda _m: None, workflows_root=workflows_root)
            surface = _Surface(app)
            await surface.opened()

            status = await _call_once(app, "/api/kanban/patrol/run")
            # The response is back and the patrol is provably still inside
            # `run_patrol` — nothing but `started` can have been published yet.
            started = await surface.next_frames(1, timeout=REAL_PATROL_FRAME_CEILING)
            released.set()
            rest = await surface.next_frames(2, timeout=REAL_PATROL_FRAME_CEILING)
            await surface.hang_up()
            reset_active_config()
            return status, started + rest

        status, frames = asyncio.run(scenario())
        assert status == 202
        assert [json.loads(frame["data"])["kind"] for frame in frames] == [
            "started",
            "progressed",
            "finished",
        ]
