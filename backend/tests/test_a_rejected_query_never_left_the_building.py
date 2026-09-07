""".. `production-ready` 100 — a query the tool rejected still counted as sent.

`production-ready` 95 records `queried` off **call arguments**, and any
`queried` anywhere clears `unrun_query_claim` for the whole run. 98 removed the
invented name from it: a tool nobody binds never sent anything.

There is a third shape, and it was measured with a `ToolNode` rather than
imagined. A model calls a **real, bound** tool with the **wrong argument name**.
LangGraph validates the arguments *before* it invokes the tool, and answers with
a `ToolMessage` carrying the tool's **own** name and `status="error"`:

    name='chinook_execute_sql' status='error'
    content="Error invoking tool 'chinook_execute_sql' with kwargs {'sql': ...}
             with error:\\n query: Field required\\n Please fix the error and
             try again."

`ran` records it, and that is right — the tool exists and the loop reached it.
`queried` recorded it too, and that is wrong: the body never executed, so no
query ever reached the database, and the run's fabricated answer went
unchallenged.

The load-bearing half is `TestAToolThatReallyRanStillCounts`. "Errored" and
"never executed" are not the same thing at the message layer, and a fix that
drops every `status="error"` from `queried` re-breaks
`the-agent-asks-for-what-it-cannot-get` 01 — a tool that ran a query and *then*
failed did send it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from openstategraph.compile.node_runtime import tool_report
from openstategraph.compile.workflow_compiler import (
    arguments_were_rejected,
    unrun_query_claim,
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

BOUND = ["chinook_list_tables", "chinook_get_table_schema", "chinook_execute_sql"]

#: Verbatim from a real `ToolNode` run — see `TestTheMeasurement`, which
#: regenerates it rather than trusting this constant.
INVOCATION_ERROR = (
    "Error invoking tool 'chinook_execute_sql' with kwargs "
    "{'sql': 'SELECT 1 FROM Artist'} with error:\n"
    " query: Field required\n"
    " Please fix the error and try again."
)


def _row(messages: list[Any], bound: list[str]) -> dict[str, Any]:
    return tool_report("agent-sql", messages, bound)["tool_use"]["agent-sql"]


def _rejected_arguments() -> list[Any]:
    """The live shape: one real tool used, then the real SQL tool called wrong."""
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "chinook_list_tables", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content="Artist, Album", name="chinook_list_tables", tool_call_id="c1"),
        AIMessage(
            content="",
            tool_calls=[{"name": "chinook_execute_sql", "args": {"sql": SQL}, "id": "c2"}],
        ),
        ToolMessage(
            content=INVOCATION_ERROR,
            name="chinook_execute_sql",
            tool_call_id="c2",
            status="error",
        ),
        AIMessage(content=FABRICATED),
    ]


class TestTheMeasurement:
    """A real `ToolNode`, so the shape under test is the library's, not ours."""

    def _tool_message(self, args: dict[str, Any]) -> Any:
        from langchain_core.tools import tool
        from langgraph.graph import START, MessagesState, StateGraph
        from langgraph.prebuilt import ToolNode
        from pydantic import BaseModel

        class Args(BaseModel):
            query: str

        @tool("chinook_execute_sql", args_schema=Args)
        def chinook_execute_sql(query: str) -> str:
            """Run a SELECT."""
            return "Iron Maiden|138.60"

        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode([chinook_execute_sql]))
        graph.add_edge(START, "tools")
        call = AIMessage(
            content="",
            tool_calls=[
                {"name": "chinook_execute_sql", "args": args, "id": "c1", "type": "tool_call"}
            ],
        )
        return graph.compile().invoke({"messages": [call]})["messages"][-1]

    def test_bad_arguments_come_back_under_the_tools_own_name(self) -> None:
        message = self._tool_message({"sql": "SELECT 1 FROM Artist"})
        assert message.name == "chinook_execute_sql"
        assert message.status == "error"
        assert arguments_were_rejected(message.content, message.name) is True

    def test_good_arguments_are_not_a_rejection(self) -> None:
        message = self._tool_message({"query": "SELECT 1 FROM Artist"})
        assert message.status == "success"
        assert arguments_were_rejected(message.content, message.name) is False


class TestTheDetector:
    def test_the_measured_sentence_is_read(self) -> None:
        assert arguments_were_rejected(INVOCATION_ERROR, "chinook_execute_sql") is True

    def test_it_is_about_the_tool_that_answered(self) -> None:
        """Strict in trusting: the sentence names its own subject, and a
        message from some *other* tool quoting it is not a rejection of this
        one."""
        assert arguments_were_rejected(INVOCATION_ERROR, "chinook_list_tables") is False

    def test_a_tool_that_ran_and_failed_is_not_a_rejection(self) -> None:
        """The load-bearing negative. LangGraph says *executing* for a body
        that ran and threw, and *invoking* for arguments it never accepted."""
        executed = (
            "Error executing tool 'chinook_execute_sql' with kwargs "
            "{'query': 'SELECT 1'} with error:\n no such table: Artist\n"
            " Please fix the error and try again."
        )
        assert arguments_were_rejected(executed, "chinook_execute_sql") is False

    def test_ordinary_prose_is_left_alone(self) -> None:
        assert arguments_were_rejected("Error: the database is offline.", "x") is False
        assert arguments_were_rejected(None, "x") is False

    def test_an_answer_quoting_the_sentence_is_not_a_rejection(self) -> None:
        """This product prints machinery as prose constantly. The sentence has
        to be the message, not something inside it."""
        quoted = "I hit this earlier:\n\n> " + INVOCATION_ERROR + "\n\nSo I gave up."
        assert arguments_were_rejected(quoted, "chinook_execute_sql") is False


class TestTheSeam:
    def test_the_tool_still_counts_as_reached(self) -> None:
        """98's sentence for `ran` is unchanged: the tool exists, was invoked,
        and answered. Only `queried` is narrower."""
        assert _row(_rejected_arguments(), BOUND)["ran"] == [
            "chinook_list_tables",
            "chinook_execute_sql",
        ]

    def test_a_query_the_tool_never_accepted_was_never_sent(self) -> None:
        assert "queried" not in _row(_rejected_arguments(), BOUND)

    def test_nothing_was_refused(self) -> None:
        """`unmet_tools` is about a name nobody binds. This name is bound."""
        assert "unmet_tools" not in tool_report("agent-sql", _rejected_arguments(), BOUND)

    def test_a_second_call_that_the_tool_did_accept_still_counts(self) -> None:
        """The rejection is per **call**, not per tool — the model's next lap
        usually fixes the argument name, and that query really was sent."""
        messages = _rejected_arguments()[:-1] + [
            AIMessage(
                content="",
                tool_calls=[{"name": "chinook_execute_sql", "args": {"query": SQL}, "id": "c3"}],
            ),
            ToolMessage(
                content="Iron Maiden|138.60", name="chinook_execute_sql", tool_call_id="c3"
            ),
            AIMessage(content=FABRICATED),
        ]
        assert _row(messages, BOUND)["queried"] == ["chinook_execute_sql"]


class TestTheGrader:
    """`queried` exists for exactly one reader, so the reader is the test."""

    def test_the_fabricating_run_is_now_rejected(self) -> None:
        used = tool_report("agent-sql", _rejected_arguments(), BOUND)["tool_use"]
        reason = unrun_query_claim(FABRICATED, used)
        assert reason is not None
        assert "chinook_execute_sql" in reason


class TestAToolThatReallyRanStillCounts:
    """95's positive control and 01's error-is-data rule, both intact."""

    def _real(self) -> list[Any]:
        return [
            AIMessage(
                content="",
                tool_calls=[{"name": "chinook_execute_sql", "args": {"query": SQL}, "id": "c1"}],
            ),
            ToolMessage(
                content="Iron Maiden|138.60", name="chinook_execute_sql", tool_call_id="c1"
            ),
            AIMessage(content=FABRICATED),
        ]

    def test_a_genuine_query_is_still_recorded(self) -> None:
        assert _row(self._real(), BOUND)["queried"] == ["chinook_execute_sql"]

    def test_the_grader_still_leaves_a_genuine_query_alone(self) -> None:
        used = tool_report("agent-sql", self._real(), BOUND)["tool_use"]
        assert unrun_query_claim(FABRICATED, used) is None

    def test_a_query_that_ran_and_then_failed_still_counts(self) -> None:
        """**The whole ticket.** The body executed, the database was reached,
        and the statement was rejected by SQLite rather than by Pydantic. That
        query left the building."""
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"name": "chinook_execute_sql", "args": {"query": SQL}, "id": "c1"}],
            ),
            ToolMessage(
                content="Error: no such column: ar.Revenue",
                name="chinook_execute_sql",
                tool_call_id="c1",
                status="error",
            ),
            AIMessage(content=FABRICATED),
        ]
        row = _row(messages, BOUND)
        assert row["ran"] == ["chinook_execute_sql"]
        assert row["queried"] == ["chinook_execute_sql"]

    def test_a_dangling_call_is_dropped_by_98_not_by_this_fix(self) -> None:
        """Recorded rather than changed. A call nothing ever answered has no
        `ToolMessage`, so `ran` is empty and 98's filter already drops it —
        `unaccepted` never sees it. Pinned here because it is the one place
        where this area errs towards accusing rather than missing, and a
        reader arriving at the asymmetry deserves to find it named."""
        messages = [
            AIMessage(
                content="",
                tool_calls=[{"name": "chinook_execute_sql", "args": {"query": SQL}, "id": "c1"}],
            ),
        ]
        row = _row(messages, BOUND)
        assert row["ran"] == []
        assert "queried" not in row


class TestTheRealDocument:
    """The layer the defect lives at: a compiled graph, a scripted analyst that
    calls the real SQL tool with the argument name it does not have."""

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
            # `sql`, not `query` — a real tool, arguments it will not accept.
            {"name": "chinook_execute_sql", "args": {"sql": SQL}, "id": "c2"},
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

    def test_no_node_claims_to_have_sent_a_query(self) -> None:
        rows = self._final()["tool_use"]
        assert rows, "the run recorded no tool use at all"
        for row in rows.values():
            assert not row.get("queried")

    def test_the_tool_is_still_recorded_as_reached(self) -> None:
        rows = self._final()["tool_use"]
        assert "chinook_execute_sql" in rows["agent-sql"]["ran"]
