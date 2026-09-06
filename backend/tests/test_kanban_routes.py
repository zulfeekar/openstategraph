"""`GET /api/kanban/cards` — the frontend's read door onto real cards.

`kanban-patrol/19` is unblocked here on purpose: reading current state needs
no live channel at all, so the board can show real rows today, refreshed by
hand. `kanban-patrol/07` is what makes a push exist alongside it —
`test_patrol_events.py` covers that stream and `TestRunningThePatrol` below
covers the route that starts it.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app
from openstategraph.kanban_store import Stage, kanban_store_path
from kanban_by_path import ensure_schema, file_card, set_stage
from openstategraph.patrol import PatrolResult


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    root = tmp_path / "workflows"
    root.mkdir()
    # `with`, not a bare `TestClient(...)`: a bare client opens and closes a
    # fresh event loop *per request*, which would tear down (and therefore
    # never finish) a background task started by one request and observed by
    # the next — exactly the behaviour `TestRunningThePatrol` exists to prove
    # actually outlives a single request.
    with TestClient(create_app(workflows_root=root)) as test_client:
        yield test_client


def _configured(client: TestClient, monkeypatch: pytest.MonkeyPatch, project_id: str = "proj-x") -> None:
    from openstategraph.config_file import render_config_file, reset_active_config

    config_path = client.app.state.services.store.root.parent / "openstategraph.yaml"
    config_path.write_text(render_config_file(project_id=project_id))
    monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config_path))
    reset_active_config()


def _wait_for(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition never became true")
        time.sleep(0.005)


def _filed(client: TestClient, task_id: str = "proj-a:thread-1") -> Path:
    root = client.app.state.services.store.root
    db = kanban_store_path(root)
    ensure_schema(db)
    file_card(db, task_id=task_id, board="workflows", kind="bug", category="bug", title="A tool call with no timeout")
    return db


class TestReadingCards:
    def test_an_empty_store_is_an_empty_list_not_an_error(self, client: TestClient) -> None:
        response = client.get("/api/kanban/cards")

        assert response.status_code == 200
        assert response.json() == []

    def test_a_filed_card_is_returned(self, client: TestClient) -> None:
        _filed(client)

        cards = client.get("/api/kanban/cards").json()

        assert len(cards) == 1
        assert cards[0]["task_id"] == "proj-a:thread-1"
        assert cards[0]["stage"] == "unattended"

    def test_stage_changes_are_reflected_on_the_next_read(self, client: TestClient) -> None:
        """The whole point: attend and advance through the CLI/MCP doors,
        and this route — the one the board polls — sees it, because it
        reads the same store, not a cache of its own."""
        db = _filed(client)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        cards = client.get("/api/kanban/cards").json()

        assert cards[0]["stage"] == "attended"
        assert cards[0]["actor"] == "alice"


class TestStaleField:
    """`kanban-patrol/19`. `GET /api/kanban/cards` computes `stale` per row
    from `flagged_stale` — never stored, so a reader never has to know the
    threshold to read the fact."""

    def test_a_fresh_attend_reports_not_stale(self, client: TestClient) -> None:
        db = _filed(client)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        cards = client.get("/api/kanban/cards").json()

        assert cards[0]["stale"] is False

    def test_an_old_heartbeat_reports_stale(self, client: TestClient) -> None:
        db = _filed(client)
        set_stage(db, "proj-a:thread-1", Stage.ATTENDED, actor="alice")
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE cards SET last_heartbeat_at = ? WHERE task_id = ?",
            ("2020-01-01T00:00:00+00:00", "proj-a:thread-1"),
        )
        conn.commit()
        conn.close()

        cards = client.get("/api/kanban/cards").json()

        assert cards[0]["stale"] is True

    def test_an_unattended_card_is_never_stale(self, client: TestClient) -> None:
        _filed(client)

        cards = client.get("/api/kanban/cards").json()

        assert cards[0]["stale"] is False


class TestReleaseRoute:
    """`POST /api/kanban/cards/{task_id}/release` — kanban-patrol/19's
    explicit Release, a thin door onto `kanban_store.release_card`."""

    def _staled(self, client: TestClient, task_id: str = "proj-a:thread-1") -> Path:
        db = _filed(client, task_id)
        set_stage(db, task_id, Stage.ATTENDED, actor="alice")
        set_stage(db, task_id, Stage.RED, actor="alice", test_id="tests/test_x.py::test_y", reason="boom")
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE cards SET last_heartbeat_at = ? WHERE task_id = ?",
            ("2020-01-01T00:00:00+00:00", task_id),
        )
        conn.commit()
        conn.close()
        return db

    def test_releasing_a_stale_card_succeeds_and_resets_it(self, client: TestClient) -> None:
        self._staled(client)

        response = client.post("/api/kanban/cards/proj-a:thread-1/release")

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        card = client.get("/api/kanban/cards").json()[0]
        assert card["stage"] == "unattended"
        assert card["actor"] is None
        assert card["stale"] is False
        assert card["evidence_test_id"] == ""
        assert card["evidence_red_reason"] == ""
        assert card["evidence_green"] is False
        assert card["evidence_commit"] == ""

    def test_releasing_an_active_card_is_refused_with_a_clean_400(self, client: TestClient) -> None:
        _filed(client)
        set_stage(kanban_store_path(client.app.state.services.store.root), "proj-a:thread-1", Stage.ATTENDED, actor="alice")

        response = client.post("/api/kanban/cards/proj-a:thread-1/release")

        assert response.status_code == 400
        assert "not stale" in response.json()["detail"]
        card = client.get("/api/kanban/cards").json()[0]
        assert card["stage"] == "attended", "a refused release must not touch the card"


class TestAnswerRoute:
    """`POST /api/kanban/cards/{task_id}/answer` — kanban-patrol/15's Answer,
    the board's own door onto `kanban_store.answer_card`.

    The browser is where a person actually reads a Needs You card, so this is
    the door the decision usually arrives through. It adds no rule of its
    own: the store owns "written once", "back to Detected, never Resolved",
    and every refusal.
    """

    def _judgement(self, client: TestClient, task_id: str = "proj-a:judgement") -> Path:
        root = client.app.state.services.store.root
        db = kanban_store_path(root)
        ensure_schema(db)
        file_card(
            db,
            task_id=task_id,
            board="workflows",
            kind="decision",
            category="decision",
            title="Which model should the grader use?",
        )
        return db

    def test_answering_records_the_decision_and_the_card_returns_to_detected(
        self, client: TestClient
    ) -> None:
        self._judgement(client)

        response = client.post(
            "/api/kanban/cards/proj-a:judgement/answer",
            json={"answer": "The cloud one.", "actor": "zulfeekar"},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        card = client.get("/api/kanban/cards").json()[0]
        assert card["answer"] == "The cloud one."
        assert card["answered_by"] == "zulfeekar"
        assert card["answered_at"]
        # Still unattended: answering is a decision, not a claim, and the
        # card must be attendable by an agent straight afterwards.
        assert card["stage"] == "unattended"

    def test_a_blank_answer_is_a_clean_400_and_touches_nothing(self, client: TestClient) -> None:
        self._judgement(client)

        response = client.post(
            "/api/kanban/cards/proj-a:judgement/answer",
            json={"answer": "   ", "actor": "zulfeekar"},
        )

        assert response.status_code == 400
        assert "answer" in response.json()["detail"]
        assert client.get("/api/kanban/cards").json()[0]["answer"] == ""

    def test_a_card_that_was_never_in_question_is_a_clean_400(self, client: TestClient) -> None:
        _filed(client)

        response = client.post(
            "/api/kanban/cards/proj-a:thread-1/answer",
            json={"answer": "yes", "actor": "zulfeekar"},
        )

        assert response.status_code == 400
        assert "not waiting on a decision" in response.json()["detail"]

    def test_a_missing_card_is_a_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/kanban/cards/nope/answer", json={"answer": "yes", "actor": "zulfeekar"}
        )

        assert response.status_code == 404

    def test_a_second_answer_is_refused_and_the_first_decision_stands(
        self, client: TestClient
    ) -> None:
        self._judgement(client)
        client.post(
            "/api/kanban/cards/proj-a:judgement/answer",
            json={"answer": "The cloud one.", "actor": "zulfeekar"},
        )

        response = client.post(
            "/api/kanban/cards/proj-a:judgement/answer",
            json={"answer": "The local one.", "actor": "someone-else"},
        )

        assert response.status_code == 400
        assert "zulfeekar" in response.json()["detail"]
        assert client.get("/api/kanban/cards").json()[0]["answer"] == "The cloud one."

    def test_a_caller_that_names_nobody_is_still_recorded_as_something(
        self, client: TestClient
    ) -> None:
        # `kanban-patrol/20`'s floor: the store refuses a blank actor, and
        # the board has no name box. A card reading "answered by " with
        # nothing in the blank is meaningless, so this door names the door.
        self._judgement(client)

        response = client.post(
            "/api/kanban/cards/proj-a:judgement/answer", json={"answer": "The cloud one."}
        )

        assert response.status_code == 200
        assert response.json()["answered_by"].strip()
        assert client.get("/api/kanban/cards").json()[0]["answered_by"].strip()


class TestRunningThePatrol:
    """`POST /api/kanban/patrol/run` — kanban-patrol/27, made durable by
    `kanban-patrol/07`. The board's own Refresh button already exists; this
    is the door "Run Patrol" calls, and it no longer waits for the patrol to
    finish before answering."""

    def test_returns_202_and_starts_immediately(self, client: TestClient, monkeypatch) -> None:
        _configured(client, monkeypatch)

        response = client.post("/api/kanban/patrol/run")

        assert response.status_code == 202
        assert response.json() == {"status": "started"}

    def test_no_project_id_is_a_clear_error_not_a_crash(self, client: TestClient, monkeypatch) -> None:
        from openstategraph.config_file import reset_active_config
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(client.app.state.services.store.root.parent / "does-not-exist.yaml"))
        reset_active_config()

        response = client.post("/api/kanban/patrol/run")

        assert response.status_code == 400
        reset_active_config()

    def test_the_request_returns_before_a_slow_patrol_finishes(
        self, client: TestClient, monkeypatch
    ) -> None:
        """`07`'s whole point, proven with a clock rather than trusted on
        faith: today's real patrol answers in well under a second (19
        findings, sub-second — the ticket's own prior resolution), so a real
        demo cannot show a request *waiting* for one. A patrol instrumented
        to take a third of a second stands in for a slower one, and the
        request is timed against it."""

        def slow_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            time.sleep(0.3)
            return PatrolResult(filed=[], skipped=[], total_findings=0)

        monkeypatch.setattr("openstategraph.patrol.run_patrol", slow_patrol)
        _configured(client, monkeypatch)

        started = time.monotonic()
        response = client.post("/api/kanban/patrol/run")
        elapsed = time.monotonic() - started

        assert response.status_code == 202
        assert elapsed < 0.15, f"the request waited {elapsed:.3f}s for a 0.3s patrol"
        _wait_for(lambda: client.get("/api/kanban/patrol/status").json()["status"] != "running")

    def test_a_second_run_while_one_is_in_flight_is_refused(
        self, client: TestClient, monkeypatch
    ) -> None:
        def slow_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            time.sleep(0.3)
            return PatrolResult(filed=[], skipped=[], total_findings=0)

        monkeypatch.setattr("openstategraph.patrol.run_patrol", slow_patrol)
        _configured(client, monkeypatch)

        first = client.post("/api/kanban/patrol/run")
        second = client.post("/api/kanban/patrol/run")

        assert first.status_code == 202
        assert second.status_code == 409
        assert "already running" in second.json()["detail"].lower()
        _wait_for(lambda: client.get("/api/kanban/patrol/status").json()["status"] != "running")

    def test_a_new_run_is_allowed_once_the_last_one_finished(
        self, client: TestClient, monkeypatch
    ) -> None:
        _configured(client, monkeypatch)
        first = client.post("/api/kanban/patrol/run")
        assert first.status_code == 202
        _wait_for(lambda: client.get("/api/kanban/patrol/status").json()["status"] != "running")

        second = client.post("/api/kanban/patrol/run")

        assert second.status_code == 202


class TestPatrolStatus:
    """`GET /api/kanban/patrol/status` — the refetch half of "refetch plus
    subscribe" (kanban-patrol/07). A client that opens the board mid-patrol
    asks this instead of relying on having been subscribed when it started."""

    def test_idle_before_anything_has_run(self, client: TestClient) -> None:
        response = client.get("/api/kanban/patrol/status")

        assert response.status_code == 200
        assert response.json()["status"] == "idle"

    def test_running_while_in_flight_then_finished_with_the_summary(
        self, client: TestClient, monkeypatch
    ) -> None:
        def slow_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            if on_card_filed is not None:
                on_card_filed("proj-x:thread-1", "A card")
            time.sleep(0.2)
            return PatrolResult(filed=["proj-x:thread-1"], skipped=[], total_findings=1)

        monkeypatch.setattr("openstategraph.patrol.run_patrol", slow_patrol)
        _configured(client, monkeypatch)

        client.post("/api/kanban/patrol/run")
        mid_flight = client.get("/api/kanban/patrol/status").json()
        assert mid_flight["status"] == "running"
        assert mid_flight["started_at"] != ""

        _wait_for(lambda: client.get("/api/kanban/patrol/status").json()["status"] != "running")
        finished = client.get("/api/kanban/patrol/status").json()
        assert finished["status"] == "finished"
        assert finished["filed"] == 1
        assert finished["total_findings"] == 1

    def test_a_failed_patrol_is_reported_as_failed_with_the_reason(
        self, client: TestClient, monkeypatch
    ) -> None:
        def broken_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            raise RuntimeError("no such table: kanban_cards")

        monkeypatch.setattr("openstategraph.patrol.run_patrol", broken_patrol)
        _configured(client, monkeypatch)

        client.post("/api/kanban/patrol/run")
        _wait_for(lambda: client.get("/api/kanban/patrol/status").json()["status"] != "running")

        status = client.get("/api/kanban/patrol/status").json()
        assert status["status"] == "failed"
        assert "no such table" in status["error"]


class TestAClientThatConnectsMidPatrol:
    """`07`'s own "done when": *"A client that connects mid-patrol gets a
    correct board — refetch plus subscribe, with a test that a card created
    while disconnected is present after reconnect."* No subscriber is opened
    at all here on purpose — this is the half of that claim that belongs to
    the plain read door: `GET /api/kanban/cards` must be correct regardless
    of whether anything was ever listening on the SSE stream, because it is
    a plain SQL read with no memory of events at all."""

    def test_a_card_filed_while_nobody_was_subscribed_is_on_the_next_read(
        self, client: TestClient, monkeypatch
    ) -> None:
        def fake_patrol(*, project_id, workflows_root, on_card_filed=None, **_kw):
            # Filed for real, through the same `file_card` seam a genuine
            # patrol uses — not asserted from the stub's return value, which
            # would prove nothing about the store.
            db = kanban_store_path(workflows_root)
            ensure_schema(db)
            file_card(
                db,
                task_id="proj-x:thread-9",
                board="workflows",
                kind="task",
                category="gap",
                title="Filed while nobody was watching",
            )
            return PatrolResult(filed=["proj-x:thread-9"], skipped=[], total_findings=1)

        monkeypatch.setattr("openstategraph.patrol.run_patrol", fake_patrol)
        _configured(client, monkeypatch)

        # Red first, as `07` asks: before the patrol runs, the card is
        # genuinely absent — the assertion below is not a tautology.
        assert client.get("/api/kanban/cards").json() == []

        client.post("/api/kanban/patrol/run")
        _wait_for(lambda: client.get("/api/kanban/patrol/status").json()["status"] != "running")

        cards = client.get("/api/kanban/cards").json()
        assert any(card["task_id"] == "proj-x:thread-9" for card in cards)


class TestTheIdeaBriefOnTheWire:
    """`osg-agent-experience/25`. The board draws the brief, so the brief has
    to reach it — and on *every* row, not only an idea card's, because two
    doors publishing different field sets is how a board and an agent come to
    read different cards."""

    def test_an_idea_cards_five_fields_reach_the_board(self, client: TestClient) -> None:
        from kanban_by_path import file_idea_card

        db = kanban_store_path(client.app.state.services.store.root)
        ensure_schema(db)
        file_idea_card(
            db,
            project_id="proj-a",
            kind="task",
            title="Draft the agenda",
            story="A weekly planner wants a first agenda without typing one.",
            done_when="A run answers with five numbered items.",
            priority="high",
            priority_reason="It is the first thing the owner asked for.",
            blocked_by=("proj-a:idea-other",),
            agent_model="opus",
            agent_effort="high",
        )

        row = client.get("/api/kanban/cards").json()[0]

        assert row["story"].startswith("A weekly planner")
        assert row["done_when"] == "A run answers with five numbered items."
        assert row["blocked_by"] == ["proj-a:idea-other"]
        assert row["agent_model"] == "opus"
        assert row["agent_effort"] == "high"

    def test_a_patrol_card_carries_them_empty_rather_than_missing(
        self, client: TestClient
    ) -> None:
        _filed(client)

        row = client.get("/api/kanban/cards").json()[0]

        assert row["story"] == ""
        assert row["done_when"] == ""
        assert row["blocked_by"] == []
        assert row["agent_model"] == ""
        assert row["agent_effort"] == ""
