"""Every writer of a `workflow.json` reaches every open tab —
`osg-agent-experience/69`.

The owner's question, 2026-09-05, after `68`: *"a user opens three tabs on the
same workflow, how does each get the latest changes?"* Four kinds of writer —
an editor tab, a second editor tab, `openstategraph` on the command line, a
coding agent through the MCP server — and until this stream only the first of
them told anybody.

Four claims, and the third is the ticket:

1. **The revision on the wire is the one the 409 already checks.** A frame's
   `digest` is the string a save quotes as `base_digest`; if it were a second
   stamp, a tab could refresh to a revision the save path does not recognise.
2. **A frame is one per change, not one per tick**, and a read moves nothing.
3. **A write from another process reaches a connected tab.** Deliberately
   `subprocess`, not a second call in this one: an in-process write would pass
   against a watcher that only hears its own writes, which is exactly the
   defect — `catalogue_events` already does that and a second tab still went
   stale.
4. **Nothing is polled while nobody is connected**, and a package nobody has
   subscribed to is never read at all.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph.api import workflow_events
from openstategraph.api.main import create_app
from openstategraph.api.workflow_events import (
    WORKFLOW_EVENT,
    WORKFLOW_FRAME_FIELDS,
    WorkflowChangedEvent,
    WorkflowChangeWatcher,
    digest_reader,
)
from openstategraph.api.workflow_store import WorkflowStore, package_digest

REPO_BACKEND = str(Path(__file__).resolve().parents[1])

SLUG = "tabs-probe"


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
    """The door the CLI and a coding agent use: a fresh interpreter writing
    the file. Nothing about the server process, which is the point."""
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


class TestTheRevision:
    def test_it_is_the_digest_the_save_path_already_checks(self, tmp_path: Path) -> None:
        """One seam, not a second counter. `describe(slug).digest` is what a
        client quotes back as `base_digest`, and it is what the reader behind
        the watcher answers — so a tab that refreshes on a frame holds a
        revision the 409 recognises."""
        path = _write(tmp_path, SLUG, "One")
        store = WorkflowStore(root=tmp_path)
        row = store.describe(SLUG)
        assert row is not None
        read = digest_reader(store.directory_for)
        assert read(SLUG) == row.digest == package_digest(path)

    def test_a_slug_with_no_package_reads_as_nothing_rather_than_raising(
        self, tmp_path: Path
    ) -> None:
        """A tab may be watching a package that is about to be created, or one
        just deleted. Neither may raise into the poll loop."""
        read = digest_reader(WorkflowStore(root=tmp_path).directory_for)
        assert read("never-existed") == ""
        assert read("../escape") == ""

    def test_the_frame_fields_are_derived_from_the_event(self) -> None:
        assert WORKFLOW_FRAME_FIELDS == ("slug", "digest")
        assert set(WorkflowChangedEvent(slug="a", digest="b").as_dict()) == set(
            WORKFLOW_FRAME_FIELDS
        )


class TestTheWatcher:
    def test_it_publishes_once_for_a_write_from_another_process(self, tmp_path: Path) -> None:
        path = _write(tmp_path, SLUG, "One")
        read = digest_reader(WorkflowStore(root=tmp_path).directory_for)

        async def scenario() -> list:
            watcher = WorkflowChangeWatcher(read, interval=0.02)
            received: list = []
            async with watcher.subscribe(SLUG) as subscriber:
                stream = subscriber.events(idle_timeout=0.02)

                async def pump() -> None:
                    async for event in stream:
                        if event is not None:
                            received.append(event)
                            return

                _rewrite_in_another_process(path, "Two")
                await asyncio.wait_for(pump(), timeout=3.0)
                # A second window of the same length, to prove the frame is
                # one per change rather than one per tick.
                await asyncio.sleep(0.2)
                await stream.aclose()
            return received

        received = asyncio.run(scenario())
        assert len(received) == 1
        assert received[0].slug == SLUG
        assert received[0].digest == package_digest(path)

    def test_it_says_nothing_while_the_file_is_only_read(self, tmp_path: Path) -> None:
        path = _write(tmp_path, SLUG, "One")
        read = digest_reader(WorkflowStore(root=tmp_path).directory_for)

        async def scenario() -> int:
            watcher = WorkflowChangeWatcher(read, interval=0.02)
            async with watcher.subscribe(SLUG) as subscriber:
                for _ in range(10):
                    path.read_text()
                    await asyncio.sleep(0.02)
                banked, _closed = subscriber._drain()
            return len(banked)

        assert asyncio.run(scenario()) == 0

    def test_it_polls_only_while_somebody_is_connected(self, tmp_path: Path) -> None:
        _write(tmp_path, SLUG, "One")
        read = digest_reader(WorkflowStore(root=tmp_path).directory_for)

        async def scenario() -> tuple[bool, bool, bool]:
            watcher = WorkflowChangeWatcher(read, interval=0.02)
            before = watcher.running
            async with watcher.subscribe(SLUG):
                during = watcher.running
            await asyncio.sleep(0.05)
            return before, during, watcher.running

        assert asyncio.run(scenario()) == (False, True, False)

    def test_three_tabs_on_one_workflow_hold_one_poll_between_them(
        self, tmp_path: Path
    ) -> None:
        """The ticket's own title, at the watcher. Three subscriptions to one
        slug is one watched package and one poll task; the last one leaving is
        what stops it."""
        _write(tmp_path, SLUG, "One")
        read = digest_reader(WorkflowStore(root=tmp_path).directory_for)

        async def scenario() -> tuple:
            watcher = WorkflowChangeWatcher(read, interval=0.02)
            async with watcher.subscribe(SLUG):
                async with watcher.subscribe(SLUG):
                    async with watcher.subscribe(SLUG):
                        three = (watcher.watched_slugs, watcher.subscriber_count)
                one_left = watcher.running
            await asyncio.sleep(0.05)
            return three, one_left, watcher.running, watcher.watched_slugs

        three, one_left, after, watched_after = asyncio.run(scenario())
        assert three == ((SLUG,), 3)
        assert (one_left, after, watched_after) == (True, False, ())

    def test_a_package_nobody_watches_is_never_read(self, tmp_path: Path) -> None:
        """The cost is bounded by what is open, not by what is on disk. A root
        holding a hundred packages must not be walked because one tab is."""
        _write(tmp_path, SLUG, "One")
        _write(tmp_path, "someone-elses", "Other")
        asked: list[str] = []
        real = digest_reader(WorkflowStore(root=tmp_path).directory_for)

        def read(slug: str) -> str:
            asked.append(slug)
            return real(slug)

        async def scenario() -> None:
            watcher = WorkflowChangeWatcher(read, interval=0.02)
            async with watcher.subscribe(SLUG):
                await asyncio.sleep(0.1)

        asyncio.run(scenario())
        assert asked
        assert set(asked) == {SLUG}


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
    """One open SSE connection over the raw ASGI interface —
    `test_the_board_learns_a_card_moved.py`'s `_Surface`, aimed at this stream."""

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

    async def quiet_for(self, seconds: float) -> list[dict[str, str]]:
        """Every frame that arrives in a window — for proving none does."""
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


class TestTheEndpoint:
    def test_it_answers_as_an_event_stream(self, tmp_path: Path) -> None:
        _write(tmp_path, SLUG, "One")

        async def scenario():
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app, f"/api/workflows/{SLUG}/events")
            await surface.opened()
            result = (surface.status, surface.headers.get("content-type", ""))
            await surface.hang_up()
            return result

        status, content_type = asyncio.run(scenario())
        assert status == 200
        assert content_type.startswith("text/event-stream")

    def test_a_cli_rewrite_reaches_an_open_tab(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ticket, end to end. The tab is an open SSE connection; the
        writer is another interpreter rewriting `workflow.json`; nothing in
        this process tells the server anything."""
        monkeypatch.setattr(workflow_events, "POLL_INTERVAL_SECONDS", 0.02)
        path = _write(tmp_path, SLUG, "One")

        async def scenario() -> dict[str, str]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            surface = _Surface(app, f"/api/workflows/{SLUG}/events")
            await surface.opened()
            await asyncio.get_running_loop().run_in_executor(
                None, _rewrite_in_another_process, path, "Two"
            )
            frame = await surface.next_frame()
            await surface.hang_up()
            return frame

        frame = asyncio.run(scenario())
        assert frame["event"] == WORKFLOW_EVENT
        payload = json.loads(frame["data"])
        assert payload == {"slug": SLUG, "digest": package_digest(path)}

    def test_a_tab_is_not_told_about_a_package_it_is_not_editing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One broadcaster serves every watched package. A tab that asked
        about one slug must not be woken by traffic about another — which is
        exactly what a fifth `CatalogueEvent.reason` would have done."""
        monkeypatch.setattr(workflow_events, "POLL_INTERVAL_SECONDS", 0.02)
        _write(tmp_path, SLUG, "One")
        other = _write(tmp_path, "someone-elses", "Other")

        async def scenario() -> tuple[list, dict[str, str]]:
            app = create_app(graph_factory=lambda _m: None, workflows_root=tmp_path)
            mine = _Surface(app, f"/api/workflows/{SLUG}/events")
            theirs = _Surface(app, "/api/workflows/someone-elses/events")
            await mine.opened()
            await theirs.opened()
            await asyncio.get_running_loop().run_in_executor(
                None, _rewrite_in_another_process, other, "Rewritten"
            )
            told = await theirs.next_frame()
            silence = await mine.quiet_for(0.3)
            await mine.hang_up()
            await theirs.hang_up()
            return silence, told

        silence, told = asyncio.run(scenario())
        assert json.loads(told["data"])["slug"] == "someone-elses"
        assert silence == []
