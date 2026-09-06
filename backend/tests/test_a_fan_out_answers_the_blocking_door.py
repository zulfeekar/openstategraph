"""Two model-calling nodes at once, through a synchronous door.

`async-first/12`. Phase D gave every migrated node body a sync door that runs
it on a **private** loop — `asyncio.run(body(...))`, one loop per node call,
created and closed inside that call. For a graph with one model-calling node
that is indistinguishable from the old behaviour, which is why four door tests
and 5305 green ones said nothing.

For a graph that fans out it is not. A model client caches an async transport
bound to the loop that first used it — `httpx`/`httpcore` hold a connection
pool whose sockets belong to a loop — so the second node call reaches a
transport whose loop has been closed underneath it:

    RuntimeError: Event loop is closed
    During task with name 'model' ...
    During task with name 'worker_web' ...

Measured live on 2026-08-27 against `morning-brief` and a real model: `502` in
8.3 s through `CompiledWorkflow.ask`, where the same document one loop earlier
answers in 13.7 s.

**The layer matters more than the assertion here.** A unit test over
`both_doors` — call the pair's `.invoke()` twice, check the body ran twice —
stays green against a completely unfixed defect, because nothing in it holds a
resource across the two loops. So these tests drive a *compiled graph* whose
model is loop-bound, through the doors a person actually uses.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from conftest import RespondingModel


class LoopBoundModel(RespondingModel):
    """A model shaped like a real one: its transport belongs to one loop.

    The narrowest honest stand-in for `httpx.AsyncClient`. It remembers the
    running loop of its first asynchronous call and touches that loop on every
    later call, which raises exactly what a pooled socket raises when the loop
    that owned it has been closed. Nothing else about it is a fake of anything.
    """

    first_loop: Any = None
    loops_seen: list[Any] = []

    def __init__(self, default: str = "an answer") -> None:
        super().__init__([], default=default)
        object.__setattr__(self, "first_loop", None)
        object.__setattr__(self, "loops_seen", [])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        loop = asyncio.get_running_loop()
        if self.first_loop is None:
            object.__setattr__(self, "first_loop", loop)
        self.loops_seen.append(loop)
        # Long enough that the second fanned-out node call starts before the
        # first has finished — which is the whole shape under test.
        await asyncio.sleep(0.05)
        # What a pooled connection does when it is used again: reach the loop
        # it was opened on. `RuntimeError: Event loop is closed` if that loop
        # is gone.
        self.first_loop.call_soon(lambda: None)
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def fan_out_document() -> dict[str, Any]:
    """`morning-brief`'s shape, with the model calls and nothing else.

    One model-calling node, then **two more in the same superstep** — which is
    what the live document does with a supervisor and its workers, and both
    halves matter. The lead's loop is created, used and *closed* before the
    workers start, so the transport they inherit is already orphaned; and the
    two workers overlap, so no ordering between them can hide it.
    """
    return {
        "version": 3,
        "name": "fan-out",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "go"}},
            {"id": "lead", "type": "agent.llm", "position": {"x": 200, "y": 100}, "data": {}},
            {"id": "a1", "type": "agent.llm", "position": {"x": 400, "y": 0}, "data": {}},
            {"id": "a2", "type": "agent.llm", "position": {"x": 400, "y": 200}, "data": {}},
            {"id": "out1", "type": "output.formatted", "position": {"x": 600, "y": 0}, "data": {}},
        ],
        "edges": [
            {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "lead", "portId": "prompt"}},
            {"source": {"nodeId": "lead", "portId": "result"}, "target": {"nodeId": "a1", "portId": "prompt"}},
            {"source": {"nodeId": "lead", "portId": "result"}, "target": {"nodeId": "a2", "portId": "prompt"}},
            {"source": {"nodeId": "a1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
        ],
    }


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "fan-out"
    package.mkdir()
    (package / "workflow.json").write_text(json.dumps(fan_out_document()))
    return package


class TestTheLibraryDoorRunsAFanOut:
    def test_two_model_calling_nodes_answer_one_blocking_call(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_CHECKPOINT_PATH", "memory")
        from openstategraph import load_workflow

        model = LoopBoundModel()
        workflow = load_workflow(_package(tmp_path), model=model)

        result = workflow.ask("hello")

        # The user-visible half: a run that did not fail.
        assert result.failures == []
        assert result.answer
        assert result.outputs.get("a2")
        # And the cause, said directly, so a future regression names itself
        # rather than arriving as somebody else's `RuntimeError`.
        assert len(model.loops_seen) >= 3
        assert set(model.loops_seen) == {model.first_loop}


class TestTheRunLoopSurvivesACallerThatAlreadyHasOne:
    """`asyncio.run` refuses to nest, and a blocking door is reachable from a
    coroutine — a FastAPI handler that forgot `def`, an adopter's script, a
    notebook. `abc/async_doors.to_completion` already answers that, and this
    pins that the run door inherits the answer rather than growing a second
    one."""

    def test_a_run_started_from_inside_a_loop_still_answers(self) -> None:
        from openstategraph.run_doors import invoke_run

        class _Graph:
            async def ainvoke(self, payload, config=None, **extra):  # noqa: ANN001
                await asyncio.sleep(0)
                return {"seen": payload, "config": config, **extra}

        async def caller() -> Any:
            return invoke_run(_Graph(), {"question": "hi"}, {"recursion_limit": 50})

        answer = asyncio.run(caller())

        assert answer["seen"] == {"question": "hi"}
        assert answer["config"] == {"recursion_limit": 50}


class TestOneSeamAndNotFourCallSites:
    """The doors drive a run through `invoke_run`, or the next one will not.

    The same shape as `test_a_runs_diagram_opens_its_mounts.py`: four call
    sites that must each remember the right call is a defect with a fifth
    instance waiting, so the *absence* of the wrong call is the test. Parsing
    rather than grepping, because a docstring that quotes `graph.invoke(` is
    prose and this module's own header is full of it.
    """

    #: The one module that drives a graph synchronously and is not a door.
    #: `/api/workflows/chinook-assistant/ask` is the hand-built Chinook loop
    #: that predates the canvas; it is registered only when `create_app` is
    #: handed a `graph_factory`, which nothing in this package ever does — a
    #: test injects a stub. Its graph therefore holds no compiled node family
    #: and no migrated body, so it has neither the defect nor a reason to
    #: carry the fix. Named here rather than passed over silently.
    NOT_A_DOOR = {"api/routes/demo.py"}

    def test_no_module_drives_a_compiled_graph_through_invoke(self) -> None:
        import ast
        from pathlib import Path

        import openstategraph

        root = Path(openstategraph.__file__).parent
        offenders: list[str] = []
        for module in sorted(root.rglob("*.py")):
            relative = module.relative_to(root).as_posix()
            if relative in self.NOT_A_DOOR:
                continue
            for node in ast.walk(ast.parse(module.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr != "invoke":
                    continue
                target = func.value
                name = getattr(target, "id", None) or getattr(target, "attr", None)
                if name == "graph":
                    offenders.append(f"{relative}:{node.lineno}")

        assert offenders == [], (
            "a run driven by `graph.invoke()` gets one private loop per node "
            "call — use `openstategraph.run_doors.invoke_run`: " + ", ".join(offenders)
        )

    def test_each_blocking_door_uses_the_seam(self) -> None:
        from pathlib import Path

        import openstategraph

        root = Path(openstategraph.__file__).parent
        for door in ("loader.py", "api/routes/runs.py", "mcp_server.py"):
            assert "invoke_run(" in (root / door).read_text(), door
