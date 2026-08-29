"""launch-readiness 165 — a bare `COUNT(*)` is a count of rows, and nothing else.

A run published *"there are **1,454,449 dark vessels**"*. The SQL behind it was

    SELECT COUNT(*) AS dark_vessels_count FROM sm.area_counts_dark_v1r0 WHERE dark = 1

and `sm.area_counts_dark_v1r0` is a geofence × day × IMO fact table: 2,208,572
rows over 10,096 vessels. The true distinct dark-vessel count is 6,119. The
published figure was ~219x too large and carried a confident gloss.

**Why `151` cannot catch this, and the sentence is the whole reason this module
exists:** `1,454,449` *was* retrieved — the query really returned it — so
`numbers_in_prose` finds it grounded and passes, correctly. `151` checks a
number's **provenance**; this number's provenance is impeccable and its
**meaning** is wrong. `UNDECLARED_FALLBACK`, 151's compile-time half, is silent
for an equally correct reason: the CPL MCP tools declare `open_world = False`
because they *are* the run's store.

So this is a different axis, and it is answerable without any declaration at
all, because it is SQL semantics rather than schema knowledge: `COUNT(*)`
returns a number of **rows**. Whether those rows happen to be one-per-vessel is
a property of the table that only the table can declare — which is why this
check never says *"that number is wrong"*. It says *"you counted rows; say so,
or count the entity"*, and both repairs are one lap away.

**Both directions are pinned here, because `133` is the counter-example this
project already paid for.** *"How many rows are in this table"* is a real
question with a real `COUNT(*)` behind it, and a gate that fires on it is a gate
people route around.
"""

from __future__ import annotations

from decimal import Decimal

from langchain_core.messages import AIMessage, ToolMessage

from openstategraph.grounded_numbers import numbers_in as numbers_in_of
from openstategraph.counted_rows import (
    check_row_counts_in_prose,
    counts_rows_only,
    mislabelled_row_counts,
    row_counts_retrieved,
)


DARK_COUNT_SQL = "SELECT COUNT(*) AS dark_vessels_count FROM sm.area_counts_dark_v1r0 WHERE dark = 1"


def _run(sql: str, result: str) -> dict:
    """One agent lap: a tool call carrying SQL, and the row it came back with."""
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "mcp_execute_sql", "args": {"sql": sql}, "id": "c1"}],
            ),
            ToolMessage(content=result, tool_call_id="c1", name="mcp_execute_sql"),
        ],
        "outputs": {},
        "question": "How many dark vessels departed Mongstad last month?",
    }


# ------------------------------------------------------------------ #
# What makes a statement a row count — read off the SQL, no schema
# ------------------------------------------------------------------ #


class TestWhatCountsRowsAndNothingElse:
    def test_the_published_query_counts_rows(self) -> None:
        assert counts_rows_only(DARK_COUNT_SQL) is True

    def test_count_one_is_the_same_statement_spelled_differently(self) -> None:
        assert counts_rows_only("SELECT COUNT(1) FROM sm.area_counts_dark_v1r0") is True

    def test_counting_an_entity_is_not_counting_rows(self) -> None:
        """The repair, and it must take the check off the answer."""
        assert counts_rows_only("SELECT COUNT(DISTINCT imo) FROM sm.area_counts_dark_v1r0") is False

    def test_any_distinct_anywhere_puts_the_statement_out_of_reach(self) -> None:
        """`COUNT(*)` over a de-duplicated subquery is an entity count, and this
        module will not try to prove which. Silent is the honest answer."""
        assert (
            counts_rows_only("SELECT COUNT(*) FROM (SELECT DISTINCT imo FROM sm.a) t") is False
        )

    def test_a_grouped_count_is_a_breakdown_not_a_headline(self) -> None:
        assert counts_rows_only("SELECT geofence, COUNT(*) FROM sm.a GROUP BY geofence") is False

    def test_a_query_that_does_not_count_is_not_this_modules_business(self) -> None:
        assert counts_rows_only("SELECT imo FROM sm.area_counts_dark_v1r0") is False

    def test_a_sum_of_a_declared_quantity_column_is_left_alone(self) -> None:
        """`dark_fleet`'s own declared idiom. It must never be reported."""
        assert counts_rows_only("SELECT SUM(dark_vessel_count) FROM sm.area_counts_dark_v1r0") is False


# ------------------------------------------------------------------ #
# Pairing the statement with what it returned
# ------------------------------------------------------------------ #


class TestReadingTheRunsOwnRecord:
    def test_the_value_and_the_table_come_back_together(self) -> None:
        found = row_counts_retrieved(_run(DARK_COUNT_SQL, '{"row_count": 1, "rows": [{"dark_vessels_count": 1454449}]}'))
        assert (Decimal("1454449"), "sm.area_counts_dark_v1r0") in found

    def test_a_refused_call_returned_nothing_to_publish(self) -> None:
        state = _run(DARK_COUNT_SQL, "lock guard refused: out-of-lens table")
        state["messages"][1].status = "error"
        assert row_counts_retrieved(state) == []

    def test_a_run_that_ran_no_sql_yields_nothing(self) -> None:
        assert row_counts_retrieved({"messages": [], "outputs": {}}) == []


# ------------------------------------------------------------------ #
# The narrow half — what fires, and what must stay silent
# ------------------------------------------------------------------ #


ROWS = [(Decimal("1454449"), "sm.area_counts_dark_v1r0")]


class TestItFiresOnTheFanOutCount:
    def test_the_published_sentence(self) -> None:
        prose = (
            "Additionally, there are 1,454,449 dark vessels identified, which are "
            "vessels marked with dark = 1."
        )
        assert mislabelled_row_counts(prose, ROWS) == [("1,454,449", "vessels")]

    def test_the_thousands_separator_is_not_required(self) -> None:
        assert mislabelled_row_counts("1454449 vessels were dark.", ROWS) == [("1454449", "vessels")]


class TestItStaysSilentOnTheHonestAnswer:
    def test_a_row_count_published_as_rows(self) -> None:
        """*How many rows are in this table* is a real question."""
        assert mislabelled_row_counts("The table holds 1,454,449 rows.", ROWS) == []

    def test_records_and_entries_are_the_same_word(self) -> None:
        assert mislabelled_row_counts("1,454,449 records matched.", ROWS) == []
        assert mislabelled_row_counts("1,454,449 entries matched.", ROWS) == []

    def test_a_row_noun_later_in_the_phrase_still_answers_the_question(self) -> None:
        assert mislabelled_row_counts("1,454,449 daily geofence rows.", ROWS) == []

    def test_a_number_with_no_noun_attached_is_not_a_claim_about_entities(self) -> None:
        assert mislabelled_row_counts("The count was 1,454,449.", ROWS) == []

    def test_a_verb_is_not_a_noun_because_it_ends_in_s(self) -> None:
        assert mislabelled_row_counts("1,454,449 was the figure as of today.", ROWS) == []

    def test_a_number_the_run_never_counted_belongs_to_151(self) -> None:
        assert mislabelled_row_counts("There are 6,119 vessels.", ROWS) == []

    def test_a_singular_subject_is_not_a_population_claim(self) -> None:
        assert mislabelled_row_counts("Row 1,454,449 is the last one.", ROWS) == []


# ------------------------------------------------------------------ #
# The check, end to end
# ------------------------------------------------------------------ #


class TestTheCheckContract:
    def test_it_refuses_the_run_that_shipped(self) -> None:
        state = _run(DARK_COUNT_SQL, '{"row_count": 1, "rows": [{"dark_vessels_count": 1454449}]}')
        reason = check_row_counts_in_prose(
            "Additionally, there are 1,454,449 dark vessels identified.", state, []
        )
        assert "1,454,449" in reason
        assert "sm.area_counts_dark_v1r0" in reason
        assert "COUNT(DISTINCT" in reason

    def test_an_empty_return_is_a_pass(self) -> None:
        state = _run(DARK_COUNT_SQL, '{"row_count": 1, "rows": [{"dark_vessels_count": 1454449}]}')
        assert check_row_counts_in_prose("The table holds 1,454,449 rows.", state, []) == ""

    def test_the_entity_count_repair_passes(self) -> None:
        state = _run(
            "SELECT COUNT(DISTINCT imo) AS n FROM sm.area_counts_dark_v1r0 WHERE dark = 1",
            '{"row_count": 1, "rows": [{"n": 6119}]}',
        )
        assert check_row_counts_in_prose("There are 6,119 dark vessels.", state, []) == ""


# ------------------------------------------------------------------ #
# Wired — a unit test stays green against a graph that never runs the check
# ------------------------------------------------------------------ #


class TestTheCheckIsNameableFromADocument:
    def test_guard_check_can_name_it_without_a_package_function(self) -> None:
        from openstategraph.compile.node_runtime import _BUILT_IN_CHECKS

        assert _BUILT_IN_CHECKS["row_counts_in_prose"] is check_row_counts_in_prose


class TestABuiltInCheckIsDiscoverableFromTheEditor:
    """A gate nobody can find is a gate nobody wires.

    `151` shipped `numbers_in_prose` into `_BUILT_IN_CHECKS` and left the
    `guard.check` card's only hint saying *"the package function to run"* — so
    the one check core supplies for free was reachable only by reading Python.
    `cpl-mcp`, the package this ticket's defect shipped from, has no guard on
    its path at all.

    Pinned rather than described, because a hand-mirror in TypeScript of a
    Python dict is exactly the drift CLAUDE.md's DRY rule forbids without one.
    """

    def test_every_built_in_check_is_named_on_the_card(self) -> None:
        from pathlib import Path

        from openstategraph.compile.node_runtime import _BUILT_IN_CHECKS

        card = (
            Path(__file__).resolve().parents[2] / "src" / "nodes" / "guard" / "GuardCheckNode.ts"
        ).read_text()
        for name in _BUILT_IN_CHECKS:
            assert name in card, f"{name} is a built-in check the guard card never mentions"


# ------------------------------------------------------------------ #
# The reason nobody could wire this gate where it belongs
# ------------------------------------------------------------------ #


class TestAGraderCanStandBehindAGuard:
    """A grader reads its candidate from `plan.edges` only — so a guard in
    front of it is invisible.

    Found by wiring this ticket's gate into `cpl-mcp` and running it live:
    every run came back *"I could not produce an answer after 2 attempts. The
    last review said: The answer is empty."* while `outputs[guard1]` held the
    full draft. `guard.check`'s `pass` is a **conditional** edge, exactly like a
    grader's, so it never appears in `plan.edges`; `_guard_check` reads both
    sources (`upstream + conditional_upstream`) and `_grader`, written first,
    reads only one.

    `compile/diagnostics.py` tells people to *"put a guard.check between that
    step and the output"*. When the output sits behind a grader — which is the
    ordinary NL2SQL shape and what `cpl-mcp` ships — following that advice
    silently emptied the answer.
    """

    def _document(self) -> dict:
        wire = lambda s, sp, t, tp: {  # noqa: E731
            "source": {"nodeId": s, "portId": sp},
            "target": {"nodeId": t, "portId": tp},
        }
        return {
            "nodes": [
                {"id": "in1", "type": "input.text", "data": {}},
                {"id": "a1", "type": "agent.llm", "data": {}},
                {"id": "guard1", "type": "guard.check", "data": {"check": "row_counts_in_prose"}},
                {"id": "g1", "type": "route.grader", "data": {"criteria": "Answer it.", "maxAttempts": "2"}},
                {"id": "out1", "type": "output.formatted", "data": {}},
            ],
            "edges": [
                wire("in1", "text", "a1", "prompt"),
                wire("a1", "result", "guard1", "candidate"),
                wire("guard1", "revise", "a1", "feedback"),
                wire("guard1", "pass", "g1", "candidate"),
                wire("g1", "revise", "a1", "feedback"),
                wire("g1", "pass", "out1", "result"),
            ],
        }

    def _run(self) -> tuple[str, list[str]]:
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        from conftest import RespondingModel

        is_grader = lambda content: "You are a grader" in content  # noqa: E731
        answer = "Mongstad shipped 12 cargoes last month."
        model = RespondingModel([(is_grader, "PASS")], default=answer)
        runtime = NodeRuntime(model=model)
        graph = WorkflowCompiler().build(self._document(), RunState, runtime.factory(self._document()))
        graph.invoke(
            {"question": "How many cargoes?", "attempts": 0, "decisions": {}, "outputs": {}},
            {"recursion_limit": 40},
        )
        return answer, [c for c in model.calls if is_grader(c)]

    def test_the_grader_is_shown_the_draft_the_guard_passed(self) -> None:
        answer, grader_calls = self._run()
        assert grader_calls, "the grader never ran"
        assert answer in grader_calls[0], (
            "the grader judged an empty candidate — a guard's `pass` is a "
            "conditional edge and `plan.edges` does not carry it"
        )


# ------------------------------------------------------------------ #
# The reason the gate was inert on the run it was written for
# ------------------------------------------------------------------ #


class TestAnAgentsQueriesReachTheGate:
    """`_agent` does not return `messages`, so a guard sees none of them.

    `grounded_numbers.retrieved_evidence`'s docstring says *"an agent's SQL
    rows come back as `ToolMessage`s"* — they come back to the **agent's own
    loop**, and `_agent` returns `outputs`/`answer`/`tool_use` and no messages
    at all. So every check reading `state["messages"]` is blind on the agent
    rail, which is the rail `cpl-mcp` runs on.

    Measured, not reasoned: with the gate wired and the check green in unit
    tests, a live run republished *"1,454,449 dark vessels"* and `guard1` said
    `pass`. The candidate was right there in `outputs[guard1]`; the evidence
    was not anywhere.

    So `tool_report` records the exchange it already scans for — it computes
    `queried` by looking for a SQL-shaped argument, and threw the query and
    its answer away. `tool_use` is the right home: keyed by node, already
    `MERGE_ROWS`, and already the run's record of *what happened*, which is
    exactly what a gate needs and what does not un-happen across revise laps.
    """

    def _messages(self) -> list:
        return [
            AIMessage(
                content="",
                tool_calls=[{"name": "mcp_execute_sql", "args": {"sql": DARK_COUNT_SQL}, "id": "c1"}],
            ),
            ToolMessage(
                content='{"row_count": 1, "rows": [{"dark_vessels_count": 1454449}]}',
                tool_call_id="c1",
                name="mcp_execute_sql",
            ),
        ]

    def test_the_query_and_its_answer_are_recorded(self) -> None:
        from openstategraph.compile.node_runtime import tool_report

        row = tool_report("agent1", self._messages(), ["mcp_execute_sql"], ())["tool_use"]["agent1"]
        # `tool` joined the exchange in `one-chinook-honest` 30: a gate asks
        # whether the statement was answered, and a person reading the run asks
        # what this tool actually did.
        assert row["queries"] == [
            {
                "sql": DARK_COUNT_SQL,
                "tool": "mcp_execute_sql",
                "result": '{"row_count": 1, "rows": [{"dark_vessels_count": 1454449}]}',
            }
        ]

    def test_a_run_with_no_sql_records_no_queries(self) -> None:
        """Absent, not empty — `queried`'s own rule, and for its own reason."""
        from openstategraph.compile.node_runtime import tool_report

        row = tool_report("agent1", [], ["mcp_execute_sql"], ())["tool_use"]["agent1"]
        assert "queries" not in row

    def test_the_check_reads_the_record_when_the_messages_are_gone(self) -> None:
        """The live shape: a guard downstream of an agent, holding no messages."""
        from openstategraph.compile.node_runtime import tool_report

        state = {
            "messages": [],
            "outputs": {},
            **tool_report("agent1", self._messages(), ["mcp_execute_sql"], ()),
        }
        assert (Decimal("1454449"), "sm.area_counts_dark_v1r0") in row_counts_retrieved(state)
        reason = check_row_counts_in_prose(
            "There are a total of **1,454,449 dark vessels** identified.", state, []
        )
        assert "1,454,449" in reason


class TestTheEnvelopeIsNotTheAnswer:
    """`133`'s trap, met live. The first wired run printed five findings and
    two were noise: *"The answer reports 1 ports"*, off the `row_count: 1` a
    tool wraps its rows in. A reader stops at the second wrong line.

    A bare `COUNT(*)` with no `GROUP BY` returns exactly one cell, so anything
    outside the rows is the tool talking about itself.
    """

    def test_a_row_count_wrapper_is_not_a_result(self) -> None:
        from openstategraph.counted_rows import cells_of

        assert numbers_in_of(cells_of('{"row_count": 1, "rows": [{"n": 1454449}]}')) == {
            Decimal("1454449")
        }

    def test_the_measured_mcp_envelope(self) -> None:
        """Captured off the live CPL MCP server, not composed here.

        Three layers at once: a **Python repr** of LangChain content blocks
        (not JSON), each block's `text` a JSON document, and the rows under
        `data.sample_rows`. The envelope carries a `row_count`, a hex
        `request_id` and a `digest` note, and every digit in those was being
        read as a retrieved figure.
        """
        from openstategraph.counted_rows import cells_of

        payload = (
            "[{'type': 'text', 'text': '{\\n  \"ok\": true,\\n  \"request_id\": "
            "\"95903ea18f10418aa419dfb6f22104e5\",\\n  \"data\": {\\n    \"row_count\": 1,"
            "\\n    \"sample_rows\": [\\n      {\\n        \"total_rows\": 2658929\\n"
            "      }\\n    ],\\n    \"truncated\": false\\n  }\\n}', "
            "'id': 'lc_ea4d8514-cf52-4957-8623-d41f540efa61'}]"
        )
        assert numbers_in_of(cells_of(payload)) == {Decimal("2658929")}

    def test_a_refused_call_carries_no_data(self) -> None:
        """`lock_violation` arrives as an ordinary successful `ToolMessage` on
        the MCP path — the payload is the only thing that says otherwise, and
        its `request_id` is full of digits."""
        from openstategraph.counted_rows import cells_of

        payload = (
            "[{'type': 'text', 'text': '{\"ok\": false, \"request_id\": "
            "\"80bc6fc71ba94019be9b1c428fd43606\", \"error_code\": \"lock_violation\"}'}]"
        )
        assert numbers_in_of(cells_of(payload)) == set()

    def test_an_unrecognised_shape_is_left_whole(self) -> None:
        from openstategraph.counted_rows import cells_of

        assert numbers_in_of(cells_of("count\n1454449\n")) == {Decimal("1454449")}
        assert numbers_in_of(cells_of('{"total": 12}')) == {Decimal("12")}

    def test_the_envelope_never_reaches_the_prose_check(self) -> None:
        state = _run(DARK_COUNT_SQL, '{"row_count": 1, "rows": [{"dark_vessels_count": 1454449}]}')
        assert check_row_counts_in_prose("There was 1 vessel that departed.", state, []) == ""
