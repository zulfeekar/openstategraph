"""`retry_policy` does not re-run a call a tool refused. Measured, not assumed.

`launch-readiness/164`. The ticket arrived carrying a theory: every CPL MCP
failure declares `"retryable": false`, `agent1`'s `maxRetries` is blank so it
inherits the graph default of three, and a failure the tool itself calls
unretryable is therefore re-run twice more.

**It is not.** `retry_policy` is a graph-assembly parameter that re-runs a node
which *raised*; a tool returning `{"ok": false, …}` returns normally, the agent
loop hands the payload to the model, and the node completes. The measured run
the ticket cites says the same thing from the other end: fourteen
`mcp_execute_sql` calls, thirteen distinct SQL texts, thirteen request ids —
framework retry never fired.

So the finding is smaller than it looked and still real: **the thing that
repeats an unretryable call is the model**, which is why `164`'s corrective
goes on the model rail (`abc/tool_notes.Correction`) and not near
`add_node`. This file is the fact that decision rests on, so it cannot quietly
stop being true.

The layer is the point. A test that asserted `RetryPolicy(max_attempts=3)` was
passed would have been green for both readings of the question.
"""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict

from openstategraph.compile.workflow_compiler import WorkflowCompiler


class State(TypedDict, total=False):
    attempts: int
    outputs: dict[str, Any]
    retries: dict[str, Any]


FAILED = {
    "ok": False,
    "request_id": "faef3e4b0bf14805adb7a3bff0f0718c",
    "error_code": "internal_error",
    "message": "Invalid column name 'loading_time'. (207)",
    "retryable": False,
}


def _document(**data: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "name": "tool failure",
        "nodes": [
            {
                "id": "node:agent.llm-1",
                "type": "agent.llm",
                "data": data,
                "position": {"x": 0, "y": 0},
            }
        ],
        "edges": [],
    }


def _build(document: dict[str, Any], fn: Any) -> Any:
    return WorkflowCompiler().build(document, State, lambda *_a, **_k: fn)


class TestATooLFailureCostsNoRetry:
    def test_a_node_whose_tool_returned_a_failure_envelope_runs_once(self) -> None:
        calls = {"n": 0}

        def body(state: State) -> dict:
            calls["n"] += 1
            # What an agent node does when a tool answers `{"ok": false}`: it
            # hands the payload to the model and returns. Nothing raises.
            return {"outputs": {"node:agent.llm-1": FAILED["message"]}}

        graph = _build(_document(), body)
        graph.invoke({}, {"recursion_limit": 10})

        assert calls["n"] == 1

    def test_the_same_is_true_with_the_retry_count_the_owner_had_set(self) -> None:
        # `maxRetries` blank inherits the graph-wide three; setting it to
        # three explicitly is the same policy said out loud. Neither fires.
        calls = {"n": 0}

        def body(state: State) -> dict:
            calls["n"] += 1
            return {"outputs": {"node:agent.llm-1": "that did not work"}}

        graph = _build(_document(maxRetries="3"), body)
        graph.invoke({}, {"recursion_limit": 10})

        assert calls["n"] == 1

    def test_the_policy_is_wired_and_does_fire_on_a_node_that_raises(self) -> None:
        # Anti-vacuity, and the whole reason the two assertions above mean
        # anything: a graph with no retry policy at all would pass them.
        calls = {"n": 0}

        def body(state: State) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return {"outputs": {"node:agent.llm-1": "done"}}

        graph = _build(_document(maxRetries="3"), body)
        graph.invoke({}, {"recursion_limit": 10})

        assert calls["n"] == 2
