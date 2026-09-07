"""The team tab stops saying "not configured" once something is configured —
`team-board-and-gap-reports/04`.

`boardTabState('osgEngineering')` returned a hardcoded `unavailable` carrying
the sentence *"Nothing points at one yet"*. After `02` and `03` something can
point at one, and a tab that goes on saying otherwise is a false statement on
the surface a maintainer looks at.

Three facts have to reach the browser, and this file pins each of them at the
layer it lives in.

## One: whether a team store is configured, by the variable's **name**

`GET /api/health` already answers exactly this shape of question about
providers — `model_configured` is "does the environment name credentials",
never "is the vendor reachable", and it reads environment variables and opens
no socket. The team board's fact is the same fact about a different variable,
so it joins that response rather than starting a second status door.

**The name, never the value.** `OPENSTATEGRAPH_KANBAN_URL` holds a Postgres
URI with a password in it. What the editor needs is a boolean and a variable a
maintainer can be told to set; what it must never receive is the URI. That is
`CLAUDE.md`'s Ollama rule — *never restore a spec that reaches a vendor without
naming a variable someone can set, see and revoke* — applied to a surface.

## Two: which board a read is about

The owner's decision of 2026-09-05 is *one table, a `board` column*, so the two
tabs are two boards **in one store**, not two stores. `GET /api/kanban/cards`
therefore takes `?board=`, defaulting to the tab that has always been there, and
filters on the column. Nothing about which store answers changes: that is
`open_kanban_store`'s job and `02` settled it.

## Three: the live stream is unchanged, and that is the assertion

`KanbanChangeWatcher` already asks `IKanbanStore.store_digest()` rather than
stat-ing a file (`02`), and `PostgresKanbanStore` already answers it with
`count(*)`/`max(updated_at)` (`03`). So the team board rides the stream that
exists, on the connection that exists — the frame, the poll lifetime and the
refetch are the ones `osg-agent-experience/36` shipped and `71` folded onto one
socket. The tests below exist to make "unchanged" a claim that can fail: a
future edit that gives the team board its own watcher, its own frame or its own
connection turns one of them red.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.kanban_store import (
    BOARD_IDS,
    KANBAN_URL_ENV,
    LOCAL_BOARD,
    TEAM_BOARD,
    open_kanban_store,
    team_board_status,
)

BOARD_TABS_TS = (
    Path(__file__).resolve().parents[2] / "src" / "view" / "board" / "boardTabs.ts"
)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    made = tmp_path / "workflows"
    made.mkdir()
    return made


@pytest.fixture()
def client(root: Path) -> Iterator[TestClient]:
    with TestClient(create_app(workflows_root=root)) as test_client:
        yield test_client


def _file(store, task_id: str, board: str) -> None:
    store.file_card(
        task_id=task_id,
        board=board,
        kind="bug",
        category="bug",
        title=f"a finding on {board}",
    )


class TestTheVariableIsNamedAndNeverRead:
    """The status the editor is handed: a boolean and a variable name."""

    def test_unset_is_not_configured_and_still_names_the_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KANBAN_URL_ENV, raising=False)
        status = team_board_status()
        assert status.configured is False
        # The whole point of the sentence a maintainer reads: it must be able
        # to say *what to set*, which means the name travels even when nothing
        # is set. A tab that says "not configured" and stops is the state
        # today; this is the half that makes it actionable.
        assert status.env_var == KANBAN_URL_ENV

    def test_set_is_configured(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv(KANBAN_URL_ENV, f"sqlite:///{tmp_path / 'team.sqlite'}")
        assert team_board_status().configured is True

    def test_whitespace_is_not_a_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(KANBAN_URL_ENV, "   ")
        assert team_board_status().configured is False

    def test_health_publishes_it_and_publishes_no_url(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        secret = f"postgresql://board:hunter2@db.example/{tmp_path.name}"
        monkeypatch.setenv(KANBAN_URL_ENV, secret)
        body = client.get("/api/health").text
        payload = client.get("/api/health").json()
        assert payload["team_board_configured"] is True
        assert payload["team_board_env"] == KANBAN_URL_ENV
        # Not "the field does not contain it" — *nothing in the response* does.
        # A password reaching the browser through a status endpoint would be
        # this ticket shipping a worse defect than the one it fixes.
        assert "hunter2" not in body
        assert secret not in body

    def test_health_says_so_when_nothing_is_configured(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KANBAN_URL_ENV, raising=False)
        payload = client.get("/api/health").json()
        assert payload["team_board_configured"] is False
        assert payload["team_board_env"] == KANBAN_URL_ENV


class TestOneTableTwoBoards:
    """`?board=` reads the column, and the column is the whole difference."""

    def test_the_default_is_the_tab_that_was_always_there(
        self, client: TestClient, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KANBAN_URL_ENV, raising=False)
        store = open_kanban_store(root)
        _file(store, "local-1", LOCAL_BOARD)
        rows = client.get("/api/kanban/cards").json()
        assert [row["task_id"] for row in rows] == ["local-1"]

    def test_each_board_sees_only_its_own(
        self, client: TestClient, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KANBAN_URL_ENV, raising=False)
        store = open_kanban_store(root)
        _file(store, "local-1", LOCAL_BOARD)
        _file(store, "team-1", TEAM_BOARD)

        local = client.get("/api/kanban/cards", params={"board": LOCAL_BOARD}).json()
        team = client.get("/api/kanban/cards", params={"board": TEAM_BOARD}).json()

        assert [row["task_id"] for row in local] == ["local-1"]
        assert [row["task_id"] for row in team] == ["team-1"]
        # The row shape does not change with the board — one spelling of a
        # card, `kanban-patrol/16`.
        assert set(local[0]) == set(team[0])

    def test_a_board_nothing_has_been_filed_on_is_empty_not_an_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(KANBAN_URL_ENV, raising=False)
        response = client.get("/api/kanban/cards", params={"board": TEAM_BOARD})
        assert response.status_code == 200
        assert response.json() == []

    def test_a_board_this_product_does_not_have_is_refused_by_name(
        self, client: TestClient
    ) -> None:
        # `github` is a tab and not a board. A read for it must not silently
        # answer with the local board's cards, which is the "quietly fell back"
        # failure `open_kanban_store` already refuses on its own axis.
        response = client.get("/api/kanban/cards", params={"board": "github"})
        assert response.status_code == 400
        assert "github" in response.json()["detail"]
        assert LOCAL_BOARD in response.json()["detail"]


class TestTheTabIdsAndTheColumnAreOneVocabulary:
    """Two spellings of one vocabulary in two languages — the pin
    `BOARD_COLUMNS` already carries, one axis along."""

    def _tab_ids(self) -> tuple[str, ...]:
        source = BOARD_TABS_TS.read_text(encoding="utf-8")
        match = re.search(r"export type BoardTabId =([^;]+);", source)
        assert match, "no `export type BoardTabId` in boardTabs.ts"
        return tuple(re.findall(r"'([^']+)'", match.group(1)))

    def test_every_board_is_a_tab_in_tab_order(self) -> None:
        tabs = self._tab_ids()
        assert BOARD_IDS == tuple(tab for tab in tabs if tab in BOARD_IDS)

    def test_not_every_tab_is_a_board(self) -> None:
        # Stated rather than implied: `github` is a tab with no store behind
        # it, and the day it gets one, the assertion above is what says so.
        assert set(self._tab_ids()) - set(BOARD_IDS) == {"github"}


class TestTheStreamIsTheOneThatAlreadyExists:
    """No second watcher, no second frame, no second connection."""

    def test_the_watcher_reads_the_configured_store_not_a_file(
        self, root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from openstategraph.api.kanban_events import KanbanChangeWatcher

        elsewhere = tmp_path / "team.sqlite"
        monkeypatch.setenv(KANBAN_URL_ENV, f"sqlite:///{elsewhere}")
        watcher = KanbanChangeWatcher(lambda: open_kanban_store(root), interval=0.01)

        async def run() -> list[str]:
            seen: list[str] = []
            async with watcher.subscribe() as subscriber:
                # A write to the *configured* store, which is not the local
                # file `root` points at. A watcher that had frozen a path at
                # construction, or that stat-ed `kanban.sqlite`, sees nothing.
                _file(open_kanban_store(root), "team-1", TEAM_BOARD)
                async for event in subscriber.events(idle_timeout=2.0):
                    if event is None:
                        break
                    seen.append(event.digest)
                    break
            return seen

        assert asyncio.run(run())

    def test_it_still_costs_nothing_while_no_board_is_open(
        self, root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from openstategraph.api.kanban_events import KanbanChangeWatcher

        monkeypatch.setenv(KANBAN_URL_ENV, f"sqlite:///{tmp_path / 'team.sqlite'}")
        watcher = KanbanChangeWatcher(lambda: open_kanban_store(root), interval=0.01)

        async def run() -> tuple[bool, bool, bool]:
            before = watcher.running
            async with watcher.subscribe():
                during = watcher.running
            return before, during, watcher.running

        before, during, after = asyncio.run(run())
        assert (before, during, after) == (False, True, False)

    def test_there_is_exactly_one_kanban_subject_on_the_live_stream(self) -> None:
        from openstategraph.api.live_stream import LIVE_TOPICS

        kanban = [topic for topic in LIVE_TOPICS if "kanban" in topic.event]
        assert [topic.asked_for for topic in kanban] == ["kanban"]
