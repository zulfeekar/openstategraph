"""A node that opts into caching does not re-run — `organisms-first-class/34`.

`cache_policy` is the third graph-assembly parameter of `add_node`, beside
`retry_policy` and `timeout` which `test_node_overrides.py` already pins. It
was the only one of ticket 34's three that this compiler could carry today,
and the measurement that made it worth carrying is `4500ccc`
(`organisms-first-class/40`): a **retried or re-run mount really does redo its
whole child**, and the lever for that is a cache policy on the node.

Two halves, and LangGraph will not give you the behaviour without both:
`add_node(..., cache_policy=CachePolicy(ttl=...))` names the policy, and
`compile(cache=...)` supplies the cache it reads. A policy with no cache is a
box that does nothing, which is why the compiler passes a cache **only** when
at least one node opted in — a document that sets nothing must assemble
exactly as it did before this ticket.

The test that matters is the *behaviour* — a node invoked twice with the same
input runs once — not that the kwarg reached `add_node`. A kwarg assertion
would have stayed green against a graph compiled with no cache at all.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

from openstategraph.compile.workflow_compiler import WorkflowCompiler, _node_overrides

try:
    from langgraph.types import CachePolicy
except ImportError:  # pragma: no cover - langgraph<1.2
    CachePolicy = None  # type: ignore[misc,assignment]

_SKIP_IF_OLD = pytest.mark.skipif(
    CachePolicy is None or not hasattr(StateGraph, "set_node_defaults"),
    reason="`CachePolicy` requires `langgraph>=1.2`",
)


class State(TypedDict, total=False):
    x: int
    result: int


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def _document(name: str, **data: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "name": name,
        "nodes": [node("node:agent.llm-1", "agent.llm", **data)],
        "edges": [],
    }


class TestParsing:
    def test_blank_or_absent_means_no_cache_policy(self) -> None:
        assert "cache_policy" not in _node_overrides({})
        assert "cache_policy" not in _node_overrides({"cacheTtlSeconds": ""})
        assert "cache_policy" not in _node_overrides({"cacheTtlSeconds": "   "})

    @_SKIP_IF_OLD
    def test_a_positive_ttl_becomes_a_cache_policy(self) -> None:
        overrides = _node_overrides({"cacheTtlSeconds": "60"})
        assert isinstance(overrides["cache_policy"], CachePolicy)
        assert overrides["cache_policy"].ttl == 60

    def test_garbage_is_ignored_rather_than_raising(self) -> None:
        # Same contract as `maxRetries`/`timeoutSeconds`: the frontend's own
        # `validate` rejects these before a save, so reaching the compiler
        # with one predates validation, not a case to crash a run over.
        for bad in ("not-a-number", "0", "-30", "1.5"):
            assert "cache_policy" not in _node_overrides({"cacheTtlSeconds": bad})


class TestTheBehaviourItBuys:
    @_SKIP_IF_OLD
    def test_a_cached_node_invoked_twice_with_the_same_input_runs_once(self) -> None:
        calls = {"count": 0}

        def expensive(state: State) -> dict:
            calls["count"] += 1
            return {"result": state.get("x", 0) * 2}

        graph = WorkflowCompiler().build(
            _document("cached", cacheTtlSeconds="60"),
            State,
            lambda *_: expensive,
        )

        assert graph.invoke({"x": 5}, {"recursion_limit": 10})["result"] == 10
        assert graph.invoke({"x": 5}, {"recursion_limit": 10})["result"] == 10

        assert calls["count"] == 1, "the second run must be served from the cache"

    @_SKIP_IF_OLD
    def test_a_different_input_is_a_different_key_and_does_run(self) -> None:
        """Tolerance is never a licence to serve the wrong answer."""
        calls = {"count": 0}

        def expensive(state: State) -> dict:
            calls["count"] += 1
            return {"result": state.get("x", 0) * 2}

        graph = WorkflowCompiler().build(
            _document("cached", cacheTtlSeconds="60"),
            State,
            lambda *_: expensive,
        )

        assert graph.invoke({"x": 5}, {"recursion_limit": 10})["result"] == 10
        assert graph.invoke({"x": 7}, {"recursion_limit": 10})["result"] == 14

        assert calls["count"] == 2

    @_SKIP_IF_OLD
    def test_without_the_field_the_same_input_re_runs_every_time(self) -> None:
        """The inverse. Caching is opt-in; nothing may start caching silently."""
        calls = {"count": 0}

        def expensive(state: State) -> dict:
            calls["count"] += 1
            return {"result": state.get("x", 0) * 2}

        graph = WorkflowCompiler().build(
            _document("uncached"), State, lambda *_: expensive
        )

        graph.invoke({"x": 5}, {"recursion_limit": 10})
        graph.invoke({"x": 5}, {"recursion_limit": 10})

        assert calls["count"] == 2


class TestADocumentThatOptsOutIsAssembledExactlyAsBefore:
    """A cache is supplied **only** when somebody asked for one.

    `compile(cache=...)` on every graph would attach an unbounded in-process
    dict to workflows that never opted in — a memory cost, and a behaviour
    change, bought by nothing.
    """

    def _spy_compile_kwargs(self, document: dict[str, Any]) -> dict[str, Any]:
        import openstategraph.compile.workflow_compiler as wc

        seen: dict[str, Any] = {}
        real_compile = wc.StateGraph.compile

        def spy(self_: Any, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return real_compile(self_, **kwargs)

        wc.StateGraph.compile = spy  # type: ignore[method-assign]
        try:
            WorkflowCompiler().build(document, State, lambda *_: (lambda s: {}))
        finally:
            wc.StateGraph.compile = real_compile  # type: ignore[method-assign]
        return seen

    def test_no_cache_is_passed_when_no_node_opted_in(self) -> None:
        assert self._spy_compile_kwargs(_document("plain")).get("cache") is None

    @_SKIP_IF_OLD
    def test_a_cache_is_passed_when_one_node_opted_in(self) -> None:
        seen = self._spy_compile_kwargs(_document("opted", cacheTtlSeconds="60"))
        assert seen.get("cache") is not None
