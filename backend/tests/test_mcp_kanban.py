"""The MCP door onto a kanban card — `kanban-patrol/16`.

Same rule as the CLI door (`kanban-patrol/19`): both wrap
`kanban_store.set_stage` / `read_card` directly, never a second
implementation of the claim or ordering logic. This file exists to prove the
*wrapping* is thin and that the concurrency guarantee survives the MCP
transport, not to re-test `kanban_store.py`'s own rules (`test_kanban_store.py`
owns those).
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openstategraph.api.services import WorkflowServices
from openstategraph.kanban_store import ensure_schema, file_card, kanban_store_path
from openstategraph.mcp_server import EXPOSED_TOOLS, build_mcp_server


@pytest.fixture()
def services(tmp_path: Path) -> WorkflowServices:
    root = tmp_path / "workflows"
    root.mkdir()
    return WorkflowServices(workflows_root=root)


def _filed(services: WorkflowServices, task_id: str = "proj-a:thread-1") -> Path:
    db = kanban_store_path(services.store.root)
    ensure_schema(db)
    file_card(db, task_id=task_id, board="workflows", kind="bug", category="bug", title="A tool call with no timeout")
    return db


def _call(server, name: str, args: dict):
    result = asyncio.run(server.call_tool(name, args))
    return result[1] if isinstance(result, tuple) else result


class TestExposedSurface:
    def test_the_three_kanban_tools_are_declared(self) -> None:
        assert "kanban_attend_card" in EXPOSED_TOOLS
        assert "kanban_set_stage" in EXPOSED_TOOLS
        assert "kanban_show_card" in EXPOSED_TOOLS
        assert "kanban_release_card" in EXPOSED_TOOLS
        assert "kanban_file_card" in EXPOSED_TOOLS


class TestAttend:
    def test_first_attend_wins(self, services: WorkflowServices) -> None:
        _filed(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "alice"})

        assert result.get("ok") is True

    def test_second_attend_loses_and_names_the_winner(self, services: WorkflowServices) -> None:
        """The concurrency guarantee `kanban_store.py` proves at the function
        level must survive the MCP call boundary unchanged — the loser is
        told, never silently overwritten."""
        _filed(services)
        server = build_mcp_server(services)
        _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "alice"})

        result = _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "bob"})

        assert result.get("ok") is False
        assert "alice" in result.get("reason", "")


class TestSetStage:
    def test_advances_the_card(self, services: WorkflowServices) -> None:
        _filed(services)
        server = build_mcp_server(services)
        _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "alice"})

        result = _call(
            server,
            "kanban_set_stage",
            {
                "task_id": "proj-a:thread-1", "stage": "red", "actor": "alice",
                "test_id": "tests/test_x.py::test_y", "reason": "boom",
            },
        )

        assert result.get("ok") is True

    def test_skipping_a_stage_is_reported_not_raised_over_the_wire(
        self, services: WorkflowServices
    ) -> None:
        """An MCP client gets a structured refusal, not a stack trace over the
        transport — `StageOrderError` is caught at this boundary and turned
        into `ok=False` + `reason`, same shape as a lost claim."""
        _filed(services)
        server = build_mcp_server(services)
        _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "alice"})

        result = _call(
            server,
            "kanban_set_stage",
            {"task_id": "proj-a:thread-1", "stage": "green", "actor": "alice", "test_id": "tests/test_x.py::test_y"},
        )

        assert result.get("ok") is False
        assert "one step at a time" in result.get("reason", "")

    def test_finished_with_no_evidence_is_refused_over_the_wire(
        self, services: WorkflowServices
    ) -> None:
        """`kanban-patrol/17`+`21`. `MissingEvidenceError` gets the exact same
        structured treatment `StageOrderError` already gets at this
        boundary — `ok=False` with the gap named, never a stack trace."""
        _filed(services)
        server = build_mcp_server(services)
        _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "alice"})

        result = _call(
            server, "kanban_set_stage", {"task_id": "proj-a:thread-1", "stage": "finished", "actor": "alice"}
        )

        assert result.get("ok") is False
        assert "test_id" in result.get("reason", "")


class TestShowCard:
    def test_returns_the_instruction(self, services: WorkflowServices) -> None:
        _filed(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_show_card", {"task_id": "proj-a:thread-1"})

        assert result["task_id"] == "proj-a:thread-1"
        assert result["title"] == "A tool call with no timeout"

    def test_an_unknown_task_id_is_a_clear_miss_not_a_crash(self, services: WorkflowServices) -> None:
        server = build_mcp_server(services)

        result = _call(server, "kanban_show_card", {"task_id": "does-not-exist"})

        assert result.get("ok") is False


class TestReleaseCard:
    """`kanban-patrol/19`'s explicit Release, over MCP — a thin wrapper over
    `kanban_store.release_card`, never a second implementation of "already
    flagged, then atomic reset"."""

    def _staled(self, services: WorkflowServices, task_id: str = "proj-a:thread-1") -> None:
        from openstategraph.kanban_store import Stage, kanban_store_path, set_stage

        db = kanban_store_path(services.store.root)
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

    def test_releasing_a_stale_card_succeeds_and_resets_it(self, services: WorkflowServices) -> None:
        _filed(services)
        self._staled(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_release_card", {"task_id": "proj-a:thread-1"})

        assert result.get("ok") is True
        result = _call(server, "kanban_show_card", {"task_id": "proj-a:thread-1"})
        assert result["stage"] == "unattended"
        assert result["actor"] is None

    def test_releasing_an_active_card_is_refused_not_raised(self, services: WorkflowServices) -> None:
        _filed(services)
        server = build_mcp_server(services)
        _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "alice"})

        result = _call(server, "kanban_release_card", {"task_id": "proj-a:thread-1"})

        assert result.get("ok") is False
        assert "not stale" in result.get("reason", "")


class TestActorIsTheServersToDetermine:
    """`kanban-patrol/29`: identity is the server's to determine, never the
    caller's to assert — `principal.py`'s standing rule, re-asserted at the
    MCP door.

    `28` established the mechanism: the streamable-HTTP transport puts the
    Starlette request on the tool's `RequestContext`, so a deployment behind
    a proxy that stamps a verified identity has the same headers
    `/api/runs` already resolves through `IPrincipals`. These tests drive
    that seam the way the transport does — by setting the request context
    the tool reads — rather than calling a private closure.
    """

    HEADER = "x-forwarded-email"

    @staticmethod
    @contextmanager
    def _arriving_with(headers: dict[str, str] | None):
        """One request, carrying `headers` — or, with `None`, a stdio call,
        which has no HTTP request at all and must be handled as such."""
        from mcp.server.lowlevel.server import request_ctx
        from mcp.shared.context import RequestContext

        request = SimpleNamespace(headers=headers) if headers is not None else None
        token = request_ctx.set(
            RequestContext(
                request_id="1",
                meta=None,
                session=None,
                lifespan_context=None,
                request=request,
            )
        )
        try:
            yield
        finally:
            request_ctx.reset(token)

    def _services(self, tmp_path: Path) -> WorkflowServices:
        from openstategraph.principal import TrustedHeaderPrincipals

        root = tmp_path / "workflows"
        root.mkdir()
        return WorkflowServices(
            workflows_root=root, principals=TrustedHeaderPrincipals(self.HEADER)
        )

    def _actor(self, services: WorkflowServices) -> str | None:
        from openstategraph.kanban_store import kanban_store_path, read_card

        return read_card(kanban_store_path(services.store.root), "proj-a:thread-1").actor

    def test_a_vouched_principal_is_the_actor_whatever_the_model_passed(
        self, tmp_path: Path
    ) -> None:
        services = self._services(tmp_path)
        _filed(services)
        server = build_mcp_server(services)

        with self._arriving_with({self.HEADER: "alice@example.com", "X-OpenStateGraph-Proxy": "1"}):
            result = _call(
                server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "claude"}
            )

        assert result.get("ok") is True
        assert self._actor(services) == "alice@example.com"

    def test_answer_records_the_principal_not_the_passed_name(self, tmp_path: Path) -> None:
        """`kanban-patrol/15`'s answer is a *decision*, so whose name it
        carries matters more than on any other kanban write — a decision
        attributed to whoever the model said made it is not a record of who
        made it. Same `_actor_on_the_card` seam as attend, not a second one."""
        services = self._services(tmp_path)
        db = _judgement(services)
        server = build_mcp_server(services)

        with self._arriving_with({self.HEADER: "alice@example.com", "X-OpenStateGraph-Proxy": "1"}):
            result = _call(
                server,
                "kanban_answer_card",
                {"task_id": "proj-a:judgement", "actor": "claude", "answer": "The cloud one."},
            )

        assert result.get("ok") is True
        from openstategraph.kanban_store import read_card

        assert read_card(db, "proj-a:judgement").answered_by == "alice@example.com"

    def test_set_stage_records_the_principal_not_the_passed_name(self, tmp_path: Path) -> None:
        services = self._services(tmp_path)
        _filed(services)
        server = build_mcp_server(services)
        headers = {self.HEADER: "alice@example.com", "X-OpenStateGraph-Proxy": "1"}

        with self._arriving_with(headers):
            _call(server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "claude"})
            result = _call(
                server,
                "kanban_set_stage",
                {
                    "task_id": "proj-a:thread-1",
                    "stage": "red",
                    "actor": "mallory",
                    "test_id": "tests/test_x.py::test_y",
                    "reason": "boom",
                },
            )

        assert result.get("ok") is True
        assert self._actor(services) == "alice@example.com"

    def test_a_request_with_no_headers_keeps_the_callers_actor(self, tmp_path: Path) -> None:
        services = self._services(tmp_path)
        _filed(services)
        server = build_mcp_server(services)

        with self._arriving_with({}):
            result = _call(
                server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "claude"}
            )

        assert result.get("ok") is True
        assert self._actor(services) == "claude"

    def test_stdio_has_no_request_and_keeps_the_callers_actor(self, tmp_path: Path) -> None:
        services = self._services(tmp_path)
        _filed(services)
        server = build_mcp_server(services)

        with self._arriving_with(None):
            result = _call(
                server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "claude"}
            )

        assert result.get("ok") is True
        assert self._actor(services) == "claude"

    def test_an_identity_header_with_no_proxy_signature_resolves_nobody(
        self, tmp_path: Path
    ) -> None:
        """`principal.py`'s own rule, asserted at this door rather than
        assumed: the identity header is only trusted beside the one header
        whose name this project owns and every shipped proxy config
        overwrites. Alone, it is whatever the client typed."""
        services = self._services(tmp_path)
        _filed(services)
        server = build_mcp_server(services)

        with self._arriving_with({self.HEADER: "alice@example.com"}):
            result = _call(
                server, "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": "claude"}
            )

        assert result.get("ok") is True
        assert self._actor(services) == "claude"

    def test_the_request_context_is_never_a_tool_argument(self, tmp_path: Path) -> None:
        """The parameter carrying the request must stay invisible on the
        wire. A `ctx` a client could fill in would be identity asserted by
        the caller wearing the server's clothes — the exact thing this
        ticket removes."""
        services = self._services(tmp_path)
        server = build_mcp_server(services)

        tools = {t.name: sorted(t.inputSchema.get("properties", {})) for t in asyncio.run(server.list_tools())}

        assert tools["kanban_attend_card"] == ["actor", "task_id"]
        assert tools["kanban_set_stage"] == [
            "actor",
            "commit",
            "reason",
            "stage",
            "task_id",
            "test_id",
        ]


class TestListCards:
    """`kanban-patrol/16`'s read tool. An agent that is not the one which
    filed a card has to find it somehow; every other tool here takes a
    `task_id` it must already know."""

    def _two_cards(self, services: WorkflowServices) -> Path:
        db = kanban_store_path(services.store.root)
        ensure_schema(db)
        file_card(db, task_id="proj-a:one", board="workflows", kind="bug",
                  category="bug", title="A tool call with no timeout",
                  priority="high", area="backend")
        file_card(db, task_id="proj-a:two", board="workflows", kind="decision",
                  category="decision", title="Which model grades this",
                  priority="low", area="ux")
        return db

    def test_the_tool_is_declared(self) -> None:
        assert "kanban_list_cards" in EXPOSED_TOOLS

    def test_every_card_is_listed(self, services: WorkflowServices) -> None:
        self._two_cards(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_list_cards", {})

        assert result["ok"] is True
        assert {c["task_id"] for c in result["cards"]} == {"proj-a:one", "proj-a:two"}

    def test_a_row_carries_what_the_board_reads_plus_its_column(
        self, services: WorkflowServices
    ) -> None:
        """The same fields `GET /api/kanban/cards` sends, so a client of this
        tool and the board are reading one row shape rather than two that can
        drift — plus the derived `column`, which the board computes for
        itself in TypeScript and an MCP client cannot."""
        from openstategraph.api.schemas import KanbanCardResponse

        self._two_cards(services)
        server = build_mcp_server(services)

        row = _call(server, "kanban_list_cards", {})["cards"][0]

        assert set(row) == set(KanbanCardResponse.model_fields) | {"column"}

    def test_a_column_filter_selects_only_that_column(
        self, services: WorkflowServices
    ) -> None:
        self._two_cards(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_list_cards", {"column": "needsYou"})

        assert [c["task_id"] for c in result["cards"]] == ["proj-a:two"]

    def test_the_column_filter_ignores_case(self, services: WorkflowServices) -> None:
        self._two_cards(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_list_cards", {"column": "NEEDSYOU"})

        assert [c["task_id"] for c in result["cards"]] == ["proj-a:two"]

    def test_an_unknown_column_names_the_accepted_values(
        self, services: WorkflowServices
    ) -> None:
        """Never an exception over the transport, and never a bare empty list
        either — an empty answer with no reason reads as "the board is empty",
        which is a different and wrong fact."""
        self._two_cards(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_list_cards", {"column": "backlog"})

        assert result["ok"] is False
        assert result["cards"] == []
        for accepted in ("detected", "needsYou", "inProgress", "resolved"):
            assert accepted in result["reason"]

    def test_an_unknown_area_names_the_accepted_values(
        self, services: WorkflowServices
    ) -> None:
        self._two_cards(services)
        server = build_mcp_server(services)

        result = _call(server, "kanban_list_cards", {"area": "kitchen"})

        assert result["ok"] is False
        assert result["cards"] == []
        assert "backend" in result["reason"]

    def test_board_area_and_priority_filter_exactly(
        self, services: WorkflowServices
    ) -> None:
        self._two_cards(services)
        server = build_mcp_server(services)

        assert [c["task_id"] for c in _call(
            server, "kanban_list_cards", {"priority": "HIGH"}
        )["cards"]] == ["proj-a:one"]
        assert [c["task_id"] for c in _call(
            server, "kanban_list_cards", {"area": "ux"}
        )["cards"]] == ["proj-a:two"]
        assert _call(server, "kanban_list_cards", {"board": "nothing-here"})["cards"] == []

    def test_a_store_that_does_not_exist_yet_lists_nothing(
        self, services: WorkflowServices
    ) -> None:
        """No patrol has ever run here. That is an empty board, not a
        failure — the same answer `list_cards` and `GET /api/kanban/cards`
        already give."""
        server = build_mcp_server(services)

        result = _call(server, "kanban_list_cards", {})

        assert result["ok"] is True
        assert result["cards"] == []

    def test_a_claimed_card_reports_the_in_progress_column(
        self, services: WorkflowServices
    ) -> None:
        self._two_cards(services)
        server = build_mcp_server(services)
        _call(server, "kanban_attend_card", {"task_id": "proj-a:two", "actor": "alice"})

        result = _call(server, "kanban_list_cards", {"column": "inProgress"})

        assert [c["task_id"] for c in result["cards"]] == ["proj-a:two"]


def _judgement(services: WorkflowServices, task_id: str = "proj-a:judgement") -> Path:
    db = kanban_store_path(services.store.root)
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


class TestAnswerCard:
    """`kanban-patrol/15`, and `16`'s last deferred tool. It was deliberately
    not built until the owner had decided what Answer *does* — building the
    tool first would have been inventing the answer in the adapter.

    What it is now: the same `kanban_store.answer_card` the CLI and the HTTP
    route call, so an agent that grills a person over MCP and a person typing
    into the board write one row through one path.
    """

    def test_the_tool_is_declared(self) -> None:
        assert "kanban_answer_card" in EXPOSED_TOOLS

    def test_answering_records_the_decision_and_returns_the_card_to_detected(
        self, services: WorkflowServices
    ) -> None:
        db = _judgement(services)
        server = build_mcp_server(services)

        result = _call(
            server,
            "kanban_answer_card",
            {"task_id": "proj-a:judgement", "actor": "alice", "answer": "The cloud one."},
        )

        assert result.get("ok") is True
        from openstategraph.kanban_store import column_for, read_card

        card = read_card(db, "proj-a:judgement")
        assert card.answer == "The cloud one."
        assert column_for(card) == "detected"

    def test_a_blank_answer_is_a_structured_refusal_not_a_stack_trace(
        self, services: WorkflowServices
    ) -> None:
        # Every refusal at this door reads the same way: a client's model
        # reads `{"ok": false, "reason": ...}` far more reliably than an
        # exception raised over the transport.
        _judgement(services)
        server = build_mcp_server(services)

        result = _call(
            server,
            "kanban_answer_card",
            {"task_id": "proj-a:judgement", "actor": "alice", "answer": "   "},
        )

        assert result.get("ok") is False
        assert "answer" in result.get("reason", "")

    def test_a_card_that_was_never_in_question_is_refused(
        self, services: WorkflowServices
    ) -> None:
        _filed(services)
        server = build_mcp_server(services)

        result = _call(
            server,
            "kanban_answer_card",
            {"task_id": "proj-a:thread-1", "actor": "alice", "answer": "yes"},
        )

        assert result.get("ok") is False
        assert "not waiting on a decision" in result.get("reason", "")

    def test_a_missing_card_is_refused_by_name(self, services: WorkflowServices) -> None:
        _judgement(services)
        server = build_mcp_server(services)

        result = _call(
            server,
            "kanban_answer_card",
            {"task_id": "nope", "actor": "alice", "answer": "yes"},
        )

        assert result.get("ok") is False
        assert "nope" in result.get("reason", "")

    def test_a_second_answer_loses_and_names_the_first(self, services: WorkflowServices) -> None:
        _judgement(services)
        server = build_mcp_server(services)
        _call(
            server,
            "kanban_answer_card",
            {"task_id": "proj-a:judgement", "actor": "alice", "answer": "The cloud one."},
        )

        result = _call(
            server,
            "kanban_answer_card",
            {"task_id": "proj-a:judgement", "actor": "bob", "answer": "The local one."},
        )

        assert result.get("ok") is False
        assert "alice" in result.get("reason", "")


class TestTwoRealConcurrentCallers:
    """`kanban-patrol/16`'s own "done when", and the one it left unbuilt:
    *a concurrency test drives two claimants at one card and asserts exactly
    one wins and the loser is told.*

    That guarantee was proven twice already and neither proof was this one.
    `test_kanban_store.py` drives the function; `TestAttend` above drives two
    **sequential** calls through the tool and shows the refusal survives the
    call boundary. Neither has ever had two callers in flight at once, which
    is the only shape that can catch a read-then-write.
    """

    def _server(self, services: WorkflowServices):
        _filed(services)
        return build_mcp_server(services)

    def _attend(self, server, actor: str):
        async def go() -> Any:
            result = await server.call_tool(
                "kanban_attend_card", {"task_id": "proj-a:thread-1", "actor": actor}
            )
            return result[1] if isinstance(result, tuple) else result

        return go()

    def test_two_calls_in_flight_at_once_produce_exactly_one_winner(
        self, services: WorkflowServices
    ) -> None:
        server = self._server(services)

        async def both() -> list[Any]:
            return list(await asyncio.gather(self._attend(server, "alice"), self._attend(server, "bob")))

        results = asyncio.run(both())

        winners = [r for r in results if r.get("ok") is True]
        losers = [r for r in results if r.get("ok") is False]
        assert len(winners) == 1
        assert len(losers) == 1
        # Told, not guessed at: the loser learns who actually holds the card,
        # so a polite agent can take the next one instead of retrying.
        assert losers[0]["reason"]
        assert "alice" in losers[0]["reason"] or "bob" in losers[0]["reason"]

    def test_a_gather_does_not_interleave_inside_a_tool_body(
        self, services: WorkflowServices
    ) -> None:
        """And here is what the test above does *not* prove, written down
        rather than assumed — because a test that cannot fail is worse than
        no test at all.

        These tool bodies are plain synchronous functions, so the server
        awaits each one inline on the event-loop thread: two `gather`ed calls
        are dispatched concurrently and then run one after the other. The
        transport serialises them. So the test above proves the refusal
        survives real concurrent dispatch, and the *atomicity* is proven by
        the threaded test below and by `test_kanban_store.py` — never by this
        one.

        Pinned so the day a kanban tool becomes `async def`, or does its work
        off the loop, this fails and whoever made that change reads the
        paragraph they need.
        """
        import threading

        from openstategraph import kanban_store

        threads: list[str] = []
        real = kanban_store.set_stage

        def note(*args: Any, **kwargs: Any) -> Any:
            threads.append(threading.current_thread().name)
            return real(*args, **kwargs)

        server = self._server(services)
        kanban_store.set_stage = note  # type: ignore[assignment]
        try:

            async def both() -> Any:
                return await asyncio.gather(self._attend(server, "alice"), self._attend(server, "bob"))

            asyncio.run(both())
        finally:
            kanban_store.set_stage = real  # type: ignore[assignment]

        assert threads == ["MainThread", "MainThread"], threads

    def test_two_callers_that_genuinely_overlap_still_produce_one_winner(
        self, services: WorkflowServices
    ) -> None:
        """The atomicity itself, at this door — two threads, each with its own
        event loop, held at a barrier until **both** have read the card.

        That barrier is the whole test. It manufactures the interleave a
        `gather` cannot produce here and a sequential call never could: both
        callers see an unattended card, and only the conditional `UPDATE`
        decides. A read-then-write passes every other test in this file and
        records two winners on one card here.
        """
        import threading

        from openstategraph import kanban_store

        server = self._server(services)
        both_have_read = threading.Barrier(2, timeout=5)
        real_read = kanban_store.read_card
        once: set[str] = set()
        guard = threading.Lock()

        def read_then_wait_for_the_other(*args: Any, **kwargs: Any) -> Any:
            card = real_read(*args, **kwargs)
            with guard:
                first_read_by_this_thread = threading.current_thread().name not in once
                once.add(threading.current_thread().name)
            if first_read_by_this_thread:
                both_have_read.wait()
            return card

        results: list[Any] = []
        results_lock = threading.Lock()

        def caller(actor: str) -> None:
            outcome = asyncio.run(self._attend(server, actor))
            with results_lock:
                results.append(outcome)

        kanban_store.read_card = read_then_wait_for_the_other  # type: ignore[assignment]
        try:
            threads = [
                threading.Thread(target=caller, args=("alice",)),
                threading.Thread(target=caller, args=("bob",)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
        finally:
            kanban_store.read_card = real_read  # type: ignore[assignment]

        assert len(results) == 2, "both callers must return, neither may hang"
        assert len([r for r in results if r.get("ok") is True]) == 1, results
        loser = next(r for r in results if r.get("ok") is False)
        assert "alice" in loser["reason"] or "bob" in loser["reason"]
        # And the card carries exactly one name — the winner's — rather than
        # whichever write happened to land last.
        from openstategraph.kanban_store import kanban_store_path, read_card

        actor = read_card(kanban_store_path(services.store.root), "proj-a:thread-1").actor
        assert actor in {"alice", "bob"}


class TestTheKanbanToolsAreDocumented:
    """`kanban-patrol/16` recorded this gap in its own resolution and did not
    close it: *no test enforces the MCP doc surface the way
    `test_documented_cli_surface.py` does for the CLI*. This is that test,
    scoped to the tools this ticket owns.

    Scoped by prefix deliberately. `docs/mcp.md` names non-tools in prose
    (`draw_mermaid_png`, `state_dir`), so a blanket "every name written as a
    call is a tool" would fail for a correct document — and a check that
    fails wrongly gets suppressed and then guards nothing.
    """

    KANBAN = tuple(name for name in EXPOSED_TOOLS if name.startswith("kanban_"))

    def _doc(self) -> str:
        return (Path(__file__).resolve().parents[2] / "docs" / "mcp.md").read_text()

    def test_there_are_kanban_tools_to_document(self) -> None:
        # A rule about an empty set is a rule that passes for the wrong reason.
        assert len(self.KANBAN) >= 5

    def test_every_kanban_tool_is_named_in_the_doc(self) -> None:
        doc = self._doc()
        missing = [name for name in self.KANBAN if name not in doc]
        assert not missing, (
            f"exposed over MCP and absent from docs/mcp.md: {missing}. An agent "
            "reads the doc to learn this surface exists; a tool nobody documents "
            "is a tool nobody calls."
        )

    def test_the_doc_names_no_kanban_tool_that_does_not_exist(self) -> None:
        import re

        named = set(re.findall(r"`(kanban_[a-z0-9_]*)\(", self._doc()))
        assert not named - set(self.KANBAN), (
            f"docs/mcp.md documents kanban tools that are not registered: "
            f"{sorted(named - set(self.KANBAN))}"
        )


@pytest.fixture()
def _identified(tmp_path: Path, monkeypatch) -> Path:
    """A project this door can name — `osg-agent-experience/25`.

    A card is keyed by `project_id`, and that id is read from the project's
    own committed config, never invented per-call (`kanban-patrol/23`). So a
    test of the filing door has to give it a project to file into, exactly as
    a real one has.
    """
    from openstategraph.config_file import reset_active_config

    config = tmp_path / "openstategraph.yaml"
    config.write_text("project_id: proj-a\n")
    monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
    reset_active_config()
    yield config
    reset_active_config()


def _brief(**overrides: object) -> dict:
    args: dict = {
        "kind": "task",
        "title": "Draft the agenda",
        "story": "A weekly planner wants a first agenda without typing one.",
        "done_when": "A run answers with five numbered items.",
        "priority": "high",
        "priority_reason": "It is the first thing the owner asked for.",
    }
    args.update(overrides)
    return args


class TestFileCard:
    """`osg-agent-experience/25`'s filing door — the one kanban tool that
    creates a card rather than moving one already on the board."""

    def test_the_tool_is_declared(self) -> None:
        assert "kanban_file_card" in EXPOSED_TOOLS

    def test_filing_returns_the_id_and_the_column_it_landed_in(
        self, services: WorkflowServices, _identified: Path
    ) -> None:
        server = build_mcp_server(services)

        result = _call(server, "kanban_file_card", _brief())

        assert result["ok"] is True
        assert result["task_id"] == "proj-a:idea-draft-the-agenda"
        assert result["column"] == "detected"

    def test_the_brief_reaches_the_store(
        self, services: WorkflowServices, _identified: Path
    ) -> None:
        from openstategraph.kanban_store import kanban_store_path, read_card

        server = build_mcp_server(services)

        _call(server, "kanban_file_card", _brief(blocked_by=["proj-a:idea-other"],
                                                 agent_model="opus", agent_effort="high"))

        card = read_card(kanban_store_path(services.store.root), "proj-a:idea-draft-the-agenda")
        assert card.done_when == "A run answers with five numbered items."
        assert card.blocked_by == ("proj-a:idea-other",)
        assert (card.agent_model, card.agent_effort) == ("opus", "high")

    def test_a_judgement_is_filed_into_needs_you(
        self, services: WorkflowServices, _identified: Path
    ) -> None:
        server = build_mcp_server(services)

        result = _call(server, "kanban_file_card",
                       _brief(kind="grilling", title="One node or two"))

        assert result["column"] == "needsYou"

    def test_a_missing_brief_is_a_structured_refusal_not_a_stack_trace(
        self, services: WorkflowServices, _identified: Path
    ) -> None:
        server = build_mcp_server(services)

        result = _call(server, "kanban_file_card", _brief(done_when="  "))

        assert result["ok"] is False
        assert "done_when" in result["reason"]

    def test_a_duplicate_title_is_a_structured_refusal(
        self, services: WorkflowServices, _identified: Path
    ) -> None:
        server = build_mcp_server(services)
        _call(server, "kanban_file_card", _brief())

        result = _call(server, "kanban_file_card", _brief(story="Something else."))

        assert result["ok"] is False
        assert "already" in result["reason"]

    def test_a_project_with_no_identity_is_told_so_rather_than_crashing(
        self, services: WorkflowServices, tmp_path: Path, monkeypatch
    ) -> None:
        from openstategraph.config_file import reset_active_config

        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(tmp_path / "nothing.yaml"))
        monkeypatch.chdir(tmp_path)
        reset_active_config()
        server = build_mcp_server(services)

        result = _call(server, "kanban_file_card", _brief())

        reset_active_config()
        assert result["ok"] is False
        assert "init" in result["reason"]


class TestTheFilerIsTheServersFinding:
    """`kanban-patrol/29`'s rule, applied to the one write that creates a
    card: over MCP the caller filling in `actor` is a model, so a deployment
    that can identify the person behind the request records *them*."""

    HEADER = TestActorIsTheServersToDetermine.HEADER

    def test_a_vouched_principal_is_the_filer_whatever_the_model_passed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from openstategraph.config_file import reset_active_config
        from openstategraph.kanban_store import kanban_store_path, read_card
        from openstategraph.principal import TrustedHeaderPrincipals

        config = tmp_path / "openstategraph.yaml"
        config.write_text("project_id: proj-a\n")
        monkeypatch.setenv("OPENSTATEGRAPH_CONFIG", str(config))
        reset_active_config()
        root = tmp_path / "workflows"
        root.mkdir()
        services = WorkflowServices(
            workflows_root=root, principals=TrustedHeaderPrincipals(self.HEADER)
        )
        server = build_mcp_server(services)

        with TestActorIsTheServersToDetermine._arriving_with(
            {self.HEADER: "alice@example.com", "X-OpenStateGraph-Proxy": "1"}
        ):
            _call(server, "kanban_file_card", _brief(actor="claude"))

        reset_active_config()
        assert read_card(
            kanban_store_path(root), "proj-a:idea-draft-the-agenda"
        ).actor == "alice@example.com"
