"""Per-node retry/timeout overrides — the P1 "per-node retry/timeout UI" gap.

`set_node_defaults` already gives every node the same graph-wide retry
policy (`workflow_compiler.py`). This is the per-node *override* the
canvas's `maxRetries`/`timeoutSeconds` fields expose (declared once in
`ModelRegistry.defineNode` on the TS side, inherited by every executable
node type per CLAUDE.md's "a graph-assembly concern, not a node concern"
rule). LangGraph's own docs are explicit that per-node `add_node` kwargs
take precedence over `set_node_defaults` — this pins that the compiler
actually passes them, not just that the values parse.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

try:
    from langgraph.types import TimeoutPolicy
except ImportError:
    TimeoutPolicy = None  # type: ignore[misc,assignment]

#: `set_node_defaults` and `TimeoutPolicy` require `langgraph>=1.2`.
_HAS_SET_NODE_DEFAULTS = hasattr(StateGraph, "set_node_defaults")
_SKIP_IF_OLD = pytest.mark.skipif(
    not _HAS_SET_NODE_DEFAULTS,
    reason="`set_node_defaults`/`TimeoutPolicy` require `langgraph>=1.2`",
)
from typing_extensions import TypedDict

from dyflow.compile.workflow_compiler import WorkflowCompiler, _node_overrides


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, sp: str, dst: str, dp: str) -> dict[str, Any]:
    return {"source": {"nodeId": src, "portId": sp}, "target": {"nodeId": dst, "portId": dp}}


class TestNodeOverridesParsing:
    def test_blank_fields_produce_no_override_at_all(self) -> None:
        assert _node_overrides({}) == {}
        assert _node_overrides({"maxRetries": "", "timeoutSeconds": ""}) == {}

    def test_a_valid_max_retries_becomes_a_retry_policy(self) -> None:
        overrides = _node_overrides({"maxRetries": "1"})
        assert isinstance(overrides["retry_policy"], RetryPolicy)
        assert overrides["retry_policy"].max_attempts == 1
        assert "timeout" not in overrides

    @_SKIP_IF_OLD
    def test_a_valid_timeout_becomes_a_timeout_policy(self) -> None:
        overrides = _node_overrides({"timeoutSeconds": "30"})
        assert isinstance(overrides["timeout"], TimeoutPolicy)
        assert overrides["timeout"].run_timeout == 30.0
        assert "retry_policy" not in overrides

    @_SKIP_IF_OLD
    def test_both_together(self) -> None:
        overrides = _node_overrides({"maxRetries": "5", "timeoutSeconds": "12.5"})
        assert overrides["retry_policy"].max_attempts == 5
        assert overrides["timeout"].run_timeout == 12.5

    def test_garbage_values_are_ignored_rather_than_raising(self) -> None:
        # The frontend's own field validation already rejects these before a
        # document can be saved — reaching the compiler with one predates
        # that, not a case worth crashing a run over.
        assert _node_overrides({"maxRetries": "not-a-number"}) == {}
        assert _node_overrides({"maxRetries": "0"}) == {}
        assert _node_overrides({"maxRetries": "-3"}) == {}
        assert _node_overrides({"timeoutSeconds": "0"}) == {}
        assert _node_overrides({"timeoutSeconds": "-1"}) == {}


class State(TypedDict, total=False):
    attempts: int


class TestCompilerAppliesTheOverride:
    @_SKIP_IF_OLD
    def test_a_node_with_maxretries_1_is_invoked_exactly_once_before_erroring(
        self,
    ) -> None:
        """Proves the override actually reaches `add_node`, not just that it parses.

        A node that always raises normally gets the graph-wide default of 3
        attempts (`build`'s own `set_node_defaults`). With `maxRetries: "1"`
        on this specific node, it must be invoked exactly once before the
        graph-wide `error_handler` catches it and the run completes instead
        of raising.
        """
        calls = {"count": 0}

        def always_fails(state: State) -> dict:
            calls["count"] += 1
            raise ConnectionError("boom")

        document = {
            "version": 1,
            "name": "override-proof",
            "nodes": [node("node:agent.llm-1", "agent.llm", maxRetries="1")],
            "edges": [],
        }

        def factory(node_id: str, node_data: dict, plan: Any) -> Any:
            return always_fails

        graph = WorkflowCompiler().build(document, State, factory)
        # Does not raise: the graph-wide error_handler recovers once retries
        # (here, exactly one attempt) are exhausted.
        graph.invoke({}, {"recursion_limit": 10})

        assert calls["count"] == 1

    @_SKIP_IF_OLD
    def test_without_an_override_the_graph_wide_default_of_three_attempts_applies(
        self,
    ) -> None:
        calls = {"count": 0}

        def always_fails(state: State) -> dict:
            calls["count"] += 1
            raise ConnectionError("boom")

        document = {
            "version": 1,
            "name": "no-override",
            "nodes": [node("node:agent.llm-1", "agent.llm")],
            "edges": [],
        }

        def factory(node_id: str, node_data: dict, plan: Any) -> Any:
            return always_fails

        graph = WorkflowCompiler().build(document, State, factory)
        graph.invoke({}, {"recursion_limit": 10})

        assert calls["count"] == 3
