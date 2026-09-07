"""Phase D, third family: a mount awaits the child workflow it runs.

`async-first/06`. A mount is the longest step this compiler can schedule —
it is a whole other workflow run as one node, so the work abandoned when a run
is stopped inside one is *everything the child had left to do*. That makes it
the third family by duration and the third to migrate.

It is also the one whose migration is not obviously safe, because a mount is a
closure over the child's `invoke()` rather than a LangGraph subgraph
(`compile/composition.py`), and three things ride on that closure:

- **the child's checkpointer**, which it inherits from the parent through the
  ambient config — the seam that broke on the synchronous door when `_agent`
  went async, and is why the async bridge now sits at the compiler;
- **`interrupt()`**, which a child raises and the *parent's* checkpointer
  holds (`organisms-first-class` 64/65). A pause that stopped crossing an
  `await` would take every gated mount with it;
- **the step budget and the `GraphRecursionError` translation**, which are
  read and raised around that one call.

So this file asserts the ordinary case, then each of those three, rather than
trusting that a mount is just another node.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler


def _n(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "position": {"x": 0, "y": 0}, "data": data}


def _e(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


CHILD: dict[str, Any] = {
    "version": 3,
    "name": "child",
    "nodes": [
        _n("c-in", "input.text"),
        _n("c-work", "function.format_report", reportTitle="Child report"),
        _n("c-out", "output.formatted"),
    ],
    "edges": [
        _e("c-in", "text", "c-work", "candidate"),
        _e("c-work", "report", "c-out", "result"),
    ],
}

GATED_CHILD: dict[str, Any] = {
    "version": 3,
    "name": "gated",
    "nodes": [
        _n("g-in", "input.text"),
        _n("g-gate", "human.approval", message="OK from the child?"),
        _n("g-out", "output.formatted"),
    ],
    "edges": [
        _e("g-in", "text", "g-gate", "candidate"),
        _e("g-gate", "approved", "g-out", "result"),
    ],
}

_LIBRARY = {"child-flow": CHILD, "gated-flow": GATED_CHILD}


def _loader(slug: str) -> dict[str, Any]:
    return json.loads(json.dumps(_LIBRARY[slug]))


def _parent(target: str) -> dict[str, Any]:
    return {
        "version": 3,
        "name": "parent",
        "nodes": [
            _n("in1", "input.text"),
            _n("mount1", "workflow.subgraph", workflow=target),
            _n("out1", "output.formatted"),
        ],
        "edges": [
            _e("in1", "text", "mount1", "input"),
            _e("mount1", "output", "out1", "input"),
        ],
    }


def _runtime() -> NodeRuntime:
    return NodeRuntime(model=None, document_loader=_loader)


class TestTheMountBodyIsACoroutine:
    def test_the_factory_returns_an_async_def(self) -> None:
        node = _n("mount1", "workflow.subgraph", workflow="child-flow")
        run = _runtime()._subgraph("mount1", node, CompiledPlan())
        assert inspect.iscoroutinefunction(run)

    def test_an_unresolved_mount_still_answers_without_touching_a_loop(self) -> None:
        """The early return has no I/O in it, and must not have grown any."""
        node = _n("mount1", "workflow.subgraph", workflow="")
        run = _runtime()._subgraph("mount1", node, CompiledPlan())
        assert asyncio.run(run(RunState(question="q"))) == {"outputs": {"mount1": ""}}  # type: ignore[typeddict-item]

    def test_the_child_runs_and_its_answer_comes_back(self) -> None:
        document = _parent("child-flow")
        runtime = _runtime()
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

        result = asyncio.run(graph.ainvoke({"messages": [], "question": "hello"}))

        assert "hello" in str(result["outputs"]["mount1"])
        # And what happened *inside* the mount is still folded up, prefixed.
        assert any(key.startswith("mount1/") for key in result.get("nested_outputs") or {})


class TestTheThingsThatRideOnTheClosure:
    def test_a_gate_inside_a_mount_still_pauses_and_still_resumes(self) -> None:
        """`interrupt()` is raised by the child and held by the *parent's*
        checkpointer, because a mount is a closure and not a subgraph. If that
        stopped crossing the `await`, every gated mount would break at once and
        no other assertion here would notice."""
        from langgraph.types import Command

        document = _parent("gated-flow")
        runtime = _runtime()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "paused-thread"}}

        paused = asyncio.run(
            graph.ainvoke({"messages": [], "question": "please review"}, config)
        )
        assert "__interrupt__" in paused

        resumed = asyncio.run(
            graph.ainvoke(Command(resume={"decision": "approve"}), config)
        )
        assert "__interrupt__" not in resumed
        assert "please review" in str(resumed["outputs"]["mount1"])

    def test_the_same_pause_still_works_through_the_synchronous_door(self) -> None:
        """Both doors, because a mount is reached from the blocking
        `/api/runs` and the MCP server as well as from the stream."""
        from langgraph.types import Command

        document = _parent("gated-flow")
        runtime = _runtime()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "sync-thread"}}

        paused = graph.invoke({"messages": [], "question": "please review"}, config)
        assert "__interrupt__" in paused

        resumed = graph.invoke(Command(resume={"decision": "approve"}), config)
        assert "__interrupt__" not in resumed

    def test_a_child_that_cannot_settle_still_says_so_in_our_words(
        self, monkeypatch
    ) -> None:
        """`GraphRecursionError` is caught around the child's call and
        translated at the boundary; the `await` must not let the library's own
        advice — raise a limit this product's copy tells you not to raise —
        escape to the caller.

        Driven by making the *child graph* raise, rather than by building a
        document that loops: the assertion is about the `except` around one
        call, and a document that has to actually exhaust a budget would go red
        for reasons that are not this.
        """
        from langgraph.errors import GraphRecursionError

        from openstategraph.compile import workflow_compiler as compiler_module
        from openstategraph.errors import StepBudgetExhausted

        real_build = compiler_module.WorkflowCompiler.build

        class _NeverSettles:
            async def ainvoke(self, *_a: Any, **_k: Any) -> Any:
                raise GraphRecursionError("Recursion limit of 6 reached")

            def invoke(self, *_a: Any, **_k: Any) -> Any:
                raise GraphRecursionError("Recursion limit of 6 reached")

        def build(self: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
            if (document or {}).get("name") == "child":
                return _NeverSettles()
            return real_build(self, document, *args, **kwargs)

        monkeypatch.setattr(compiler_module.WorkflowCompiler, "build", build)

        node = _n("mount1", "workflow.subgraph", workflow="child-flow")
        run = _runtime()._subgraph("mount1", node, CompiledPlan())

        raised: list[BaseException] = []
        try:
            asyncio.run(run(RunState(question="hello")))  # type: ignore[typeddict-item]
        except BaseException as exc:  # noqa: BLE001 — the point is which one
            raised.append(exc)

        assert raised, "a child that cannot settle produced no error at all"
        assert isinstance(raised[0], StepBudgetExhausted)
        assert "step budget" in str(raised[0])
