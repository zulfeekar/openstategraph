"""`@task` around a mount's invoke was priced and refused — this is the price.

`organisms-first-class/40`. The ticket read: a `retry_policy` firing on a
mount, or a resume landing inside one, re-runs the whole child, so wrap the
expensive inner steps as `@task` and let the checkpointer skip the completed
ones.

Half of that premise is true and the other half is not, and neither half
survives contact with what `@task` actually does **in the installed
LangGraph** (1.2.10). Measured, in this order:

1. **A retry on a mount does re-run the whole child.** Two attempts, two runs
   of the child's agent. That much of the ticket is real.
2. **`@task` does not change it.** The identical measurement with the mount's
   invoke wrapped in `@task`, under a checkpointer, is *also* two runs.
   `docs-langchain` is precise about which boundary the cache serves —
   `graph-api.mdx` § *Using tasks in nodes*: "Task results are checkpointed
   when the graph uses a checkpointer, so **resuming a thread** can skip
   completed task work inside the node." A retry attempt is not a resumed
   thread: it happens inside one superstep, before any checkpoint is written,
   so there is nothing to restore from. So on the ticket's own headline case
   the construct buys exactly nothing.
3. **A resume landing inside a mount does *not* re-run the child.** This is
   where `@task` would pay, and it is already paid for — by
   `checkpoint_ns`. The child is invoked from inside the parent's node and
   inherits the parent's config, checkpointer included, so it is checkpointed
   under its own namespace and its finished nodes are restored like anybody
   else's. Pausing at a `human.approval` *inside a mounted child* and
   resuming runs the child's agent **once in total**, not twice.

So the construct is refused, and the cost of adopting it would have been real
rather than nominal: `graph-api.mdx` warns that a node calling tasks takes on
"stricter determinism rules ... changing task or interrupt order in code
before the resume point can mismatch cached values", and `_subgraph`'s body
chooses its child question by branching over router versus content sources —
an order that is not statically fixed. It would also move the child's failure
behind a future, so an exception from a mounted package would surface from
`.result()` rather than from the invoke that caused it.

The second half of the ticket — discovered-function calls — needs no
measurement and gets none: `_function` runs exactly one call in its node and
turns a raised exception into downstream text rather than a failure, so there
is neither a second operation to skip nor a retry to skip it on.

`test_the_refused_construct_is_absent` is the part that stops this being a
story: `@task` cannot appear in the runtime without turning this file red and
sending the next reader to this docstring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import task
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy

from openstategraph.compile.node_runtime import NodeRuntime, RunState, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan, WorkflowCompiler


def _node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


#: A child that costs a model call, so "did it re-run" is a number and not a guess.
CHILD = {
    "version": 1,
    "name": "child",
    "nodes": [
        _node("c:in", "input.text"),
        _node("c:a1", "agent.llm"),
        _node("c:out", "output.formatted"),
    ],
    "edges": [
        _edge("c:in", "text", "c:a1", "prompt"),
        _edge("c:a1", "result", "c:out", "result"),
    ],
}

#: The same child, pausing for a person half way through — the resume case.
CHILD_THAT_PAUSES = {
    "version": 1,
    "name": "child",
    "nodes": [
        _node("c:in", "input.text"),
        _node("c:a1", "agent.llm"),
        _node("c:hold", "human.approval", message="OK to publish?"),
        _node("c:out", "output.formatted"),
    ],
    "edges": [
        _edge("c:in", "text", "c:a1", "prompt"),
        _edge("c:a1", "result", "c:hold", "candidate"),
        _edge("c:hold", "approved", "c:out", "result"),
    ],
}

PARENT = {
    "version": 1,
    "name": "parent",
    "nodes": [
        _node("p:in", "input.text"),
        _node("p:mount", "workflow.subgraph", workflow="child"),
        _node("p:out", "output.formatted"),
    ],
    "edges": [
        _edge("p:in", "text", "p:mount", "task"),
        _edge("p:mount", "result", "p:out", "result"),
    ],
}


class _CountingModel(GenericFakeChatModel):
    """A scripted model that records how many answers it was asked for."""

    calls: int = 0

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return super()._generate(*args, **kwargs)


def _mount_runner(model: Any, child: dict[str, Any] = CHILD) -> Any:
    """The real `_subgraph` closure for a parent mounting `child`."""
    runtime = NodeRuntime(
        services=RuntimeServices(model=model, document_loader=lambda _slug: child)
    )
    return runtime._subgraph(
        "p:mount",
        _node("p:mount", "workflow.subgraph", workflow="child"),
        CompiledPlan(),
    )


def _graph_whose_mount_fails_once(runner: Any, *, wrap_in_task: bool, retries: int) -> Any:
    """A one-node graph whose mount node raises after the child has returned.

    The failure is placed *after* the child's work on purpose: that is the
    only arrangement in which "the child already finished, does it run again"
    is a question with an answer.
    """
    tasked = task(runner)
    remaining = {"failures": 1}

    def mount(state: RunState) -> dict[str, Any]:
        out = tasked(state).result() if wrap_in_task else runner(state)
        if remaining["failures"]:
            remaining["failures"] -= 1
            raise RuntimeError("the parent's node fails after the child returned")
        return out

    builder: Any = StateGraph(RunState)
    builder.add_node(
        "mount",
        mount,
        retry_policy=RetryPolicy(
            max_attempts=retries, initial_interval=0.001, retry_on=Exception
        ),
    )
    builder.add_edge(START, "mount")
    builder.add_edge("mount", END)
    return builder.compile(checkpointer=InMemorySaver())


def _start(graph: Any, thread: str) -> Any:
    return graph.invoke(
        {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}},
        {"configurable": {"thread_id": thread}},
    )


class TestWhatARetryActuallyCosts:
    def test_a_retry_on_a_mount_re_runs_the_whole_child(self) -> None:
        """The ticket's premise, measured rather than assumed. It is true."""
        model = _CountingModel(messages=iter(["A"] * 8))
        graph = _graph_whose_mount_fails_once(
            _mount_runner(model), wrap_in_task=False, retries=3
        )

        final = _start(graph, "retry-plain")

        assert final["answer"] == "A"
        assert model.calls == 2

    def test_a_task_boundary_does_not_change_that(self) -> None:
        """And the proposed fix, measured. It buys nothing on this path.

        Same failure, same retry, same checkpointer — the child's agent still
        runs twice with the invoke wrapped in `@task`, because a retry attempt
        is not a resumed thread and no checkpoint was written between them.
        This is the assertion that would go red if a future LangGraph started
        caching task results across retry attempts, which is exactly when the
        refusal below deserves to be reopened.
        """
        model = _CountingModel(messages=iter(["A"] * 8))
        graph = _graph_whose_mount_fails_once(
            _mount_runner(model), wrap_in_task=True, retries=3
        )

        final = _start(graph, "retry-tasked")

        assert final["answer"] == "A"
        assert model.calls == 2

    def test_a_run_with_no_retry_runs_the_child_exactly_once(self) -> None:
        """The inverse: nothing about the mount is wasteful on its own."""
        model = _CountingModel(messages=iter(["A"] * 8))
        runner = _mount_runner(model)

        assert runner({"question": "q", "outputs": {}})["answer"] == "A"
        assert model.calls == 1


class TestTheResumeHalfIsAlreadyPaidFor:
    def test_a_resume_inside_a_mount_does_not_re_run_the_child(self) -> None:
        """The half `@task` was meant to fix, and it is already fixed.

        The child inherits the parent's checkpointer through the ambient
        config and is checkpointed under its own `checkpoint_ns`, so the agent
        it already ran before the pause is restored rather than repeated: one
        model call across a pause *and* a resume, not two.
        """
        model = _CountingModel(messages=iter(["A"] * 8))
        runtime = NodeRuntime(
            services=RuntimeServices(model=model, document_loader=lambda _s: CHILD_THAT_PAUSES)
        )
        graph = WorkflowCompiler().build(
            PARENT, RunState, runtime.factory(PARENT), checkpointer=InMemorySaver()
        )
        config = {"configurable": {"thread_id": "paused-mount"}}

        paused = graph.invoke(
            {"question": "q", "attempts": 0, "decisions": {}, "outputs": {}}, config
        )
        assert "__interrupt__" in paused
        assert model.calls == 1

        final = graph.invoke(Command(resume={"decision": "approve"}), config)

        assert final["answer"] == "A"
        assert model.calls == 1


class TestTheInversesTheRefusalMustNotDisturb:
    def test_a_mounts_diagnostics_still_arrive_exactly_once(self) -> None:
        """`workflow-gallery` 75's absorption, unchanged and un-duplicated."""
        broken_child = {
            "version": 1,
            "name": "child",
            "nodes": [
                _node("c:in", "input.text"),
                _node("c:mystery", "agent.raect"),
                _node("c:out", "output.formatted"),
            ],
            "edges": [
                _edge("c:in", "text", "c:mystery", "prompt"),
                _edge("c:mystery", "result", "c:out", "result"),
            ],
        }
        runtime = NodeRuntime(
            services=RuntimeServices(model=None, document_loader=lambda _s: broken_child)
        )
        runtime._subgraph(
            "p:mount",
            _node("p:mount", "workflow.subgraph", workflow="child"),
            CompiledPlan(),
        )

        inside = [w for w in runtime.diagnostics.warnings() if "agent.raect" in w]
        assert len(inside) == 1

    def test_the_refused_construct_is_absent(self) -> None:
        """The pin. `@task` is not in the runtime, and may not arrive quietly.

        Adding it turns this red, and a reader sent here finds the measurement
        that says why it was refused — rather than re-deriving it, or worse,
        adopting it on the strength of the ticket's paraphrase.
        """
        source = Path(NodeRuntime.__module__.replace(".", "/") + ".py")
        runtime_source = (Path(__file__).resolve().parents[1] / source).read_text()

        assert "langgraph.func" not in runtime_source
        assert "@task" not in runtime_source
