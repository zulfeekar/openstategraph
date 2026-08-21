"""`production-ready` 95 — an answer that cites a query it never sent.

`chinook-assistant`'s analyst answers *"top artists by revenue"* with a ten-row
table and a `SELECT` beside it, having listed the tables, read two schemas, and
never called `chinook_execute_sql`. Eight live runs on `gpt-oss:120b-cloud`
reproduced the skipped query eight times out of eight. The figures are right to
the cent because Chinook is a famous public fixture, which is exactly what
parametric recall produces.

The model grader *did* catch it, on the run that produced a table — and it was
right, not guessing. This pins the same rejection as a **fact**, reached with no
model call, off the run's own `tool_use`.

The load-bearing half of this module is `TestTheLegitimateAnswersLeftAlone`.
The narrowness is the safety, and it is the part that regresses.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from openstategraph.compile.node_runtime import (
    NodeRuntime,
    RunState,
    tool_report,
)
from openstategraph.compile.workflow_compiler import (
    WorkflowCompiler,
    unrun_query_claim,
)

from conftest import RespondingModel  # noqa: F401

#: What the live analyst produced: a SELECT it never sent, beside figures it
#: could only have recalled.
FABRICATED = (
    "**Top 10 artists by revenue**\n\n"
    "| Artist | Revenue (USD) |\n"
    "|---|---|\n"
    "| Iron Maiden | $138.60 |\n"
    "| U2 | $105.93 |\n"
    "| Metallica | $90.09 |\n\n"
    "SELECT ar.Name, SUM(il.UnitPrice * il.Quantity) AS revenue "
    "FROM InvoiceLine il JOIN Track t ON il.TrackId = t.TrackId "
    "JOIN Album al ON t.AlbumId = al.AlbumId "
    "JOIN Artist ar ON al.ArtistId = ar.ArtistId "
    "GROUP BY ar.Name ORDER BY revenue DESC LIMIT 10"
)

#: The live shape, verbatim: three bound, two run, the query never sent.
LIVE_TOOL_USE = {
    "agent-sql": {
        "bound": [
            "chinook_list_tables",
            "chinook_get_table_schema",
            "chinook_execute_sql",
        ],
        "ran": ["chinook_list_tables", "chinook_get_table_schema"],
    }
}


def _investigated(**extra: Any) -> dict[str, Any]:
    row = dict(LIVE_TOOL_USE["agent-sql"])
    row.update(extra)
    return {"agent-sql": row}


class TestTheCheckItself:
    def test_the_live_shape_is_rejected(self) -> None:
        assert unrun_query_claim(FABRICATED, LIVE_TOOL_USE) is not None

    def test_the_reason_names_the_query_and_the_node(self) -> None:
        reason = unrun_query_claim(FABRICATED, LIVE_TOOL_USE) or ""
        assert "agent-sql" in reason
        assert "chinook_execute_sql" in reason


class TestTheLegitimateAnswersLeftAlone:
    """Twelve answers a widening would reject. None may trip the check.

    Two of them exist because a mutation found them: replacing the SQL pattern
    with a bare `\\bselect\\b` left the other ten green.
    """

    def test_a_run_that_actually_sent_the_query_is_untouched(self) -> None:
        """The positive control. Same text, same tools, the query was sent."""
        used = _investigated(
            ran=[*LIVE_TOOL_USE["agent-sql"]["ran"], "chinook_execute_sql"],
            queried=["chinook_execute_sql"],
        )
        assert unrun_query_claim(FABRICATED, used) is None

    def test_an_honest_decline_that_shows_an_example_query(self) -> None:
        candidate = (
            "I cannot answer this: no database tool is reachable from this "
            "workflow. The query you would need is "
            "SELECT ar.Name FROM Artist ar ORDER BY ar.Name."
        )
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None

    def test_an_agent_explaining_how_a_join_works(self) -> None:
        candidate = (
            "A join matches rows across two tables. Writing "
            "SELECT t.Name FROM Track t JOIN Album a ON t.AlbumId = a.AlbumId "
            "walks every track and pairs it with its album."
        )
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None

    def test_a_quoted_table_schema_with_column_widths(self) -> None:
        candidate = (
            "The Artist table has 2 columns: ArtistId INTEGER NOT NULL, "
            "Name NVARCHAR(120). The Album table has 3 columns and 347 rows."
        )
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None

    def test_a_writer_answer_full_of_figures_and_no_sql(self) -> None:
        candidate = "Revenue rose 12% to $2,328.60 across 412 invoices in 2013."
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None

    def test_a_node_that_ran_nothing_at_all_is_someone_elses_door(self) -> None:
        """`used_no_tools`/`capability_door` owns this shape and always has.

        A node that touched none of its tools is a *capability* report — the
        same `ran`-versus-`bound` split `production-ready` 96 drew. This check
        speaks only about a node that investigated and stopped short.
        """
        used = {"agent-sql": {"bound": LIVE_TOOL_USE["agent-sql"]["bound"], "ran": []}}
        assert unrun_query_claim(FABRICATED, used) is None

    def test_a_node_that_used_every_tool_it_had(self) -> None:
        used = {
            "agent-sql": {
                "bound": ["chinook_list_tables"],
                "ran": ["chinook_list_tables"],
            }
        }
        assert unrun_query_claim(FABRICATED, used) is None

    def test_a_second_node_that_did_send_a_query_clears_the_run(self) -> None:
        used = {
            **LIVE_TOOL_USE,
            "agent-check": {
                "bound": ["chinook_execute_sql"],
                "ran": ["chinook_execute_sql"],
                "queried": ["chinook_execute_sql"],
            },
        }
        assert unrun_query_claim(FABRICATED, used) is None

    def test_a_workflow_document_quoted_back_as_prose(self) -> None:
        """`workflow-architect` answers *with an entire workflow document*."""
        candidate = (
            '{"nodes": [{"id": "n1", "type": "agent.llm", "data": '
            '{"rules": "Answer with SELECT Name FROM Artist"}}, '
            '{"id": "n2", "type": "route.grader"}], "edges": [], "version": 2}'
        )
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None

    def test_the_english_verb_select_beside_real_figures(self) -> None:
        """The case a bare `\\bselect\\b` would reject.

        Added because the mutation check found it: widening the pattern to the
        word alone left every other test in this class green, which means the
        set was not yet pinning what the pattern is *for*.
        """
        candidate = (
            "Select 2 of these playlists to compare. Their revenue differs "
            "by $12.40 against $9.75, so the choice is not arbitrary."
        )
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None

    def test_the_preposition_from_beside_real_figures(self) -> None:
        """The other half of the pattern, pinned the same way."""
        candidate = (
            "Revenue from Iron Maiden reached $138.60 and from U2 $105.93 "
            "after the refund was applied, a fall of 24.6% on the quarter."
        )
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None

    def test_the_word_select_used_as_english(self) -> None:
        candidate = (
            "Select any 3 of the 12 playlists and I will summarise them; "
            "4 of them are far from complete."
        )
        assert unrun_query_claim(candidate, LIVE_TOOL_USE) is None


class TestToolReportRecordsWhatWasQueried:
    """`queried` is the fact the check turns on, and it is name-free.

    Nothing here matches a tool *name* against a pattern — the tool that ran a
    query is the one a SELECT was handed to.
    """

    def test_a_select_in_a_tool_call_is_recorded(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "chinook_execute_sql",
                        "args": {"sql": "SELECT Name FROM Artist LIMIT 5"},
                        "id": "c1",
                    }
                ],
            ),
            ToolMessage(content="rows", name="chinook_execute_sql", tool_call_id="c1"),
        ]
        row = tool_report("n", messages, ["chinook_execute_sql"])["tool_use"]["n"]
        assert row["queried"] == ["chinook_execute_sql"]

    def test_a_call_carrying_no_query_records_nothing(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "chinook_list_tables", "args": {}, "id": "c1"}
                ],
            ),
            ToolMessage(content="Artist", name="chinook_list_tables", tool_call_id="c1"),
        ]
        row = tool_report("n", messages, ["chinook_list_tables"])["tool_use"]["n"]
        assert "queried" not in row

    def test_a_tool_of_any_name_counts(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "warehouse",
                        "args": {"q": "select 1 from dual"},
                        "id": "c1",
                    }
                ],
            ),
            ToolMessage(content="1", name="warehouse", tool_call_id="c1"),
        ]
        row = tool_report("n", messages, ["warehouse"])["tool_use"]["n"]
        assert row["queried"] == ["warehouse"]


class TestTheRealDocumentRejectsItWithoutAModel:
    """The layer the defect lives at: a compiled graph, a scripted analyst.

    A test that a string trips a predicate is not a test that an agent citing
    evidence it never gathered is caught. This drives the flagship's real saved
    document, with an agent whose loop reads two schemas and then writes the
    fabricated table.
    """

    def _run(self) -> dict[str, Any]:
        import json
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent.parent
            / "workflows"
            / "chinook-assistant"
            / "workflow.json"
        )
        document = json.loads(path.read_text())["document"]

        calls: list[str] = []
        # The analyst's loop, scripted to do exactly what the live one did:
        # list the tables, read a schema, then write the table from memory.
        # Real tool calls, so `tool_report` records a real `ran` list — a
        # scripted model that calls nothing produces a different shape and
        # would let this pass for the wrong reason.
        laps: list[dict[str, Any]] = [
            {"name": "chinook_list_tables", "args": {}, "id": "c1"},
            {
                "name": "chinook_get_table_schema",
                "args": {"table_name": "Artist"},
                "id": "c2",
            },
        ]

        class _Analyst(RespondingModel):
            lap: int = 0

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
                from langchain_core.outputs import ChatGeneration, ChatResult

                content = "\n".join(str(m.content) for m in messages)
                if "You are a grader" in content:
                    calls.append(content)
                    return self._reply("PASS")
                if "You are a router" in content:
                    return self._reply("data_query")
                index = object.__getattribute__(self, "lap")
                object.__setattr__(self, "lap", index + 1)
                # Cycled, not consumed: 73's live diagnosis found that three
                # attempts bought three *identical* first attempts, so every
                # lap of the revise loop investigates and stops short exactly
                # as the first one did.
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

        model = _Analyst([], default=FABRICATED)
        from openstategraph.compile.node_runtime import chinook_tool_registry

        runtime = NodeRuntime(model=model, tools=chinook_tool_registry())
        graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
        final = graph.invoke(
            {
                "question": "top artists by revenue",
                "attempts": 0,
                "decisions": {},
                "outputs": {},
            },
            {"recursion_limit": 40},
        )
        final["_grader_calls"] = calls
        return final

    def test_the_grader_rejects_it(self) -> None:
        final = self._run()
        assert final["verdicts"]["grader-sql"]["verdict"] == "revise"
        # Never passed on its merits — the budget ran out and the pass was
        # forced, which is a different thing and says so.
        assert final.get("forced")

    def test_no_model_was_asked_for_the_verdict(self) -> None:
        """Not one grading call, on any lap of the loop."""
        final = self._run()
        assert final["_grader_calls"] == []

    def test_the_trace_names_the_check(self) -> None:
        final = self._run()
        assert final["verdicts"]["grader-sql"]["check"] == "unrun_query"

    def test_the_reason_tells_the_agent_what_to_do(self) -> None:
        reason = self._run()["verdicts"]["grader-sql"]["reason"]
        assert "chinook_execute_sql" in reason
