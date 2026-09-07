"""The board learns a card moved without anybody pressing Refresh —
`osg-agent-experience/36`.

The defect the owner hit live: a coding agent attends a card, reports red,
then green, then finished — three writes through `openstategraph kanban
stage` or `kanban_set_stage`, each one a *separate process* opening
`kanban.sqlite` and calling `kanban_store.set_stage`. The server that serves
the board is one more reader of that file and is told nothing, so an open
board showed yesterday until Refresh.

Three claims, and the middle one is the ticket:

1. **The digest moves for a write and not for a read.** A poll that fired on
   every read would publish a frame per board refetch, which is a refetch
   loop.
2. **A write from another process reaches a connected client.** Deliberately
   `subprocess`, not a second call in this one: an in-process write would
   have passed against a watcher that only listened to its own writes, which
   is exactly the bug — the patrol's own fan-out already does that and the
   board still went stale.
3. **Nothing is polled while nobody is connected.** The cost of this feature
   is one sqlite query per interval, and it must be paid only while a board
   is open.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph.api import kanban_events
from openstategraph.api.kanban_events import (
    KANBAN_EVENT,
    KANBAN_FRAME_FIELDS,
    KanbanChangeWatcher,
)
from openstategraph.api.main import create_app
from openstategraph.kanban_store import Stage, kanban_store_path
from kanban_by_path import store
from kanban_by_path import ensure_schema, file_card, list_cards, set_stage, store_digest

REPO_BACKEND = str(Path(__file__).resolve().parents[1])


def _file_one(db: Path, task_id: str = "idea-1") -> None:
    ensure_schema(db)
    file_card(
        db,
        task_id=task_id,
        board="proj",
        kind="idea",
        category="idea",
        title="a throwaway",
    )


def _attend_in_another_process(db: Path, task_id: str = "idea-1") -> None:
    """The real door an agent uses: a fresh interpreter, its own sqlite
    connection, `kanban_store.set_stage`. Nothing about this process."""
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "from openstategraph.kanban_sqlite import SqliteKanbanStore\n"
        "from openstategraph.kanban_store import Stage\n"
        "r = SqliteKanbanStore(Path(%r)).set_stage(%r, Stage.ATTENDED, actor='agent')\n"
        "assert r.ok, r.reason\n" % (REPO_BACKEND, str(db), task_id)
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


class TestTheDigest:
    def test_a_read_does_not_move_it(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        _file_one(db)
        before = store_digest(db)
        list_cards(db)
        list_cards(db)
        assert store_digest(db) == before

    def test_a_stage_write_moves_it(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        _file_one(db)
        before = store_digest(db)
        set_stage(db, "idea-1", Stage.ATTENDED, actor="agent")
        assert store_digest(db) != before

    def test_a_new_card_moves_it(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        _file_one(db)
        before = store_digest(db)
        _file_one(db, task_id="idea-2")
        assert store_digest(db) != before

    def test_a_store_that_does_not_exist_yet_still_has_one(self, tmp_path: Path) -> None:
        """Asking never creates anything (`kanban_store_path`'s own rule), and
        an absent store must not raise into a watcher loop."""
        assert store_digest(tmp_path / "nothing.sqlite") == store_digest(tmp_path / "nothing.sqlite")


class TestTheWatcher:
    def test_it_publishes_once_for_a_write_from_another_process(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        _file_one(db)

        async def scenario() -> list:
            watcher = KanbanChangeWatcher(lambda: store(db), interval=0.02)
            received: list = []
            async with watcher.subscribe() as subscriber:
                stream = subscriber.events(idle_timeout=0.02)

                async def pump() -> None:
                    async for event in stream:
                        if event is not None:
                            received.append(event)
                            return

                _attend_in_another_process(db)
                await asyncio.wait_for(pump(), timeout=3.0)
                # A second window of the same length, to prove the frame is
                # one per change rather than one per tick.
                await asyncio.sleep(0.2)
                await stream.aclose()
            return received

        received = asyncio.run(scenario())
        assert len(received) == 1
        assert received[0].as_dict()["digest"] == store_digest(db)

    def test_it_says_nothing_while_the_store_is_only_read(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        _file_one(db)

        async def scenario() -> int:
            watcher = KanbanChangeWatcher(lambda: store(db), interval=0.02)
            async with watcher.subscribe() as subscriber:
                for _ in range(10):
                    list_cards(db)
                    await asyncio.sleep(0.02)
                banked, _closed = subscriber._drain()
            return len(banked)

        assert asyncio.run(scenario()) == 0

    def test_it_polls_only_while_somebody_is_connected(self, tmp_path: Path) -> None:
        db = tmp_path / "kanban.sqlite"
        _file_one(db)

        async def scenario() -> tuple[bool, bool, bool]:
            watcher = KanbanChangeWatcher(lambda: store(db), interval=0.02)
            before = watcher.running
            async with watcher.subscribe():
                during = watcher.running
            await asyncio.sleep(0.05)
            return before, during, watcher.running

        before, during, after = asyncio.run(scenario())
        assert (before, during, after) == (False, True, False)

    def test_the_last_client_leaving_stops_it_and_the_next_starts_it_again(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "kanban.sqlite"
        _file_one(db)

        async def scenario() -> tuple[bool, bool, bool]:
            watcher = KanbanChangeWatcher(lambda: store(db), interval=0.02)
            async with watcher.subscribe():
                async with watcher.subscribe():
                    pass
                # One left, one still here: the poll must not have stopped.
                still_running = watcher.running
            await asyncio.sleep(0.05)
            stopped = watcher.running
            async with watcher.subscribe():
                restarted = watcher.running
            return still_running, stopped, restarted

        still_running, stopped, restarted = asyncio.run(scenario())
        assert (still_running, stopped, restarted) == (True, False, True)


def _scope(path: str) -> dict:
    return {
        "type": "http",
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


class _Surface:
    """One open `/api/kanban/events` connection over the raw ASGI interface —
    `test_patrol_events.py`'s own `_Surface`, aimed at the new stream."""

    def __init__(self, app, path: str) -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._chunks: list[str] = []
        self._buffer = ""
        self._disconnect = asyncio.Event()
        self.task = asyncio.ensure_future(app(_scope(path), self._receive, self._send))

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

    async def opened(self, *, timeout: float = 2.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while self.status is None or not (self._chunks or self._buffer):
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("the stream never opened")
            await asyncio.sleep(0.005)

    async def hang_up(self) -> None:
        self._disconnect.set()
        await asyncio.wait_for(self.task, timeout=2.0)


class TestTheEndpoint:
    PATH = "/api/kanban/events"

    def test_it_answers_as_an_event_stream(self, tmp_path: Path) -> None:
        async def scenario():
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app, self.PATH)
            await surface.opened()
            result = (surface.status, surface.headers.get("content-type", ""))
            await surface.hang_up()
            return result

        status, content_type = asyncio.run(scenario())
        assert status == 200
        assert content_type.startswith("text/event-stream")

    def test_an_agent_moving_a_card_reaches_an_open_board(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ticket, end to end. The board is an open SSE connection; the
        agent is another interpreter calling `set_stage`; nothing in this
        process tells the server anything."""
        monkeypatch.setattr(kanban_events, "POLL_INTERVAL_SECONDS", 0.02)
        db = kanban_store_path(tmp_path)
        _file_one(db)

        async def scenario() -> dict[str, str]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app, self.PATH)
            await surface.opened()
            await asyncio.get_running_loop().run_in_executor(None, _attend_in_another_process, db)
            frame = await surface.next_frame()
            await surface.hang_up()
            return frame

        frame = asyncio.run(scenario())
        assert frame["event"] == KANBAN_EVENT
        payload = json.loads(frame["data"])
        assert tuple(payload) == KANBAN_FRAME_FIELDS
