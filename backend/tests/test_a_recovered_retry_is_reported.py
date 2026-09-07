"""A node that failed, was retried, and then succeeded says so.

`memory-and-replay` 41. The compiler gives every node
`RetryPolicy(max_attempts=3)` as a graph-assembly parameter, so a transient
provider failure is re-run — and a **recovered** retry was invisible on every
surface. The exhausted case was always reported (`node_failure_warnings`); the
recovered one is a second full model run, paid for, with nothing to read.

The layer matters. The record is written by the wrapper `build` puts around
every node callable, beside `retry_policy` itself, because retry is a
graph-assembly concern and not a node concern (`CLAUDE.md`). A test that only
exercised `retry_warnings` would stay green against a wrapper that was never
wired, which is the failure mode `skills/ticket-loop` names.
"""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from openstategraph.compile.workflow_compiler import (
    WorkflowCompiler,
    run_health,
    run_health_from_state,
)


class State(TypedDict, total=False):
    attempts: int
    outputs: dict[str, Any]
    retries: dict[str, Any]


def _node(node_id: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": "agent.llm", "data": data, "position": {"x": 0, "y": 0}}


def _document(name: str, node_id: str, **data: Any) -> dict[str, Any]:
    return {"version": 1, "name": name, "nodes": [_node(node_id, **data)], "edges": []}


def _build(document: dict[str, Any], fn: Any) -> Any:
    return WorkflowCompiler().build(document, State, lambda *_a, **_k: fn)


class TestTheCompilerRecordsARecoveredRetry:
    def test_a_node_that_fails_once_and_then_succeeds_records_the_attempt(self) -> None:
        calls = {"n": 0}

        def flaky(state: State) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return {"outputs": {"node:agent.llm-1": "done"}}

        graph = _build(_document("recovered", "node:agent.llm-1"), flaky)
        final = graph.invoke({}, {"recursion_limit": 10})

        assert calls["n"] == 2
        assert final["retries"] == {"node:agent.llm-1": 2}

    def test_a_node_that_succeeds_first_time_records_nothing(self) -> None:
        """Presence is the signal, the same shape as `forced` and `unrouted`."""

        def clean(state: State) -> dict:
            return {"outputs": {"node:agent.llm-1": "done"}}

        graph = _build(_document("clean", "node:agent.llm-1"), clean)
        final = graph.invoke({}, {"recursion_limit": 10})

        assert not final.get("retries")

    def test_a_node_that_exhausts_its_attempts_records_nothing_here(self) -> None:
        """It never returns, so there is no successful attempt to report — and
        `node_failure_warnings` already carries it on the failure half."""

        def always_fails(state: State) -> dict:
            raise ConnectionError("transient")

        graph = _build(_document("exhausted", "node:agent.llm-1"), always_fails)
        final = graph.invoke({}, {"recursion_limit": 10})

        assert not final.get("retries")

    def test_the_wrapper_leaves_a_non_dict_return_alone(self) -> None:
        """A node may return `None` (no state update). Recording must not
        invent a dict where the node deliberately wrote nothing."""

        def returns_none(state: State) -> Any:
            return None

        graph = _build(_document("none", "node:agent.llm-1"), returns_none)
        graph.invoke({}, {"recursion_limit": 10})


    def test_an_async_node_callable_is_recorded_too(self) -> None:
        """No node factory is async today. The branch exists so that the first
        one to be does not silently stop reporting, and an untested branch is
        how that promise would have been false."""
        import asyncio

        from openstategraph.compile.workflow_compiler import recording_attempts

        calls = {"n": 0}

        async def flaky(state: State) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return {"outputs": {"node:agent.llm-1": "done"}}

        assert asyncio.iscoroutinefunction(recording_attempts("node:agent.llm-1", flaky))

        graph = _build(_document("async", "node:agent.llm-1"), flaky)
        final = asyncio.run(graph.ainvoke({}, {"recursion_limit": 10}))

        assert calls["n"] == 2
        assert final["retries"] == {"node:agent.llm-1": 2}


class TestItIsReportedOnTheHalfThatCannotMoveAnExitCode:
    def test_a_recovered_retry_is_a_report_not_a_failure(self) -> None:
        health = run_health(outputs={}, retries={"node:agent.llm-1": 2})

        assert health.failures == []
        assert len(health.silent) == 1
        assert "node:agent.llm-1" in health.silent[0]
        assert "2" in health.silent[0]

    def test_the_library_door_reads_it_off_finished_state(self) -> None:
        health = run_health_from_state({"outputs": {}, "retries": {"node:agent.llm-1": 3}})

        assert health.failures == []
        assert any("node:agent.llm-1" in line for line in health.silent)

    def test_no_retries_says_nothing(self) -> None:
        assert run_health(outputs={}, retries={}).silent == []
        assert run_health(outputs={}, retries=None).silent == []


def test_it_survives_a_resume() -> None:
    """A health source nobody seeds is a half-empty terminal frame
    (`workflow-gallery` 49 / 25). `TestTheSeedCannotFallBehind` pins the rule;
    this names the key so the failure reads as this ticket's."""
    from openstategraph.api.streaming import RESUME_SEEDED_KEYS

    assert "retries" in RESUME_SEEDED_KEYS
