"""One long-lived connection per tab carries every live frame —
`osg-agent-experience/71`.

`69` measured the ceiling this is about. A browser allows **six concurrent
HTTP/1.1 connections per origin**, and an editor tab held two long-lived ones
(`/api/events` and `/api/kanban/patrol/events`) before `69` was written. A
third — the per-package watcher — saturated the budget at *two* tabs: the last
stream opened sat at `readyState 0` for minutes and ordinary `fetch` calls in
that tab stopped completing. So `69` shipped its endpoint and left the editor
not opening it.

The fix is not a fourth transport and not HTTP/2 (a deployment property this
project cannot assume). It is that `GET /api/events` carries **every** live
subject a surface asks for, on the one connection it already holds.

Four claims:

1. **One connection carries all four frame kinds.** Catalogue, patrol, kanban
   and this tab's package, distinguished by the SSE `event:` name each already
   had — no frame is renamed and no client learns a second wire format.
2. **An unasked subject costs nothing.** The extra subjects are opt-in query
   parameters, so a plain `GET /api/events` (which is what `/chat` opens) sees
   exactly what it saw before, and the two *polling* watchers do not run for a
   connection that never named them. That is the property `kanban_events.py`
   wrote down for itself and it survives the fold.
3. **A connection that named one slug is never handed another's traffic** —
   filtered server-side, as the per-slug endpoint already filtered it.
4. **The published contract names every frame the stream can carry**, derived
   from the one registry rather than typed here or in the route.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph.api import kanban_events, workflow_events
from openstategraph.api.broadcast import Broadcaster, Subscriber
from openstategraph.api.catalogue_events import CATALOGUE_EVENT, CatalogueEvent
from openstategraph.api.kanban_events import KANBAN_EVENT
from openstategraph.api.live_stream import LIVE_TOPICS, live_frame_fields, live_frame_name
from openstategraph.api.main import create_app
from openstategraph.api.patrol_events import PATROL_EVENT, PatrolEvent
from openstategraph.api.workflow_events import WORKFLOW_EVENT
from openstategraph.kanban_store import kanban_store_path
from kanban_by_path import ensure_schema, file_card

REPO_BACKEND = str(Path(__file__).resolve().parents[1])

SLUG = "one-stream-probe"


def _document(title: str) -> dict:
    return {
        "name": title,
        "nodes": [{"id": "in1", "type": "input", "position": {"x": 0, "y": 0}, "data": {}}],
        "edges": [],
    }


def _write(root: Path, slug: str, title: str) -> Path:
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "workflow.json"
    path.write_text(json.dumps(_document(title), indent=2), encoding="utf-8")
    return path


def _rewrite_in_another_process(path: Path, title: str) -> None:
    """The door the CLI and a coding agent use — `69`'s own helper."""
    code = (
        "import json, sys\n"
        "sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "p = Path(%r)\n"
        "d = json.loads(p.read_text())\n"
        "d['name'] = %r\n"
        "p.write_text(json.dumps(d, indent=2))\n" % (REPO_BACKEND, str(path), title)
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def _attend_in_another_process(db: Path, task_id: str) -> None:
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "from openstategraph.kanban_sqlite import SqliteKanbanStore\n"
        "from openstategraph.kanban_store import Stage\n"
        "r = SqliteKanbanStore(Path(%r)).set_stage(%r, Stage.ATTENDED, actor='agent')\n"
        "assert r.ok, r.reason\n" % (REPO_BACKEND, str(db), task_id)
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def _scope(path: str, query: str = "") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }


class _Surface:
    """One open SSE connection over the raw ASGI interface — `69`'s harness,
    aimed at the merged stream and carrying a query string."""

    def __init__(self, app, path: str, query: str = "") -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._chunks: list[str] = []
        self._buffer = ""
        self._disconnect = asyncio.Event()
        self.task = asyncio.ensure_future(app(_scope(path, query), self._receive, self._send))

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

    async def next_frame(self, *, timeout: float = 5.0) -> dict[str, str]:
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

    async def quiet_for(self, seconds: float) -> list[dict[str, str]]:
        seen: list[dict[str, str]] = []
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            try:
                seen.append(await self.next_frame(timeout=0.05))
            except AssertionError:
                pass
        return seen

    async def opened(self, *, timeout: float = 2.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while self.status is None or not (self._chunks or self._buffer):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the stream never opened")
            await asyncio.sleep(0.005)

    async def hang_up(self) -> None:
        self._disconnect.set()
        await asyncio.wait_for(self.task, timeout=2.0)


class TestOneConnectionCarriesEverything:
    def test_all_four_frame_kinds_arrive_on_one_stream(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ticket. One socket, four subjects, each frame still carrying the
        `event:` name its own endpoint gave it."""
        monkeypatch.setattr(workflow_events, "POLL_INTERVAL_SECONDS", 0.02)
        monkeypatch.setattr(kanban_events, "POLL_INTERVAL_SECONDS", 0.02)
        path = _write(tmp_path, SLUG, "One")
        db = kanban_store_path(tmp_path)
        ensure_schema(db)
        file_card(
            db,
            task_id="probe-1",
            board="proj",
            kind="idea",
            category="idea",
            title="a throwaway",
        )

        async def scenario() -> set[str]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app, "/api/events", f"patrol=1&kanban=1&slug={SLUG}")
            await surface.opened()
            services = app.state.services
            services.events.publish(
                CatalogueEvent(reason="saved", slug=SLUG, surface_visible=True)
            )
            services.patrol_events.publish(PatrolEvent(kind="started"))
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _rewrite_in_another_process, path, "Two")
            await loop.run_in_executor(None, _attend_in_another_process, db, "probe-1")
            seen: set[str] = set()
            deadline = loop.time() + 8.0
            while len(seen) < 4 and loop.time() < deadline:
                frame = await surface.next_frame(timeout=2.0)
                seen.add(frame["event"])
            await surface.hang_up()
            return seen

        assert asyncio.run(scenario()) == {
            CATALOGUE_EVENT,
            PATROL_EVENT,
            KANBAN_EVENT,
            WORKFLOW_EVENT,
        }

    def test_a_plain_connection_still_sees_only_the_catalogue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/chat` opens this endpoint with no parameters and must keep seeing
        exactly what it saw. An extra subject is asked for, never assumed."""
        monkeypatch.setattr(workflow_events, "POLL_INTERVAL_SECONDS", 0.02)
        monkeypatch.setattr(kanban_events, "POLL_INTERVAL_SECONDS", 0.02)
        path = _write(tmp_path, SLUG, "One")

        async def scenario() -> list[str]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app, "/api/events")
            await surface.opened()
            services = app.state.services
            services.patrol_events.publish(PatrolEvent(kind="started"))
            await asyncio.get_running_loop().run_in_executor(
                None, _rewrite_in_another_process, path, "Two"
            )
            services.events.publish(
                CatalogueEvent(reason="saved", slug=SLUG, surface_visible=True)
            )
            frames = await surface.quiet_for(0.4)
            await surface.hang_up()
            return [frame["event"] for frame in frames]

        assert asyncio.run(scenario()) == [CATALOGUE_EVENT]

    def test_an_unasked_watcher_never_polls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The property `kanban_events.py` wrote down for itself: the poll runs
        only while somebody is looking. Folding the frame onto a stream every
        tab holds must not turn that into a poll for the life of every tab."""
        monkeypatch.setattr(workflow_events, "POLL_INTERVAL_SECONDS", 0.02)
        monkeypatch.setattr(kanban_events, "POLL_INTERVAL_SECONDS", 0.02)
        _write(tmp_path, SLUG, "One")

        async def scenario() -> tuple[bool, bool, tuple[str, ...]]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app, "/api/events")
            await surface.opened()
            services = app.state.services
            await asyncio.sleep(0.1)
            standing = (
                services.kanban_events.running,
                services.workflow_events.running,
                services.workflow_events.watched_slugs,
            )
            await surface.hang_up()
            return standing

        assert asyncio.run(scenario()) == (False, False, ())

    def test_a_connection_that_named_one_slug_is_not_handed_another(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two tabs on two packages share one watcher and one broadcaster, so
        every frame reaches every generator. Filtered where `69` filtered it."""
        monkeypatch.setattr(workflow_events, "POLL_INTERVAL_SECONDS", 0.02)
        mine = _write(tmp_path, SLUG, "One")
        theirs = _write(tmp_path, "somebody-else", "Other")

        async def scenario() -> list[dict[str, str]]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            watching_theirs = _Surface(app, "/api/events", "slug=somebody-else")
            await watching_theirs.opened()
            surface = _Surface(app, "/api/events", f"slug={SLUG}")
            await surface.opened()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _rewrite_in_another_process, theirs, "Other 2")
            await loop.run_in_executor(None, _rewrite_in_another_process, mine, "Two")
            frames = await surface.quiet_for(0.6)
            await surface.hang_up()
            await watching_theirs.hang_up()
            return frames

        frames = asyncio.run(scenario())
        assert [frame["event"] for frame in frames] == [WORKFLOW_EVENT]
        assert json.loads(frames[0]["data"])["slug"] == SLUG


class TestTheSharedSubscriber:
    def test_letting_go_of_one_fan_out_does_not_end_the_others(self) -> None:
        """The property `attach` exists for. One connection is registered with
        four broadcasters, so a detach that closed the subscriber would end
        every other subject mid-sentence — which is why `attach` is not
        `subscribe` with the construction hoisted out."""

        async def scenario() -> tuple[bool, list[str]]:
            first: Broadcaster[str] = Broadcaster()
            second: Broadcaster[str] = Broadcaster()
            subscriber: Subscriber[str] = Subscriber(asyncio.get_running_loop(), 8)
            with second.attach(subscriber):
                with first.attach(subscriber):
                    first.publish("from the first")
                # The first fan-out has let go. If letting go had closed the
                # subscriber, this second subject would reach nobody.
                second.publish("from the second")
                banked, closed = subscriber._drain()
            return closed, banked

        assert asyncio.run(scenario()) == (False, ["from the first", "from the second"])

    def test_a_payload_no_topic_claims_never_reaches_a_client(self) -> None:
        """One connection now carries four kinds of object, so the framer is
        the only thing standing between a new fan-out and a frame arriving
        under a name no document mentions. It raises rather than guesses."""
        with pytest.raises(TypeError):
            live_frame_name(object())


class TestTheContract:
    def test_the_registry_is_the_one_place_a_frame_name_is_written(self) -> None:
        """Four topics, each naming the event it carries and deriving its
        fields from the dataclass that serialises it — never a second tuple
        somebody keeps in step by attention (`kanban-patrol/31` and `/34`)."""
        assert live_frame_name(CatalogueEvent(reason="saved", slug="", surface_visible=False)) == (
            CATALOGUE_EVENT
        )
        assert live_frame_name(PatrolEvent(kind="started")) == PATROL_EVENT
        assert set(live_frame_fields()) == {
            CATALOGUE_EVENT,
            PATROL_EVENT,
            KANBAN_EVENT,
            WORKFLOW_EVENT,
        }
        for topic in LIVE_TOPICS:
            assert live_frame_fields()[topic.event] == topic.fields

    def test_the_published_contract_names_every_frame_the_stream_can_carry(self) -> None:
        """`docs/openapi.json` is generated, so this reads the app's own
        schema rather than the committed artifact — the artifact's own drift
        gate is a different test."""
        app = create_app(graph_factory=lambda _m: None)
        description = app.openapi()["paths"]["/api/events"]["get"]["responses"]["200"][
            "description"
        ]
        for topic in LIVE_TOPICS:
            assert f"`{topic.event}`" in description
