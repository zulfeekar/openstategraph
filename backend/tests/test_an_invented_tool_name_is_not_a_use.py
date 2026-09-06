"""`production-ready` 98 — a tool the model invented counted as a tool that ran.

A live `chinook-assistant` run (`gpt-oss:120b-cloud`) asked for `execute_sql?`.
Nothing binds that name, the runtime refused it correctly and by name — and
`tool_report` filed it under `ran` anyway, because `rejected_tool_names` could
not read a refusal whose subject carries a trailing `?`: its character class
stopped at `[A-Za-z0-9_.-]`, so the sentence it wrote itself did not match.

`ran` acquired three readers on the day this was filed, and every one of them
reads it as *this node did the work*: `silent_node_warnings` (96),
`used_no_tools`/`capability_door`, and `unrun_query_claim` (95). The last will
reject a user's answer on the strength of it, so the readers are in this module
too — a test that a name is filtered out of a list is not a test that a grader
stopped mis-reporting.

The load-bearing half is `TestARealToolStillCounts`. A fix that quiets the
invented name by narrowing what counts as a use would break 96's distinction
and 95's positive control in one move.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from openstategraph.compile.node_runtime import tool_report
from openstategraph.compile.workflow_compiler import (
    rejected_tool_names,
    silent_node_warnings,
    unrun_query_claim,
    used_no_tools,
)

#: Verbatim: LangGraph's `INVALID_TOOL_NAME_ERROR_TEMPLATE`, rendered for the
#: name the live model actually asked for.
REFUSAL = (
    "Error: execute_sql? is not a valid tool, try one of "
    "[chinook_list_tables, chinook_get_table_schema, chinook_execute_sql]."
)

SQL = (
    "SELECT ar.Name, SUM(il.UnitPrice * il.Quantity) AS revenue "
    "FROM InvoiceLine il JOIN Artist ar ON il.TrackId = ar.ArtistId "
    "GROUP BY ar.Name ORDER BY revenue DESC LIMIT 10"
)

FABRICATED = (
    "**Top artists by revenue**\n\n| Artist | Revenue |\n|---|---|\n"
    "| Iron Maiden | $138.60 |\n| U2 | $105.93 |\n\n" + SQL
)


def _invented() -> list[Any]:
    """The live shape: one real tool, then a name nobody binds, carrying SQL."""
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "chinook_list_tables", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content="Artist, Album", name="chinook_list_tables", tool_call_id="c1"),
        AIMessage(
            content="",
            tool_calls=[{"name": "execute_sql?", "args": {"sql": SQL}, "id": "c2"}],
        ),
        ToolMessage(content=REFUSAL, name="execute_sql?", tool_call_id="c2", status="error"),
        AIMessage(content=FABRICATED),
    ]


def _row(messages: list[Any], bound: list[str]) -> dict[str, Any]:
    return tool_report("agent-sql", messages, bound)["tool_use"]["agent-sql"]


BOUND = ["chinook_list_tables", "chinook_get_table_schema", "chinook_execute_sql"]


class TestTheRefusalIsRead:
    def test_a_name_with_a_trailing_question_mark_is_recognised(self) -> None:
        assert rejected_tool_names(REFUSAL) == ["execute_sql?"]

    def test_prose_naming_a_tool_is_still_not_a_refusal(self) -> None:
        assert rejected_tool_names("I could use execute_sql? here if it existed.") == []


class TestTheSeam:
    def test_an_invented_name_is_not_a_use(self) -> None:
        assert _row(_invented(), BOUND)["ran"] == ["chinook_list_tables"]

    def test_the_invented_name_is_reported_as_refused(self) -> None:
        update = tool_report("agent-sql", _invented(), BOUND)
        assert update["unmet_tools"] == {"agent-sql": ["execute_sql?"]}

    def test_a_query_handed_to_nothing_was_never_sent(self) -> None:
        """`queried` is 95's evidence that the query left the building. A call
        the runtime refused never did, and recording it would clear the whole
        run's check — a miss, silently."""
        assert "queried" not in _row(_invented(), BOUND)


class TestTheReaders:
    """Every door reads the same row, so every door has to be right about it."""

    def test_the_capability_door_still_opens(self) -> None:
        """A node whose *only* call was the invented one used no tools at all,
        and the door that offers to build one must say so."""
        invented_only = _invented()[2:]
        used = tool_report("agent-sql", invented_only, BOUND)["tool_use"]
        assert used["agent-sql"]["ran"] == []
        assert used_no_tools(used) is True

    def test_a_silent_node_is_not_credited_with_the_invented_tool(self) -> None:
        used = tool_report("agent-sql", _invented(), BOUND)["tool_use"]
        (warning,) = silent_node_warnings({"agent-sql": ""}, used)
        assert "execute_sql?" not in warning

    def test_the_grader_still_rejects_the_fabricated_answer(self) -> None:
        used = tool_report("agent-sql", _invented(), BOUND)["tool_use"]
        reason = unrun_query_claim(FABRICATED, used)
        assert reason is not None
        assert "chinook_execute_sql" in reason


class TestARealToolStillCounts:
    """The inverse, and the half a careless fix breaks."""

    def _real(self) -> list[Any]:
        return [
            AIMessage(
                content="",
                tool_calls=[{"name": "chinook_execute_sql", "args": {"sql": SQL}, "id": "c1"}],
            ),
            ToolMessage(content="Iron Maiden|138.60", name="chinook_execute_sql", tool_call_id="c1"),
            AIMessage(content=FABRICATED),
        ]

    def test_a_tool_that_ran_is_still_recorded(self) -> None:
        assert _row(self._real(), BOUND)["ran"] == ["chinook_execute_sql"]

    def test_its_query_is_still_recorded(self) -> None:
        assert _row(self._real(), BOUND)["queried"] == ["chinook_execute_sql"]

    def test_the_grader_leaves_it_alone(self) -> None:
        used = tool_report("agent-sql", self._real(), BOUND)["tool_use"]
        assert unrun_query_claim(FABRICATED, used) is None

    def test_a_silent_node_that_really_ran_says_so(self) -> None:
        used = tool_report("agent-sql", self._real(), BOUND)["tool_use"]
        (warning,) = silent_node_warnings({"agent-sql": ""}, used)
        assert "chinook_execute_sql" in warning

    def test_a_tool_that_ran_and_errored_still_ran(self) -> None:
        messages = [
            AIMessage(content="", tool_calls=[{"name": "email_send", "args": {}, "id": "c1"}]),
            ToolMessage(
                content="Error: no recipient configured",
                name="email_send",
                tool_call_id="c1",
                status="error",
            ),
        ]
        assert _row(messages, ["email_send"])["ran"] == ["email_send"]

    def test_an_ambient_tool_nobody_wired_still_counts(self) -> None:
        """`bound` is canvas-wired only, so `ran` may not be filtered by it —
        an agent that reached for its memory was not stuck."""
        messages = [
            AIMessage(content="", tool_calls=[{"name": "search_memory", "args": {}, "id": "c1"}]),
            ToolMessage(content="nothing stored", name="search_memory", tool_call_id="c1"),
        ]
        assert _row(messages, [])["ran"] == ["search_memory"]


class TestTheRealDocument:
    """The layer the defect was found at: a compiled graph, a scripted analyst
    that asks for a name nobody binds."""

    def _final(self) -> dict[str, Any]:
        from langchain_core.outputs import ChatGeneration, ChatResult

        from conftest import RespondingModel
        from openstategraph.compile.node_runtime import (
            NodeRuntime,
            RunState,
            chinook_tool_registry,
        )
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        path = (
            Path(__file__).resolve().parent.parent.parent
            / "workflows"
            / "chinook-assistant"
            / "workflow.json"
        )
        document = json.loads(path.read_text())["document"]
        laps = [
            {"name": "chinook_list_tables", "args": {}, "id": "c1"},
            {"name": "execute_sql?", "args": {"sql": SQL}, "id": "c2"},
        ]

        class _Analyst(RespondingModel):
            lap: int = 0

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
                content = "\n".join(str(m.content) for m in messages)
                if "You are a grader" in content:
                    return self._reply("PASS")
                if "You are a router" in content:
                    return self._reply("data_query")
                index = object.__getattribute__(self, "lap")
                object.__setattr__(self, "lap", index + 1)
                index %= len(laps) + 1
                if index < len(laps):
                    return ChatResult(
                        generations=[
                            ChatGeneration(
                                message=AIMessage(content="", tool_calls=[laps[index]])
                            )
                        ]
                    )
                return self._reply(FABRICATED)

        runtime = NodeRuntime(
            model=_Analyst([], default=FABRICATED), tools=chinook_tool_registry()
        )
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        return graph.invoke(
            {
                "question": "top artists by revenue",
                "attempts": 0,
                "decisions": {},
                "outputs": {},
            },
            {"recursion_limit": 40},
        )

    def test_the_invented_name_is_absent_from_the_run_record(self) -> None:
        rows = self._final()["tool_use"]
        for row in rows.values():
            assert "execute_sql?" not in (row.get("ran") or [])

    def test_the_real_tool_it_did_call_is_present(self) -> None:
        rows = self._final()["tool_use"]
        assert "chinook_list_tables" in rows["agent-sql"]["ran"]
