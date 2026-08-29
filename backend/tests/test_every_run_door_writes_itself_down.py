"""Every door that starts a run writes exactly one row — `memory-and-replay/44`.

`43` landed the store and wired it to **one** door. `CompiledWorkflow.ask` and
`.resume` published a `RunRecord`, and therefore so did the CLI and a package's
own `tests/`. The three doors a *product* is served over — `POST /api/runs`,
`POST /api/runs/stream` and MCP's `run_workflow` — published nothing, because
all three call `invoke_run(...)` directly rather than going through `ask`.

So the store was populated by the door a developer uses and empty for the door
a deployment uses, which is the wrong way round for both consumers `43` names:
`guardrails/07` wants to bound spend in a deployment, and `launch-readiness/99`
wants patterns out of real traffic.

The tests come in two shapes, deliberately, and it is the same pair
`test_every_run_door_carries_identity.py` uses:

**Behaviour**, because a call to a seam is not a row. Each door is *driven* and
the store is *read back*.

**A census**, because the recurring defect is never "this door is wrong", it is
"the fix reached some doors and not others". `TestNoFifthDoorCanForget` parses
every module under `openstategraph/` for a run door and fails on one that does
not reach the seam — the shape `test_a_runs_diagram_opens_its_mounts.py`
already uses for `draw_mermaid`.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from openstategraph.run_sinks import RunRecord, read_runs, reset_run_sink_registry
from openstategraph.api.audience import Audience


def _n(i: str, t: str, **d: Any) -> dict[str, Any]:
    return {"id": i, "type": t, "data": d, "position": {"x": 0, "y": 0}}


def _document() -> dict[str, Any]:
    """Input → output. It runs, it answers, and it reaches no model at all."""
    return {
        "version": 2,
        "name": "Echo",
        "nodes": [_n("in1", "input.text"), _n("out1", "output.formatted")],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "out1", "portId": "result"},
            }
        ],
    }


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A store of this test's own, and a registry rebuilt around it.

    The process registry is memoised (it holds a sqlite handle), so pointing
    the environment variable at a new file is not enough on its own.
    """
    path = tmp_path / "runs.sqlite"
    monkeypatch.setenv("OPENSTATEGRAPH_RUN_STORE_PATH", str(path))
    reset_run_sink_registry()
    yield path
    reset_run_sink_registry()


@pytest.fixture()
def workflows_root(tmp_path: Path) -> Path:
    root = tmp_path / "workflows"
    root.mkdir()
    return root


def _rows(store: Path) -> list[RunRecord]:
    return read_runs(store, limit=50)


class TestTheBlockingHttpDoor:
    def test_a_run_over_http_is_written_down(
        self, store: Path, workflows_root: Path
    ) -> None:
        from openstategraph.api.main import create_app

        client = TestClient(create_app(workflows_root=workflows_root))
        response = client.post(
            "/api/runs",
            json={
                "workflow": _document(),
                "question": "what did the deployment do",
                "thread_id": "http-1",
            },
        )
        assert response.status_code == 200, response.text

        rows = _rows(store)
        assert len(rows) == 1, "POST /api/runs left the store empty"
        assert rows[0].thread_id == "http-1"
        assert rows[0].question == "what did the deployment do"
        assert rows[0].answer
        assert rows[0].seconds > 0


class TestTheStreamingDoor:
    def test_a_streamed_run_is_written_down(
        self, store: Path, workflows_root: Path
    ) -> None:
        """The door with no return value. Its record is assembled where its
        terminal `done` frame is, off the same folded state."""
        from openstategraph.api.main import create_app

        client = TestClient(create_app(workflows_root=workflows_root))
        response = client.post(
            "/api/runs/stream",
            json={
                "workflow": _document(),
                "question": "streamed",
                "thread_id": "sse-1",
            },
        )
        assert response.status_code == 200, response.text
        assert '"answer"' in response.text

        rows = _rows(store)
        assert len(rows) == 1, "POST /api/runs/stream left the store empty"
        assert rows[0].thread_id == "sse-1"
        assert rows[0].question == "streamed"


class TestTheMcpDoor:
    def test_a_run_over_mcp_is_written_down(
        self, store: Path, workflows_root: Path
    ) -> None:
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowRuns

        services = WorkflowServices(workflows_root=workflows_root)
        result = WorkflowRuns(services).run(
            document=_document(), question="over mcp", audience=Audience.CUSTOMER
        )
        assert result["error"] is None, result

        rows = _rows(store)
        assert len(rows) == 1, "MCP run_workflow left the store empty"
        assert rows[0].question == "over mcp"
        assert rows[0].thread_id.startswith("mcp-")


class TestOneRowPerTurn:
    """Not two. The failure mode a shared seam invites is the double-write."""

    def test_the_library_door_still_writes_exactly_one(
        self, store: Path, workflows_root: Path
    ) -> None:
        from openstategraph.loader import load_workflow

        package = workflows_root / "echo"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps({"document": _document()}))
        workflow = load_workflow(package)
        try:
            workflow.ask("through the library")
        finally:
            workflow.close()

        rows = _rows(store)
        assert len(rows) == 1
        assert rows[0].question == "through the library"

    def test_three_doors_leave_three_rows(
        self, store: Path, workflows_root: Path
    ) -> None:
        from openstategraph.api.main import create_app
        from openstategraph.api.services import WorkflowServices
        from openstategraph.mcp_server import WorkflowRuns

        client = TestClient(create_app(workflows_root=workflows_root))
        client.post("/api/runs", json={"workflow": _document(), "question": "a"})
        client.post("/api/runs/stream", json={"workflow": _document(), "question": "b"})
        WorkflowRuns(WorkflowServices(workflows_root=workflows_root)).run(
            document=_document(), question="c", audience=Audience.CUSTOMER
        )

        assert sorted(row.question for row in _rows(store)) == ["a", "b", "c"]


    def test_a_door_nested_inside_another_writes_nothing(
        self, store: Path, workflows_root: Path
    ) -> None:
        """The double-write `44` asked to be designed for, not discovered.

        `POST /api/runs` must not produce two rows if it ever starts going
        through `ask()` — and it would, because `ask` records too. Driven
        here by opening the outer turn directly, which is exactly what a door
        does; the guard is the turn, not the door.
        """
        from openstategraph.loader import load_workflow
        from openstategraph.run_journal import run_turn

        package = workflows_root / "echo"
        package.mkdir()
        (package / "workflow.json").write_text(json.dumps({"document": _document()}))
        workflow = load_workflow(package)
        try:
            with run_turn(question="the outer door asked this") as turn:
                workflow.ask("the inner door asked this")
                turn.record({"answer": "outer"})
        finally:
            workflow.close()

        rows = _rows(store)
        assert len(rows) == 1, "the nested library door wrote a second row"
        assert rows[0].question == "the outer door asked this"


class TestAStoppedRunIsARowOfItsOwn:
    """Stop, or a closed tab. See `run_journal` for why it is a `kind`."""

    def test_an_abandoned_stream_is_written_down_as_stopped(
        self, store: Path, workflows_root: Path
    ) -> None:
        import asyncio

        from openstategraph.api.streaming import _stream_run
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = _document()
        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = NodeRuntime(model=None)
        graph = compiler.build(document, RunState, runtime.factory(document))

        async def walk_out() -> None:
            frames = _stream_run(
                graph,
                {"question": "stopped halfway", "attempts": 0, "decisions": {}, "outputs": {}},
                {"configurable": {"thread_id": "sse-stop", "workflow_slug": "echo"}},
                plan,
                {},
                runtime,
                "sse-stop",
            )
            await frames.__anext__()
            await frames.aclose()

        asyncio.run(walk_out())

        rows = _rows(store)
        assert len(rows) == 1, "an abandoned run left no trace of what it spent"
        assert rows[0].kind == "stopped"
        assert rows[0].question == "stopped halfway"

    def test_it_is_not_reported_as_a_failure(
        self, store: Path, workflows_root: Path
    ) -> None:
        """A stopped run did not fail, and a failure rate read out of this
        table must not say it did."""
        import asyncio

        from openstategraph.api.streaming import _stream_run
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        document = _document()
        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        runtime = NodeRuntime(model=None)
        graph = compiler.build(document, RunState, runtime.factory(document))

        async def walk_out() -> None:
            frames = _stream_run(
                graph,
                {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
                {"configurable": {"thread_id": "t", "workflow_slug": "echo"}},
                plan,
                {},
                runtime,
                "t",
            )
            await frames.__anext__()
            await frames.aclose()

        asyncio.run(walk_out())

        assert _rows(store)[0].failed is False
        # And it is not a finished turn either: a pattern miner reading
        # `kind="run"` must not learn from half a sentence.
        assert read_runs(store, kind="run") == []


# ----------------------------------------------------- the census


def _package_root() -> Path:
    import openstategraph

    return Path(openstategraph.__file__).parent


#: Every module that starts a run, and how it hands its row to the seam.
#:
#: A module reaching `invoke_run(` is a **door**, and a door must open a
#: `run_turn(`. The streaming door drives `astream` itself and never calls
#: `invoke_run`, so it is named here rather than found — which is the point:
#: the list is what a fifth door is compared against. Nothing outside
#: `run_journal` may call `run_sinks.publish`; a second assembly is how four
#: surfaces came to draw four Mermaid diagrams.
DOORS: tuple[str, ...] = (
    "loader.py",
    "mcp_server.py",
    "api/routes/runs.py",
    "api/streaming.py",
)


def _modules(predicate: Any) -> set[str]:
    root = _package_root()
    found: set[str] = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        if predicate(tree, path):
            found.add(str(path.relative_to(root)))
    return found


def _calls(tree: ast.AST, *names: str) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute) else ""
        )
        if name in names:
            return True
    return False


class TestNoFifthDoorCanForget:
    def test_every_door_reaches_the_seam(self) -> None:
        doors = _modules(lambda tree, path: _calls(tree, "invoke_run"))
        unclassified = doors - set(DOORS)
        assert not unclassified, (
            f"{sorted(unclassified)} starts a run and this census has never "
            "been told about it — it must call `record_run`"
        )
        for module in DOORS:
            source = (_package_root() / module).read_text()
            assert "run_turn(" in source, f"{module} opens no run turn"

    def test_nothing_assembles_a_record_of_its_own(self) -> None:
        """`run_sinks.publish` is reached through `run_journal`, or the four
        doors are four assemblies again."""
        publishers = _modules(
            lambda tree, path: _calls(tree, "publish")
            and "run_sinks" in path.read_text()
        )
        assert publishers == {"run_journal.py"}, (
            f"{sorted(publishers)} publishes a run record without going "
            "through the seam"
        )
