"""A pause raised *inside* a mounted workflow says which workflow raised it.

`organisms-first-class` 64, and the mechanism the ticket named is refused here
rather than merely unused — measured before anything changed, on a parent whose
one real step mounts a child that stops at a `human.approval` gate, driven to a
real `interrupt()` through a real `WorkflowCompiler` with an `InMemorySaver`
(the `4877401` pattern), at **one level and at two**, in all three persistence
modes:

| what was asked | answer |
| --- | --- |
| `get_state(config, subgraphs=True).tasks[0].state` | **`None`**, every mode, both depths |
| `.tasks[0].interrupts` | present — the pause itself propagates |
| the child's own checkpoint | **in the saver**, under a namespace prefixed by the mount's graph node name |

So the ticket's *"read the child's state with `subgraphs=True`"* cannot be
done here at all, and not by accident: the installed 1.2.10
`langgraph/use-subgraphs.mdx` §"View subgraph state" notes that viewing
subgraph state requires LangGraph to **statically discover** the subgraph, and
that it does not work "when a subgraph is called inside a tool function or
other indirection". A mount is a closure over the child's `invoke()`
(`compile/composition.py` makes the identical argument about `xray`), which is
exactly that indirection. `subgraphs=True` will not answer for a mount until a
mount stops being a closure, which is a compile-seam change nothing here wants.

What *is* reachable is better anyway, because it needs no second query: the
pause propagates to **every** level, and the deepest checkpoint namespace
carrying a pending `__interrupt__` is the document that actually raised it.
That namespace is the mount path, so a paused caller can be told which mounted
package is asking — one `list` on the checkpointer the workflow already holds,
and only for a workflow that has mounts at all.

Stateless is the honest exception and is pinned as one: `checkpointer=False`
writes no child checkpoint, so a stateless mount at one level leaves no path to
report. It still pauses and still resumes — through the *parent's*
checkpointer — which is a fact about this boundary the docs' "cannot
pause/resume" sentence does not describe, and which is filed as `65` rather
than asserted as a feature here.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.paused_mount import mount_path, paused_mount_chain
from openstategraph.cli import mount_chain_line, pause_report_lines
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.loader import CompiledWorkflow


def _n(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "position": {"x": 0, "y": 0}, "data": data}


def _e(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


#: A child whose one step is a gate: input -> human.approval -> output.
CHILD: dict[str, Any] = {
    "version": 3,
    "name": "child",
    "nodes": [
        _n("c-in", "input.text"),
        _n("c-gate", "human.approval", message="OK from the child?"),
        _n("c-out", "output.formatted"),
    ],
    "edges": [
        _e("c-in", "text", "c-gate", "candidate"),
        _e("c-gate", "approved", "c-out", "result"),
    ],
}


def _parent(mode: str | None, target: str, name: str = "parent") -> dict[str, Any]:
    data: dict[str, Any] = {"workflow": target}
    if mode is not None:
        data["persistence"] = mode
    return {
        "version": 3,
        "name": name,
        "nodes": [
            _n("in1", "input.text"),
            _n("mount1", "workflow.subgraph", **data),
            _n("out1", "output.formatted"),
        ],
        "edges": [
            _e("in1", "text", "mount1", "input"),
            _e("mount1", "output", "out1", "input"),
        ],
    }


#: The middle document of a two-level composition. Its own mount opts into
#: nothing, so the depth being measured is always the *top* mount's mode.
MID: dict[str, Any] = _parent(None, "child-flow", name="mid")

_LIBRARY = {"child-flow": CHILD, "mid-flow": MID}


def _loader(slug: str) -> dict[str, Any]:
    return json.loads(json.dumps(_LIBRARY[slug]))


def _paused(mode: str | None, target: str, thread_id: str) -> CompiledWorkflow:
    """A real parent, mounted and driven to a real interrupt inside the child."""
    document = _parent(mode, target)
    runtime = NodeRuntime(document_loader=_loader)
    graph = WorkflowCompiler().build(
        document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
    )
    workflow = CompiledWorkflow(
        graph=graph, document=document, _mounts=dict(runtime.mounted_graphs)
    )
    graph.invoke(
        {"question": "go", "attempts": 0, "decisions": {}, "outputs": {}},
        {"configurable": {"thread_id": thread_id}},
    )
    return workflow


class TestTheMechanismTheTicketNamedDoesNotAnswerForAMount:
    """`subgraphs=True` is refused with the measurement, not left implied."""

    def test_a_mounts_task_carries_an_interrupt_but_no_child_state(self) -> None:
        for mode in (None, "per-thread", "stateless"):
            for depth, target in (("one", "child-flow"), ("two", "mid-flow")):
                thread = f"subgraphs-{mode}-{depth}"
                workflow = _paused(mode, target, thread)
                state = workflow.graph.get_state(
                    {"configurable": {"thread_id": thread}}, subgraphs=True
                )
                assert state.next == ("mount1",), (mode, depth)
                tasks = list(state.tasks or ())
                assert len(tasks) == 1, (mode, depth)
                assert tasks[0].interrupts, (mode, depth)
                # The whole refusal, in one assertion, six times.
                assert getattr(tasks[0], "state", None) is None, (mode, depth)


class TestWhatThePausedCallerIsTold:
    def test_a_pause_one_level_down_names_the_mounted_package(self) -> None:
        workflow = _paused(None, "child-flow", "named-one")
        pause = workflow.pause("named-one")
        assert pause is not None
        assert pause["message"] == "OK from the child?"
        assert pause["mount"] == [{"node": "mount1", "workflow": "child-flow"}]

    def test_a_pause_two_levels_down_names_both_documents_in_order(self) -> None:
        workflow = _paused(None, "mid-flow", "named-two")
        pause = workflow.pause("named-two")
        assert pause is not None
        assert pause["mount"] == [
            {"node": "mount1", "workflow": "mid-flow"},
            {"node": "mount1", "workflow": "child-flow"},
        ]

    def test_a_per_thread_mount_is_named_exactly_as_a_per_invocation_one_is(self) -> None:
        for depth, target, expected in (
            ("one", "child-flow", ["child-flow"]),
            ("two", "mid-flow", ["mid-flow", "child-flow"]),
        ):
            workflow = _paused("per-thread", target, f"per-thread-{depth}")
            pause = workflow.pause(f"per-thread-{depth}")
            assert pause is not None
            assert [step["workflow"] for step in pause["mount"]] == expected, depth

    def test_the_gate_is_still_answered_and_the_run_still_finishes(self) -> None:
        """`07ffbc3`'s resume is untouched by anything above."""
        workflow = _paused(None, "child-flow", "resume-still-works")
        final = workflow.resume("resume-still-works", decision="approve")
        assert final.answer == "go"


class TestBothDoorsOntoOnePauseSayTheSameThing:
    """`run` prints `RunResult.pause`; `resume` prints `pause()`. One phrase."""

    def _workflow(self, target: str) -> CompiledWorkflow:
        document = _parent(None, target)
        runtime = NodeRuntime(document_loader=_loader)
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
        )
        return CompiledWorkflow(
            graph=graph, document=document, _mounts=dict(runtime.mounted_graphs)
        )

    def test_the_pause_a_run_returns_carries_the_chain_too(self) -> None:
        workflow = self._workflow("mid-flow")
        result = workflow.ask("go", thread_id="run-door")
        assert result.pause is not None
        assert [step["workflow"] for step in result.pause["mount"]] == [
            "mid-flow",
            "child-flow",
        ]

    def test_the_run_report_names_the_package_that_asked(self) -> None:
        workflow = self._workflow("child-flow")
        result = workflow.ask("go", thread_id="report-door")
        lines = pause_report_lines(result, package="pkg", thread_id="report-door")
        assert "  asked by: child-flow (a workflow this one mounts)" in lines

    def test_two_levels_read_outermost_first(self) -> None:
        workflow = self._workflow("mid-flow")
        result = workflow.ask("go", thread_id="report-two")
        lines = pause_report_lines(result, package="pkg", thread_id="report-two")
        assert (
            "  asked by: mid-flow -> child-flow "
            "(workflows this one mounts, outermost first)" in lines
        )

    def test_a_gate_in_the_document_a_person_ran_says_nothing_extra(self) -> None:
        assert mount_chain_line({"message": "OK?"}) == ""
        assert mount_chain_line(None) == ""

    def test_a_chain_of_unnamed_mounts_claims_no_package(self) -> None:
        """A mount the compiler could not resolve has no slug to print."""
        assert mount_chain_line({"mount": [{"node": "mount1", "workflow": ""}]}) == ""


class TestTheCasesThatMustNotPayAndMustNotLie:
    def test_a_stateless_mount_leaves_no_path_and_claims_none(self) -> None:
        """`checkpointer=False` writes no child checkpoint. Inapplicable, not broken."""
        workflow = _paused("stateless", "child-flow", "stateless-one")
        pause = workflow.pause("stateless-one")
        assert pause is not None
        assert pause["message"] == "OK from the child?"
        assert "mount" not in pause

    def test_a_workflow_with_no_mounts_asks_the_checkpointer_nothing(self) -> None:
        """The inverse that keeps this free for every document without a mount."""
        document = {
            "version": 3,
            "name": "flat",
            "nodes": [
                _n("in1", "input.text"),
                _n("gate", "human.approval", message="OK?"),
                _n("out1", "output.formatted"),
            ],
            "edges": [
                _e("in1", "text", "gate", "candidate"),
                _e("gate", "approved", "out1", "result"),
            ],
        }
        runtime = NodeRuntime()
        saver = _CountingSaver()
        graph = WorkflowCompiler().build(
            document, RunState, runtime.factory(document), checkpointer=saver
        )
        graph.invoke(
            {"question": "go", "attempts": 0, "decisions": {}, "outputs": {}},
            {"configurable": {"thread_id": "flat-1"}},
        )
        workflow = CompiledWorkflow(graph=graph, document=document, _mounts={})
        _CountingSaver.lists = 0
        pause = workflow.pause("flat-1")
        assert pause is not None and "mount" not in pause
        assert _CountingSaver.lists == 0

    def test_a_finished_run_is_not_paused_and_pays_nothing(self) -> None:
        workflow = _paused(None, "child-flow", "finished-1")
        workflow.resume("finished-1", decision="approve")
        assert workflow.pause("finished-1") is None


class TestTheDerivationItself:
    def test_a_namespace_is_read_as_the_chain_of_mount_nodes(self) -> None:
        assert mount_path("") == ()
        assert mount_path("mount1:9c31dd34") == ("mount1",)
        assert mount_path("mount1") == ("mount1",)  # per-thread has no invocation suffix
        assert mount_path("mount1:aa|other:bb") == ("mount1", "other")

    def test_a_checkpointer_that_cannot_enumerate_says_nothing_rather_than_raising(
        self,
    ) -> None:
        class _Refusing:
            def list(self, config: Any, **kwargs: Any) -> Any:
                raise RuntimeError("this saver does not enumerate")

        assert paused_mount_chain(_Refusing(), "t", {"mount1": object()}) == []

    def test_a_deeper_namespace_that_is_not_waiting_is_not_the_pause(self) -> None:
        """The chain is the deepest *interrupted* level, not the deepest level.

        A composition can hold a mount that ran deeper and finished beside one
        that is still waiting — the pause is the one with the pending
        `__interrupt__` write, and reading depth alone would name the wrong
        document with complete confidence.
        """

        class _Tuple:
            def __init__(self, namespace: str, interrupted: bool) -> None:
                self.config = {"configurable": {"checkpoint_ns": namespace}}
                self.pending_writes = (
                    [("task", "__interrupt__", None)] if interrupted else [("task", "answer", "x")]
                )

        class _Saver:
            def list(self, config: Any, **kwargs: Any) -> Any:
                return [
                    _Tuple("deep:1|deeper:2", interrupted=False),
                    _Tuple("waiting:3", interrupted=True),
                ]

        class _Mounted:
            def __init__(self, slug: str, mounts: dict[str, Any] | None = None) -> None:
                self.slug = slug
                self.mounts = mounts or {}

        chain = paused_mount_chain(
            _Saver(),
            "t",
            {
                "deep": _Mounted("deep-flow", {"deeper": _Mounted("deeper-flow")}),
                "waiting": _Mounted("waiting-flow"),
            },
        )
        assert chain == [{"node": "waiting", "workflow": "waiting-flow"}]

    def test_a_workflow_with_no_mounts_is_an_empty_chain_without_asking(self) -> None:
        """The guard that keeps every un-mounted document paying nothing."""

        class _Silent:
            calls = 0

            def list(self, config: Any, **kwargs: Any) -> Any:
                self.calls += 1
                return []

        saver = _Silent()
        assert paused_mount_chain(saver, "t", {}) == []
        # Asserted on a count rather than on a raise: `paused_mount_chain`
        # tolerates a saver that cannot enumerate, so a saver that shouts
        # would be swallowed and the guard would look pinned when it is not.
        assert saver.calls == 0

    def test_no_checkpointer_at_all_is_an_empty_chain(self) -> None:
        assert paused_mount_chain(None, "t", {"mount1": object()}) == []


class _CountingSaver(InMemorySaver):
    """An `InMemorySaver` that counts the one call this change could add."""

    lists = 0

    def list(self, config: Any, **kwargs: Any) -> Any:
        type(self).lists += 1
        return super().list(config, **kwargs)
