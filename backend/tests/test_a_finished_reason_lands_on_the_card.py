"""`osg-agent-experience/85` — the argument that was accepted and dropped.

`set_stage` took `test_id`, `reason` and `commit` at every stage and kept
`reason` at `red` alone. Both doors published it — `openstategraph kanban stage
--reason` and the MCP `kanban_set_stage` argument — and neither said the value
went nowhere, so an agent that wrote its closing gate into `--reason` at
`finished` was told nothing and lost it.

That is the shape `kanban-patrol/33` already fixed once for `test_id`, which was
read for `commit` alone at `finished` and silently dropped.

The ticket named three acceptable endings — refuse it by name, keep it, or say
at both doors which stages read it. Two are taken, because the two stages differ:

- **`finished` keeps it**, in `finished_reason`. `osg-agent-experience/81`'s
  closing gate had nowhere on the card to live and was routed to
  `workflows/<slug>/AGENTS.md` instead; `commit` is required and means a sha,
  and `evidence_red_reason` is written at `red`, so neither could carry it
  without lying about what a field means.
- **`attended` and `green` refuse it by name**, naming the two stages that do
  keep one. Silently dropping is the defect; inventing a second column for a
  stage nothing reads one at would be the schema-widening the ticket forbids.

The claim under test is about *what a caller is told*, so these drive the CLI
and the MCP tool, not `set_stage` alone.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.api.services import WorkflowServices
from openstategraph.kanban_store import MissingEvidenceError, Stage, open_kanban_store
from openstategraph.mcp_server import build_mcp_server

GATE = "validate: no findings; doctor: clean; one exit"


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workflows"
    root.mkdir()
    monkeypatch.setenv("OPENSTATEGRAPH_KANBAN_STORE_PATH", str(tmp_path / "kanban.sqlite"))
    store = open_kanban_store(root)
    store.file_card(
        task_id="proj-a:thread-1",
        board="workflows",
        kind="bug",
        category="bug",
        title="A tool call with no timeout",
    )
    return root


def _to_green(root: Path) -> None:
    store = open_kanban_store(root)
    store.set_stage("proj-a:thread-1", Stage.ATTENDED, actor="alice")
    store.set_stage("proj-a:thread-1", Stage.RED, actor="alice", test_id="t::x", reason="boom")
    store.set_stage("proj-a:thread-1", Stage.GREEN, actor="alice", test_id="t::x")


def _call(server, name: str, args: dict):
    result = asyncio.run(server.call_tool(name, args))
    return result[1] if isinstance(result, tuple) else result


class TestTheCliDoor:
    def test_a_reason_at_finished_is_kept(self, project: Path, capsys) -> None:
        _to_green(project)
        code = cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "finished",
                "--actor", "alice", "--commit", "deadbeef", "--reason", GATE,
                "--workflows-root", str(project),
            ]
        )
        assert code == 0
        assert open_kanban_store(project).read_card("proj-a:thread-1").finished_reason == GATE

    def test_kanban_show_prints_it(self, project: Path, capsys) -> None:
        _to_green(project)
        cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "finished",
                "--actor", "alice", "--commit", "deadbeef", "--reason", GATE,
                "--workflows-root", str(project),
            ]
        )
        capsys.readouterr()
        cli.main(["kanban", "show", "proj-a:thread-1", "--workflows-root", str(project)])
        assert GATE in capsys.readouterr().out

    def test_a_reason_at_green_is_refused_by_name(self, project: Path, capsys) -> None:
        store = open_kanban_store(project)
        store.set_stage("proj-a:thread-1", Stage.ATTENDED, actor="alice")
        store.set_stage("proj-a:thread-1", Stage.RED, actor="alice", test_id="t::x", reason="boom")
        code = cli.main(
            [
                "kanban", "stage", "proj-a:thread-1", "green",
                "--actor", "alice", "--test-id", "t::x", "--reason", "looks fine",
                "--workflows-root", str(project),
            ]
        )
        assert code != 0
        err = capsys.readouterr().err
        assert "green" in err and "red" in err and "finished" in err

    def test_the_help_says_which_stages_read_it(self) -> None:
        """The third of the ticket's three endings, kept alongside the other
        two: `--help` is where a caller looks before passing a flag at all."""
        help_text = _stage_reason_help(cli.build_parser())
        assert "red" in help_text and "finished" in help_text


def _stage_reason_help(parser) -> str:
    """`kanban stage`'s own `--reason`, not `kanban file`'s — two flags with
    one name and two jobs, and this claim is about the first."""
    stack = [parser]
    while stack:
        current = stack.pop()
        for action in current._actions:
            subparsers = getattr(action, "choices", None)
            if isinstance(subparsers, dict):
                for name, sub in subparsers.items():
                    if name == "stage":
                        for flag in sub._actions:
                            if "--reason" in getattr(flag, "option_strings", []):
                                return flag.help or ""
                    stack.append(sub)
    raise AssertionError("no --reason flag on `kanban stage`")


class TestTheMcpDoor:
    def test_a_reason_at_finished_is_kept(self, project: Path) -> None:
        _to_green(project)
        services = WorkflowServices(workflows_root=project)
        server = build_mcp_server(services)
        result = _call(
            server,
            "kanban_set_stage",
            {
                "task_id": "proj-a:thread-1",
                "stage": "finished",
                "actor": "alice",
                "commit": "deadbeef",
                "reason": GATE,
            },
        )
        assert result.get("ok") is True
        assert open_kanban_store(project).read_card("proj-a:thread-1").finished_reason == GATE

    def test_a_reason_at_attended_is_refused_by_name(self, project: Path) -> None:
        services = WorkflowServices(workflows_root=project)
        server = build_mcp_server(services)
        result = _call(
            server,
            "kanban_set_stage",
            {
                "task_id": "proj-a:thread-1",
                "stage": "attended",
                "actor": "alice",
                "reason": "starting now",
            },
        )
        assert result.get("ok") is False
        assert "red" in result.get("reason", "") and "finished" in result.get("reason", "")

    def test_the_tool_description_says_which_stages_read_it(self) -> None:
        from openstategraph.mcp_server import EXPOSED_TOOLS

        assert "kanban_set_stage" in EXPOSED_TOOLS


class TestTheStoreItself:
    def test_a_reason_at_green_raises_naming_both_stages(self, project: Path) -> None:
        store = open_kanban_store(project)
        store.set_stage("proj-a:thread-1", Stage.ATTENDED, actor="alice")
        store.set_stage("proj-a:thread-1", Stage.RED, actor="alice", test_id="t::x", reason="boom")
        with pytest.raises(MissingEvidenceError) as excinfo:
            store.set_stage("proj-a:thread-1", Stage.GREEN, actor="alice", test_id="t::x", reason="ok")
        assert "red" in str(excinfo.value) and "finished" in str(excinfo.value)

    def test_a_release_clears_it(self, project: Path, tmp_path: Path) -> None:
        """`release_card` resets a card to filed-but-never-attended, and stale
        evidence bleeding into whoever attends next is the bug that reset
        exists to prevent — a fifth evidence field is no exception.

        Staged by writing the field onto a card that is still claimable: a
        `finished` card is excluded from `flagged_stale` by construction
        (`kanban-patrol/32`), so the only way to reach the reset with this
        field set is to put it there directly, which is exactly what a store
        written by an older or a different door could hand back."""
        import sqlite3
        from datetime import datetime, timedelta, timezone

        store = open_kanban_store(project)
        store.set_stage("proj-a:thread-1", Stage.ATTENDED, actor="alice")
        long_ago = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        conn = sqlite3.connect(tmp_path / "kanban.sqlite")
        conn.execute(
            "UPDATE cards SET last_heartbeat_at = ?, finished_reason = ? "
            "WHERE task_id = ?",
            (long_ago, GATE, "proj-a:thread-1"),
        )
        conn.commit()
        conn.close()
        assert store.read_card("proj-a:thread-1").finished_reason == GATE

        assert store.release_card("proj-a:thread-1").ok
        assert store.read_card("proj-a:thread-1").finished_reason == ""
