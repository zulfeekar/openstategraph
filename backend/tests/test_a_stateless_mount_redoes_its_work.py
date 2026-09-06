"""A stateless mount pauses — and answering it redoes everything before the gate.

`organisms-first-class` 65. `625d695` shipped `data.persistence: "stateless"`
with LangGraph's own sentence attached — a stateless subgraph "cannot
pause/resume" — and `d46ac72` measured that at *this* boundary it is false: a
mount is a closure, so the `interrupt()` a stateless child raises travels up
and is held by the **parent's** checkpointer. It pauses, and it resumes.

What this file pins is the cost that discovery uncovered, measured on the
child's own *nodes* rather than on its `invoke`, because those are different
questions and only one of them is about side effects:

| top mount's mode | pre-gate node runs, before + after the resume |
| --- | --- |
| per-invocation (default) | **1** — the child's own checkpoint picks up at the gate |
| per-thread | **1** |
| stateless | **2** — at one level and at two |

So the mount closure re-enters in every mode; only `stateless` redoes the work,
because it stored nothing to resume from. A child that drafted, called a tool
or wrote to the world before its gate does all of it a second time on the
approval path — which is what makes this a correctness question and not a bill.

**Reported, not refused.** A stateless mount with a gate inside it is a legal
document that runs, pauses, resumes and answers, so `validate`'s one question —
is this ready to run here — is honestly answered yes, and the finding is
`REPORT_ONLY` for `STALE_TOOL_DENIAL`'s reason: a report may not move an exit
code. Refusing it would break a working document over advice.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from openstategraph.compile.diagnostics import REPORT_ONLY, Finding
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.loader import CompiledWorkflow


def _n(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "position": {"x": 0, "y": 0}, "data": data}


def _e(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


#: A child that *does something* before its gate. `function.format_report` is
#: the deterministic, model-free step this suite can count — it stands in for
#: the tool call or the email that a real pre-gate step performs.
CHILD: dict[str, Any] = {
    "version": 3,
    "name": "child",
    "nodes": [
        _n("c-in", "input.text"),
        _n("c-work", "function.format_report"),
        _n("c-gate", "human.approval", message="OK from the child?"),
        _n("c-out", "output.formatted"),
    ],
    "edges": [
        _e("c-in", "text", "c-work", "candidate"),
        _e("c-work", "report", "c-gate", "candidate"),
        _e("c-gate", "approved", "c-out", "result"),
    ],
}

#: The same child with nothing to wait for — the inverse that must stay quiet.
UNGATED: dict[str, Any] = {
    "version": 3,
    "name": "ungated",
    "nodes": [
        _n("u-in", "input.text"),
        _n("u-work", "function.format_report"),
        _n("u-out", "output.formatted"),
    ],
    "edges": [
        _e("u-in", "text", "u-work", "candidate"),
        _e("u-work", "report", "u-out", "input"),
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


#: The middle document of a two-level composition; its own mount opts into
#: nothing, so the mode under measurement is always the *top* one's.
_LIBRARY = {
    "child-flow": CHILD,
    "ungated-flow": UNGATED,
    "mid-flow": _parent(None, "child-flow", name="mid"),
    "mid-ungated": _parent(None, "ungated-flow", name="mid-ungated"),
}


def _loader(slug: str) -> dict[str, Any]:
    return json.loads(json.dumps(_LIBRARY[slug]))


class _Counter:
    """How many times the child's pre-gate step actually ran.

    Wrapped around the *executor factory* rather than asserted from a state
    key: the question is how often the work happened, and a state key records
    only the last time it did. Reset on the instance is safe because the
    counter lives here and not on a class (the shadowing trap `d46ac72` hit).
    """

    def __init__(self) -> None:
        self.runs = 0
        self._original = NodeRuntime._format_report_function

    def install(self, monkeypatch: Any) -> None:
        counter = self

        def spy(runtime: Any, node_id: str, node: Any, plan: Any) -> Any:
            executor = counter._original(runtime, node_id, node, plan)

            def counted(state: Any, *args: Any, **kwargs: Any) -> Any:
                counter.runs += 1
                return executor(state, *args, **kwargs)

            return counted

        monkeypatch.setattr(NodeRuntime, "_format_report_function", spy)


def _compiled(mode: str | None, target: str) -> CompiledWorkflow:
    document = _parent(mode, target)
    runtime = NodeRuntime(document_loader=_loader)
    graph = WorkflowCompiler().build(
        document, RunState, runtime.factory(document), checkpointer=InMemorySaver()
    )
    return CompiledWorkflow(
        graph=graph,
        document=document,
        _mounts=dict(runtime.mounted_graphs),
        warnings=runtime.diagnostics.warnings(),
    )


def _warnings(mode: str | None, target: str) -> tuple[list[str], list[str]]:
    document = _parent(mode, target)
    runtime = NodeRuntime(document_loader=_loader)
    WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return runtime.diagnostics.warnings(), runtime.diagnostics.failure_warnings()


class TestWhatIsActuallyReExecuted:
    """The measurement, on the child's own step rather than on its `invoke`."""

    def test_only_a_stateless_mount_redoes_the_step_before_the_gate(
        self, monkeypatch: Any
    ) -> None:
        for mode, expected in ((None, 1), ("per-thread", 1), ("stateless", 2)):
            for depth, target in (("one", "child-flow"), ("two", "mid-flow")):
                counter = _Counter()
                counter.install(monkeypatch)
                workflow = _compiled(mode, target)
                thread = f"redo-{mode}-{depth}"
                result = workflow.ask("go", thread_id=thread)
                assert result.pause is not None, (mode, depth)
                assert counter.runs == 1, (mode, depth)
                final = workflow.resume(thread, decision="approve")
                assert final.answer, (mode, depth)
                assert counter.runs == expected, (mode, depth)


class TestWhatTheDeveloperIsToldBeforeTheRun:
    def test_a_stateless_mount_over_a_gate_is_reported_at_compile_time(self) -> None:
        for depth, target in (("one", "child-flow"), ("two", "mid-flow")):
            warnings, _ = _warnings("stateless", target)
            said = [line for line in warnings if "re-runs" in line or "second time" in line]
            assert said, (depth, warnings)
            assert "mount1" in said[0] or target in said[0], (depth, said)

    def test_the_other_two_modes_say_nothing_of_the_kind(self) -> None:
        for mode in (None, "per-invocation", "per-thread"):
            for target in ("child-flow", "mid-flow"):
                warnings, _ = _warnings(mode, target)
                assert not [line for line in warnings if "second time" in line], (
                    mode,
                    target,
                    warnings,
                )

    def test_a_stateless_mount_with_nothing_to_wait_for_is_unchanged(self) -> None:
        for target in ("ungated-flow", "mid-ungated"):
            warnings, _ = _warnings("stateless", target)
            assert not [line for line in warnings if "second time" in line], (
                target,
                warnings,
            )

    def test_it_is_a_report_and_can_never_move_an_exit_code(self) -> None:
        assert Finding.STATELESS_MOUNT_REDOES in REPORT_ONLY
        warnings, failures = _warnings("stateless", "child-flow")
        said = [line for line in warnings if "second time" in line]
        assert said
        assert not [line for line in failures if "second time" in line]


class TestTheClaimsSixtyFourLeftStanding:
    def test_a_paused_stateless_mount_still_resumes_and_answers(self) -> None:
        workflow = _compiled("stateless", "child-flow")
        workflow.ask("go", thread_id="still-resumes")
        assert workflow.resume("still-resumes", decision="approve").answer

    def test_the_asked_by_chain_still_prints_for_a_checkpointing_mount(self) -> None:
        workflow = _compiled(None, "mid-flow")
        pause = workflow.pause("nope") if False else None
        workflow.ask("go", thread_id="asked-by")
        pause = workflow.pause("asked-by")
        assert pause is not None
        assert [step["workflow"] for step in pause["mount"]] == ["mid-flow", "child-flow"]
