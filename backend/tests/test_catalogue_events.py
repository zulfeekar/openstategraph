"""Live catalogue changes: the broadcaster, and the `/api/events` endpoint.

Two things under test, kept apart on purpose:

1. **The fan-out** (`catalogue_events.CatalogueBroadcaster`) — N subscribers,
   a bounded backlog, and the drop of a dead one. Pure asyncio, no HTTP.
2. **The seam** — that exactly the endpoints which *change* the catalogue
   emit, that a read emits nothing, that the frames are framed by the one
   framer, and that a disconnect leaves no subscriber, task or queue behind
   (the lifecycle discipline of `test_resource_lifecycle.py`).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.catalogue_events import (
    KEEPALIVE_SECONDS,
    CatalogueBroadcaster,
    CatalogueEvent,
)
from openstategraph.api.main import create_app


def _event(reason: str = "published", slug: str = "billing", visible: bool = True):
    return CatalogueEvent(reason=reason, slug=slug, surface_visible=visible)


async def _take(subscriber, count: int, *, timeout: float = 1.0) -> list:
    """The next `count` events from a subscriber, or fail rather than hang."""
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
            broadcaster = CatalogueBroadcaster()
            with broadcaster.subscribe() as a, broadcaster.subscribe() as b, broadcaster.subscribe() as c:
                assert broadcaster.subscriber_count == 3
                broadcaster.publish(_event(slug="one"))
                broadcaster.publish(_event(slug="two"))
                return [await _take(s, 2) for s in (a, b, c)]

        for received in asyncio.run(scenario()):
            assert [e.slug for e in received] == ["one", "two"]

    def test_the_event_carries_reason_slug_and_surface_visibility(self) -> None:
        async def scenario():
            broadcaster = CatalogueBroadcaster()
            with broadcaster.subscribe() as sub:
                broadcaster.publish(_event("unpublished", "billing", False))
                return (await _take(sub, 1))[0]

        event = asyncio.run(scenario())
        assert event.as_dict() == {
            "reason": "unpublished",
            "slug": "billing",
            "surface_visible": False,
        }

    def test_publishing_with_no_subscribers_is_a_no_op(self) -> None:
        CatalogueBroadcaster().publish(_event())

    def test_a_subscription_is_removed_when_its_block_ends(self) -> None:
        async def scenario() -> int:
            broadcaster = CatalogueBroadcaster()
            with broadcaster.subscribe():
                assert broadcaster.subscriber_count == 1
            return broadcaster.subscriber_count

        assert asyncio.run(scenario()) == 0

    def test_publish_is_safe_from_a_worker_thread(self) -> None:
        """Every mutating endpoint is a sync `def`, so FastAPI runs it in the
        threadpool — the publish path crosses threads on every real call."""

        async def scenario() -> list:
            broadcaster = CatalogueBroadcaster()
            with broadcaster.subscribe() as sub:
                await asyncio.to_thread(broadcaster.publish, _event(slug="offthread"))
                return await _take(sub, 1)

        assert [e.slug for e in asyncio.run(scenario())] == ["offthread"]


class TestABacklogIsBounded:
    def test_a_subscriber_that_never_reads_is_dropped(self) -> None:
        async def scenario() -> tuple[int, bool]:
            broadcaster = CatalogueBroadcaster(backlog_limit=4)
            with broadcaster.subscribe() as dead:
                for i in range(5):
                    broadcaster.publish(_event(slug=f"w{i}"))
                return broadcaster.subscriber_count, dead.overflowed

        count, overflowed = asyncio.run(scenario())
        assert (count, overflowed) == (0, True)

    def test_dropping_one_does_not_disturb_the_others(self) -> None:
        async def scenario():
            broadcaster = CatalogueBroadcaster(backlog_limit=2)
            with broadcaster.subscribe() as dead, broadcaster.subscribe() as alive:
                # `alive` keeps up; `dead` never reads a thing.
                drained = []
                for i in range(5):
                    broadcaster.publish(_event(slug=f"w{i}"))
                    drained.extend(await _take(alive, 1))
                return drained, dead.overflowed, alive.overflowed, broadcaster.subscriber_count

        drained, dead_overflowed, alive_overflowed, count = asyncio.run(scenario())
        assert [e.slug for e in drained] == ["w0", "w1", "w2", "w3", "w4"]
        assert dead_overflowed is True
        assert alive_overflowed is False
        assert count == 1

    def test_a_dropped_subscribers_stream_ends_rather_than_hanging(self) -> None:
        """The consumer must learn it was dropped — a stream that simply stops
        producing would leave the endpoint parked on a wait forever."""

        async def scenario() -> list:
            broadcaster = CatalogueBroadcaster(backlog_limit=1)
            with broadcaster.subscribe() as sub:
                broadcaster.publish(_event(slug="kept"))
                broadcaster.publish(_event(slug="overflows"))
                seen = []
                async for event in sub.events():
                    seen.append(event)
                return seen

        assert [e.slug for e in asyncio.run(asyncio.wait_for(scenario(), 1.0))] == ["kept"]


class TestIdleTicks:
    def test_an_idle_stream_yields_a_keepalive_tick(self) -> None:
        async def scenario() -> list:
            broadcaster = CatalogueBroadcaster()
            with broadcaster.subscribe() as sub:
                seen = []
                stream = sub.events(idle_timeout=0.01)
                for _ in range(2):
                    seen.append(await asyncio.wait_for(stream.__anext__(), 1.0))
                await stream.aclose()
                return seen

        assert asyncio.run(scenario()) == [None, None]

    def test_the_interval_is_under_the_tightest_common_proxy_timeout(self) -> None:
        # 30s is the tightest idle timeout in common infrastructure; a missed
        # tick must still land inside it.
        assert KEEPALIVE_SECONDS * 2 <= 30


class TestOnlyRealChangesEmit:
    """One emit per mutation, none on a read."""

    @pytest.fixture()
    def app_and_client(self, tmp_path):
        app = create_app(graph_factory=lambda _model: None, workflows_root=tmp_path)
        with TestClient(app) as client:
            yield app, client

    @pytest.fixture()
    def recorded(self, app_and_client):
        """Every event the app publishes, captured in order."""
        app, client = app_and_client
        seen: list[CatalogueEvent] = []
        broadcaster = app.state.services.events
        original = broadcaster.publish

        def recording(event: CatalogueEvent) -> None:
            seen.append(event)
            original(event)

        broadcaster.publish = recording  # type: ignore[method-assign]
        return client, seen

    def test_a_save_emits_exactly_one_saved_event(self, recorded) -> None:
        client, seen = recorded
        response = client.put(
            "/api/workflows/billing",
            json={"name": "Billing", "document": {"nodes": [], "edges": []}},
        )

        assert response.status_code == 200
        assert [(e.reason, e.slug, e.surface_visible) for e in seen] == [
            # Born a draft (ticket 04), so it is not on the customer surface.
            ("saved", "billing", False)
        ]

    def test_publish_and_unpublish_each_emit_one(self, recorded) -> None:
        client, seen = recorded
        client.put(
            "/api/workflows/billing",
            json={"name": "Billing", "document": {"nodes": [], "edges": []}},
        )
        seen.clear()

        client.post("/api/workflows/billing/publish", json={"published": True})
        client.post("/api/workflows/billing/publish", json={"published": False})

        assert [(e.reason, e.surface_visible) for e in seen] == [
            ("published", True),
            ("unpublished", False),
        ]

    def test_a_delete_emits_one_and_the_slug_is_no_longer_visible(self, recorded) -> None:
        client, seen = recorded
        client.put(
            "/api/workflows/billing",
            json={"name": "Billing", "document": {"nodes": [], "edges": []}},
        )
        client.post("/api/workflows/billing/publish", json={"published": True})
        seen.clear()

        assert client.delete("/api/workflows/billing").status_code == 204
        assert [(e.reason, e.slug, e.surface_visible) for e in seen] == [
            ("deleted", "billing", False)
        ]

    def test_reads_emit_nothing(self, recorded) -> None:
        client, seen = recorded
        client.put(
            "/api/workflows/billing",
            json={"name": "Billing", "document": {"nodes": [], "edges": []}},
        )
        seen.clear()

        client.get("/api/workflows")
        client.get("/api/workflows?surface=chat")
        client.get("/api/workflows/billing")
        client.get("/api/health")

        assert seen == []

    def test_a_failed_mutation_emits_nothing(self, recorded) -> None:
        """Nothing changed, so nothing is announced — the catalogue is not
        'possibly different', it is identical."""
        client, seen = recorded

        assert client.delete("/api/workflows/nope").status_code == 404
        assert client.post(
            "/api/workflows/nope/publish", json={"published": True}
        ).status_code == 404
        assert seen == []


class _Surface:
    """One open `/api/events` connection, driven through the raw ASGI interface.

    Not `TestClient`: Starlette's test transport runs the whole app to
    completion before it returns a response object, so it cannot hold an
    unbounded stream open — `client.stream("GET", "/api/events")` simply hangs.
    Driving ASGI directly is also what makes the disconnect testable at all,
    because the test transport's `receive()` never reports one: it waits for
    the response to complete and only then says `http.disconnect`.
    """

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
            self.headers = {
                k.decode().lower(): v.decode() for k, v in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                self._chunks.append(body.decode())

    async def next_frame(self, *, timeout: float = 2.0) -> dict[str, str]:
        """The next event frame, skipping keepalive comments."""
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

    async def opened(self, *, timeout: float = 2.0) -> None:
        """Wait until this connection is live and subscribed.

        Proof, not a sleep: the endpoint yields its `: connected` comment from
        *inside* the `with broadcaster.subscribe()` block, so the first body
        chunk arriving is the subscription existing.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        while self.status is None or not (self._chunks or self._buffer):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the stream never opened")
            await asyncio.sleep(0.005)

    async def hang_up(self) -> None:
        """What a closed browser tab does."""
        self._disconnect.set()
        await asyncio.wait_for(self.task, timeout=2.0)


def _scope(path: str = "/api/events") -> dict:
    return {
        "type": "http",
        # 2.4 is what uvicorn reports, and it matters: at <2.4 Starlette spawns
        # its own disconnect listener, which would race this harness for the one
        # `http.disconnect` message `receive()` ever produces.
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }


async def _settle_until(ready: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait for a cross-thread wakeup to land — for as long as it takes.

    This was `_settle()`: exactly five 5ms sleeps, 25ms total, used as proof
    that a disconnect had propagated *across threads*. A fixed budget for a
    cross-thread handoff is flaky by construction — it is either too long
    (every run pays it) or too short (a loaded CI box goes red for a
    scheduling delay), and on the machine it was written on it happened to be
    both correct and invisible (reviews-2026-08-14 ticket 10).

    Polling a predicate instead: a healthy run returns in one tick, and a
    machine under load gets as long as it needs. The assertion afterwards is
    unchanged, so a genuine failure still fails — it just takes 5s to say so
    rather than 25ms.
    """
    deadline = time.monotonic() + timeout
    while not ready() and time.monotonic() < deadline:
        await asyncio.sleep(0.005)


class TestTheEndpoint:
    def test_it_answers_as_an_event_stream(self, tmp_path) -> None:
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

    def test_a_change_arrives_framed_as_workflows_changed(self, tmp_path) -> None:
        async def scenario():
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            broadcaster = app.state.services.events
            surface = _Surface(app)
            await surface.opened()
            # The stream is open BEFORE the change — that is the whole point.
            broadcaster.publish(CatalogueEvent("published", "billing", True))
            frame = await surface.next_frame()
            await surface.hang_up()
            return frame

        frame = asyncio.run(scenario())
        assert frame["event"] == "workflows.changed"
        assert json.loads(frame["data"]) == {
            "reason": "published",
            "slug": "billing",
            "surface_visible": True,
        }

    def test_a_real_publish_reaches_an_open_stream(self, tmp_path) -> None:
        """End to end through the endpoints, from another thread — which is
        where FastAPI actually runs the sync mutating endpoints."""

        async def scenario():
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            client = TestClient(app)
            await asyncio.to_thread(
                client.put,
                "/api/workflows/billing",
                json={"name": "Billing", "document": {"nodes": [], "edges": []}},
            )
            surface = _Surface(app)
            await surface.opened()
            await asyncio.to_thread(
                client.post, "/api/workflows/billing/publish", json={"published": True}
            )
            frame = await surface.next_frame()
            await surface.hang_up()
            return frame

        payload = json.loads(asyncio.run(scenario())["data"])
        assert payload == {"reason": "published", "slug": "billing", "surface_visible": True}

    def test_two_surfaces_both_see_one_change(self, tmp_path) -> None:
        async def scenario():
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            broadcaster = app.state.services.events
            chat, editor = _Surface(app), _Surface(app)
            await chat.opened()
            await editor.opened()
            broadcaster.publish(CatalogueEvent("saved", "billing", False))
            frames = (await chat.next_frame(), await editor.next_frame())
            await chat.hang_up()
            await editor.hang_up()
            return frames

        first, second = asyncio.run(scenario())
        assert first == second
        assert first["event"] == "workflows.changed"


class TestTheConnectionCleansUpOnBothEnds:
    """The lifecycle discipline of `test_resource_lifecycle.py`, applied to a
    live connection: a subscriber that outlived its socket would be fed for the
    life of the process and would finally be dropped for *overflow* rather than
    for the reason it actually left — and a keepalive task, had one been
    spawned, would tick against a dead socket forever."""

    def test_a_disconnect_unsubscribes(self, tmp_path) -> None:
        async def scenario() -> tuple[int, int]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            broadcaster = app.state.services.events
            surface = _Surface(app)
            await surface.opened()
            during = broadcaster.subscriber_count
            await surface.hang_up()
            await _settle_until(lambda: broadcaster.subscriber_count == 0)
            return during, broadcaster.subscriber_count

        assert asyncio.run(scenario()) == (1, 0)

    def test_a_disconnect_leaves_no_task_behind(self, tmp_path) -> None:
        async def scenario() -> list[str]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            before = asyncio.all_tasks()
            surface = _Surface(app)
            await surface.opened()
            await surface.hang_up()

            def leaked() -> set[asyncio.Task[Any]]:
                return {
                    task
                    for task in asyncio.all_tasks() - before
                    if task is not asyncio.current_task()
                }

            # A cancelled-but-not-yet-reaped task reports as a leak on a loaded
            # machine, which is what the fixed 25ms budget used to gamble on.
            await _settle_until(lambda: not leaked())
            return [repr(task) for task in leaked()]

        assert asyncio.run(scenario()) == []

    def test_one_surface_leaving_does_not_disturb_another(self, tmp_path) -> None:
        async def scenario():
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            broadcaster = app.state.services.events
            leaving, staying = _Surface(app), _Surface(app)
            await leaving.opened()
            await staying.opened()
            await leaving.hang_up()
            await _settle_until(lambda: broadcaster.subscriber_count == 1)
            broadcaster.publish(CatalogueEvent("deleted", "billing", False))
            frame = await staying.next_frame()
            still_connected = broadcaster.subscriber_count
            await staying.hang_up()
            return still_connected, frame

        count, frame = asyncio.run(scenario())
        assert count == 1
        assert json.loads(frame["data"])["reason"] == "deleted"

    def test_a_dropped_subscriber_ends_its_connection(self, tmp_path) -> None:
        """Overflow is not a silent state: the endpoint's generator must end so
        the socket closes and `EventSource` reconnects (and refetches) rather
        than holding a connection nothing will ever write to again."""

        async def scenario() -> bool:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            broadcaster = app.state.services.events
            # A tiny bound, reached without needing 32 publishes.
            broadcaster._backlog_limit = 1  # noqa: SLF001 — the bound is the subject
            surface = _Surface(app)
            await surface.opened()
            for i in range(3):
                broadcaster.publish(CatalogueEvent("saved", f"w{i}", False))
            await asyncio.wait_for(surface.task, timeout=2.0)
            return broadcaster.subscriber_count == 0

        assert asyncio.run(scenario()) is True


def _wait_for(predicate, *, timeout: float = 2.0) -> None:
    """Poll a condition another thread reaches."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached in time")
