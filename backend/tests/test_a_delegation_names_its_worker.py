"""A deep agent's record names the worker that ran — `launch-readiness/178`.

Before this, `tool_use[node]["ran"]` carried the single entry ``task`` for every
delegation a deep agent made. Live on `ollama:gpt-oss:120b-cloud` against
`.scratch/stress-2026-08-29/workflows/stress-deep`, a run that delegated to both
declared workers recorded::

    {"deep": {"bound": ["service_registry"], "ran": ["service_registry", "task"]}}

which is the same line a run delegating to the anonymous built-in
``general-purpose`` would leave — so the one fact `compile/subagents.py` is
strict about before the run was the one fact the run did not report. ``task`` is
also `deepagents`' own tool name on a record portability guardrail 4 reserves
for ours, and `silent_node_warnings` prints `ran` back to a reader verbatim.

The messages below are the shapes that run actually produced, transcribed from
the delegating `AIMessage` and the answering `ToolMessage`, so these assertions
are about a rail this product already walks rather than about a `deepagents`
internal.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from openstategraph.compile.node_runtime import tool_report
from openstategraph.compile.workflow_compiler import silent_node_warnings, used_no_tools
from openstategraph.delegations import DELEGATION_TOOL


def _delegation(call_id: str, worker: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": DELEGATION_TOOL,
                "args": {"description": "one task", "subagent_type": worker},
                "id": call_id,
            }
        ],
    )


def _answer(call_id: str, content: str = "the worker's report") -> ToolMessage:
    return ToolMessage(
        content=content, tool_call_id=call_id, name=DELEGATION_TOOL, status="success"
    )


def _tool_call(call_id: str, name: str) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": {"service": "x"}, "id": call_id}]
    )


def _tool_answer(call_id: str, name: str) -> ToolMessage:
    return ToolMessage(content="rows", tool_call_id=call_id, name=name, status="success")


class TestTheWorkerIsNamed:
    def test_two_declared_workers_are_both_on_the_record(self) -> None:
        messages = [
            HumanMessage(content="who signs this off?"),
            _tool_call("c1", "service_registry"),
            _tool_answer("c1", "service_registry"),
            _delegation("d1", "data-classifier"),
            _answer("d1"),
            _delegation("d2", "window-checker"),
            _answer("d2"),
            AIMessage(content="the answer"),
        ]
        row = tool_report("deep", messages, ["service_registry"])["tool_use"]["deep"]
        assert row["ran"] == [
            "service_registry",
            "delegate:data-classifier",
            "delegate:window-checker",
        ]

    def test_the_vendors_tool_name_is_not_on_the_record(self) -> None:
        messages = [_delegation("d1", "data-classifier"), _answer("d1")]
        row = tool_report("deep", messages, [])["tool_use"]["deep"]
        assert DELEGATION_TOOL not in row["ran"]

    def test_the_builtin_worker_is_distinguishable_from_a_declared_one(self) -> None:
        declared = tool_report(
            "deep", [_delegation("d1", "data-classifier"), _answer("d1")], []
        )["tool_use"]["deep"]
        builtin = tool_report(
            "deep", [_delegation("d1", "general-purpose"), _answer("d1")], []
        )["tool_use"]["deep"]
        assert declared["ran"] != builtin["ran"]
        assert builtin["ran"] == ["delegate:general-purpose"]

    def test_one_worker_handed_two_tasks_is_one_entry(self) -> None:
        messages = [
            _delegation("d1", "data-classifier"),
            _answer("d1"),
            _delegation("d2", "data-classifier"),
            _answer("d2", "a second report"),
        ]
        row = tool_report("deep", messages, [])["tool_use"]["deep"]
        assert row["ran"] == ["delegate:data-classifier"]

    def test_an_ordinary_tool_is_untouched(self) -> None:
        messages = [_tool_call("c1", "service_registry"), _tool_answer("c1", "service_registry")]
        row = tool_report("deep", messages, ["service_registry"])["tool_use"]["deep"]
        assert row["ran"] == ["service_registry"]


class TestOnlyWhatActuallyReachedAWorker:
    def test_a_worker_that_does_not_exist_is_not_recorded_as_having_run(self) -> None:
        """`deepagents` answers an undeclared name with a plain sentence and
        runs nothing — a request, not a delegation."""
        messages = [
            _delegation("d1", "researcher"),
            _answer(
                "d1",
                "We cannot invoke subagent researcher because it does not exist, "
                "the only allowed types are `general-purpose`",
            ),
        ]
        row = tool_report("deep", messages, ["service_registry"])["tool_use"]["deep"]
        assert row["ran"] == []
        # And so the capability door opens on a node that reached nothing —
        # the same verdict `production-ready/98` settled for an invented tool
        # name, which under the old record was hidden behind a `task` entry.
        assert used_no_tools({"deep": row}) is True

    def test_a_delegation_that_answered_still_counts_as_a_use(self) -> None:
        row = tool_report(
            "deep",
            [_delegation("d1", "data-classifier"), _answer("d1")],
            ["service_registry"],
        )["tool_use"]["deep"]
        assert used_no_tools({"deep": row}) is False

    def test_a_call_with_no_answer_is_not_a_delegation(self) -> None:
        row = tool_report("deep", [_delegation("d1", "data-classifier")], [])["tool_use"]["deep"]
        assert row["ran"] == []

    def test_a_delegation_that_answered_unnamed_is_still_recorded(self) -> None:
        """No name is invented, and the fact is not thrown away either."""
        messages = [AIMessage(content=""), _answer("d9")]
        row = tool_report("deep", messages, [])["tool_use"]["deep"]
        assert row["ran"] == ["delegate"]


class TestWhatAReaderIsShown:
    def test_the_silence_sentence_names_the_worker_not_the_vendors_tool(self) -> None:
        row = tool_report(
            "deep", [_delegation("d1", "window-checker"), _answer("d1")], []
        )["tool_use"]["deep"]
        (sentence,) = silent_node_warnings({"deep": ""}, {"deep": row})
        assert "delegate:window-checker" in sentence
        assert "ran task" not in sentence
