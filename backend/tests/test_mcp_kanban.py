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
