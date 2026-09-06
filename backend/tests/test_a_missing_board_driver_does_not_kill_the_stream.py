"""A driver that is not installed must not kill the live stream —
`team-board-and-gap-reports/18`.

**The owner's shape, 2026-09-06.** An upgrade to `rc16` carried
`[server,ollama,mssql]` — the line an orchestrator handed over, which lacked
`postgres` — with `OPENSTATEGRAPH_KANBAN_URL` set at a real Postgres board.
The editor started, `GET /api/health` said `ok`, and then every
`GET /api/events?patrol=1&kanban=1` died with a two-hundred-line traceback
ending in

    ImportError: OPENSTATEGRAPH_KANBAN_URL is set, but psycopg is not
    installed — uv tool install --force … 'openstategraph[...]'

once per reconnect, because `KanbanChangeWatcher._start` opens the store
*inside* the stream and the `ImportError` escaped as an ASGI exception.

The sentence is right — it names the variable and a command that can be
carried out (`osg-agent-experience/79`). Everything about the delivery was
wrong: a traceback for the owner, a 500 for the tab, and nothing at all on
`/api/health`, which had just answered that a team board *was* configured.

So the driver is made genuinely absent here (three `None`s in `sys.modules`,
which is what the import system itself does to a module that failed) rather
than by patching the function that raises — a test that stubbed
`postgres.open_pool` would pass against a fix that never touches the real
import path.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest

from openstategraph.api.main import create_app
from openstategraph.api.team_board import TeamBoard
from openstategraph.kanban_store import KANBAN_URL_ENV

#: A board nobody can reach, which is not the point: the driver is gone, so
#: nothing here ever opens a socket. The password is fake and is the reason
#: the recorded sentence is checked for it never appearing.
UNREACHABLE = "postgresql://board:hunter2@db.invalid:5432/cards"


@pytest.fixture
def no_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    """`import psycopg` fails, exactly as it does on an install without the
    extra. `psycopg.rows` too: `from psycopg.rows import dict_row` consults
    the submodule's own `sys.modules` entry first, so blocking the parent
    alone leaves an already-imported submodule importable."""
    for name in ("psycopg", "psycopg.rows", "psycopg_pool"):
        monkeypatch.setitem(sys.modules, name, None)


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


class _Stream:
    """One open SSE connection over the raw ASGI interface.

    The same harness `test_one_stream_per_tab.py` uses, kept here rather than
    imported from it: what this file asserts is that the connection *opens at
    all*, which needs the exception to surface as a failed task rather than be
    swallowed by a client library's retry.
    """

    def __init__(self, app, path: str, query: str = "") -> None:
        self.status: int | None = None
        self.body = ""
        self._disconnect = asyncio.Event()
        self.task = asyncio.ensure_future(app(_scope(path, query), self._receive, self._send))

    async def _receive(self) -> dict:
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
        elif message["type"] == "http.response.body":
            self.body += message.get("body", b"").decode()

    async def opened(self, *, timeout: float = 2.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self.status is None or not self.body:
            if self.task.done() and self.task.exception() is not None:
                raise AssertionError(
                    f"the stream raised instead of opening: {self.task.exception()!r}"
                )
            if loop.time() > deadline:
                raise AssertionError("the stream never opened")
            await asyncio.sleep(0.005)

    async def hang_up(self) -> None:
        self._disconnect.set()
        await asyncio.wait_for(self.task, timeout=2.0)


def _connect(app, query: str) -> str:
    async def scenario() -> str:
        stream = _Stream(app, "/api/events", query)
        await stream.opened()
        assert stream.status == 200
        await stream.hang_up()
        return stream.body

    return asyncio.run(scenario())


class TestTheOwnersReconnect:
    """URL set, driver missing — the exact shape that produced the traceback."""

    def test_the_live_stream_opens_and_carries_frames(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_driver: None
    ) -> None:
        monkeypatch.setenv(KANBAN_URL_ENV, UNREACHABLE)
        app = create_app(workflows_root=tmp_path)
        assert ": connected" in _connect(app, "patrol=1&kanban=1")

    def test_reconnecting_raises_nothing_the_second_time_either(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_driver: None
    ) -> None:
        # The defect was *per reconnect*: an editor tab retries an SSE
        # connection forever, so one traceback is really one every few seconds.
        monkeypatch.setenv(KANBAN_URL_ENV, UNREACHABLE)
        app = create_app(workflows_root=tmp_path)
        for _ in range(3):
            assert ": connected" in _connect(app, "patrol=1&kanban=1")

    def test_health_says_which_board_and_why_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_driver: None
    ) -> None:
        from fastapi.testclient import TestClient

        monkeypatch.setenv(KANBAN_URL_ENV, UNREACHABLE)
        payload = TestClient(create_app(workflows_root=tmp_path)).get("/api/health").json()
        assert payload["ok"] is True
        assert payload["team_board_configured"] is True
        assert payload["team_board_env"] == KANBAN_URL_ENV
        error = payload["team_board_error"]
        assert KANBAN_URL_ENV in error
        assert "psycopg is not installed" in error

    def test_the_recorded_sentence_never_carries_the_password(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_driver: None
    ) -> None:
        # The URL holds credentials and this sentence is published to any
        # browser that can reach the port. `team_board_env` is the name, and
        # the name is all either field may ever carry.
        from fastapi.testclient import TestClient

        monkeypatch.setenv(KANBAN_URL_ENV, UNREACHABLE)
        payload = TestClient(create_app(workflows_root=tmp_path)).get("/api/health").json()
        assert "hunter2" not in payload["team_board_error"]

    def test_the_install_command_is_on_a_line_of_its_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_driver: None
    ) -> None:
        """`osg-agent-experience/83`'s rule, on a surface it did not own: a
        command a reader has to paste cannot share a line with prose that
        wraps around it."""
        from fastapi.testclient import TestClient

        from openstategraph.install_hint import install_hint

        monkeypatch.setenv(KANBAN_URL_ENV, UNREACHABLE)
        payload = TestClient(create_app(workflows_root=tmp_path)).get("/api/health").json()
        lines = payload["team_board_error"].splitlines()
        assert install_hint("postgres") in lines

    def test_the_local_board_still_answers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_driver: None
    ) -> None:
        """"The process keeps the local board" — the whole of the fallback.

        A tab that cannot reach the shared board must still show the local
        one; a 500 on every card read would be the same outage one layer up.
        """
        from fastapi.testclient import TestClient

        monkeypatch.setenv(KANBAN_URL_ENV, UNREACHABLE)
        response = TestClient(create_app(workflows_root=tmp_path)).get("/api/kanban/cards")
        assert response.status_code == 200
        assert response.json() == []

    def test_one_log_line_at_startup_and_none_per_request(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        no_driver: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from fastapi.testclient import TestClient

        monkeypatch.setenv(KANBAN_URL_ENV, UNREACHABLE)
        with caplog.at_level(logging.WARNING, logger="openstategraph.api.team_board"):
            client = TestClient(create_app(workflows_root=tmp_path))
            mine = [r for r in caplog.records if r.name == "openstategraph.api.team_board"]
            at_startup = len(mine)
            for _ in range(3):
                client.get("/api/health")
                client.get("/api/kanban/cards")
            after = [r for r in caplog.records if r.name == "openstategraph.api.team_board"]
        assert at_startup == 1
        assert len(after) == 1


class TestABoardThatOpens:
    """Nothing above is bought at the price of the working case."""

    def test_a_reachable_board_records_no_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        monkeypatch.setenv(KANBAN_URL_ENV, f"sqlite:///{tmp_path / 'shared.sqlite'}")
        payload = TestClient(create_app(workflows_root=tmp_path)).get("/api/health").json()
        assert payload["team_board_configured"] is True
        assert payload["team_board_error"] is None

    def test_an_unconfigured_process_records_nothing_at_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KANBAN_URL_ENV, raising=False)
        from fastapi.testclient import TestClient

        payload = TestClient(create_app(workflows_root=tmp_path)).get("/api/health").json()
        assert payload["team_board_configured"] is False
        assert payload["team_board_error"] is None


class _Counting:
    def __init__(self, answer) -> None:
        self.calls = 0
        self._answer = answer

    def __call__(self):
        self.calls += 1
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


class TestTheDoorItself:
    """`TeamBoard` on its own — the unit the two behaviours above come from."""

    def test_the_configured_board_is_opened_once_however_often_it_is_asked(self) -> None:
        shared, local = _Counting("shared"), _Counting("local")
        board = TeamBoard(shared, local, is_configured=lambda: True)
        board.probe()
        board.probe()
        assert board.error is None
        assert shared.calls == 1  # the probe's own open, and no second one

    def test_a_failure_is_recorded_rather_than_raised(self) -> None:
        shared = _Counting(ImportError("no driver here"))
        local = _Counting("local")
        board = TeamBoard(shared, local, is_configured=lambda: True)
        assert board.probe() == "no driver here"
        assert board.open() == "local"
        assert shared.calls == 1

    def test_an_unconfigured_process_probes_nothing(self) -> None:
        # And still opens through the ordinary door, which is the whole point
        # of the fallback being a *fallback*: with nothing configured,
        # `open_kanban_store` already answers with this laptop's own file, so
        # a process that reached for `open_local` here would be a second
        # spelling of one branch.
        shared, local = _Counting("shared"), _Counting("local")
        board = TeamBoard(shared, local, is_configured=lambda: False)
        assert board.probe() is None
        assert board.error is None
        assert shared.calls == 0
        assert board.open() == "shared"
        assert local.calls == 0

    def test_a_door_nobody_probed_probes_itself_rather_than_raising(self) -> None:
        # The safety net under "called once at startup": a transport that
        # forgets to probe must still not hand an ImportError to a stream.
        shared = _Counting(ImportError("no driver here"))
        board = TeamBoard(shared, _Counting("local"), is_configured=lambda: True)
        assert board.open() == "local"
        assert board.error == "no driver here"
