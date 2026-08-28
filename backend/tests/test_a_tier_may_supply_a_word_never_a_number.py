"""launch-readiness 151 — a model may supply a word, never a number.

Two halves, and the second is what makes the first real.

**The gate.** `guard.check` after the summarizer, running rule F3 of the
NL2SQL rule contract — *every number in the prose appears in a result row*.
The sweep note of 2026-08-25 says that check was already "implemented as a
standalone `check_numbers_in_prose()`"; it was not, anywhere, ever. Only the
paragraph claiming it existed, which is the same defect the rule is about: an
assertion with no way to fail.

**The finding.** `UNDECLARED_FALLBACK`, reported at compile time on a graph
whose Output can be reached from a node holding a capability that answers from
outside the run's own data, with no gate between.

**The narrowness is the load-bearing half, and both directions are pinned
here.** `launch-readiness/121` is the shape: it fires on a side-effecting
capability in a loop and stays silent on a read-only one in the identical
loop. `launch-readiness/133` is the counter-example — a check that accepted
`SELECT DISTINCT k, a, b` as a dedup, reporting success on a wrong query,
which is worse than no check because it turned "unverified" into "verified".

So: a finding that fires on every graph is a finding nobody reads, and a gate
that rejects a legitimate number is a gate people route around.
"""

from __future__ import annotations

from typing import Any

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult
from openstategraph.api.services import WorkflowServices
from openstategraph.compile.diagnostics import REPORT_ONLY, Finding
from openstategraph.compile.grounding import (
    answers_from_outside_the_run,
    gated_by,
    reaches_without_passing,
)
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.grounded_numbers import (
    check_numbers_in_prose,
    retrieved_evidence,
    ungrounded_numbers,
)


# ------------------------------------------------------------------ #
# How OSG knows a capability answers from outside the run
# ------------------------------------------------------------------ #


class TestTheDeclarationSitsOnTheUnusualCase:
    """The inverse of 121's default, argued rather than copied.

    121 defaults `side_effecting` to `True` because an undeclared tool must
    land on the safe side — and there the safe side is also the *rare* side,
    so the noise falls where it belongs. Here nearly every tool in a
    quantitative workflow is the store, so the same reflex would fire this
    finding on every graph with an agent and a tool.
    """

    def test_a_tool_that_says_nothing_is_taken_to_answer_from_the_store(self) -> None:
        class SaysNothing(BaseTool):
            name = "says_nothing"
            description = ""
            Args = NoArgs

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult()

        assert not answers_from_outside_the_run(SaysNothing())

    def test_a_tool_that_declares_itself_open_world_is_believed(self) -> None:
        class Guesses(BaseTool):
            name = "guesses"
            description = ""
            Args = NoArgs
            open_world = True

            def _execute(self, args: Any) -> ToolResult:
                return ToolResult()

        assert answers_from_outside_the_run(Guesses())

    def test_an_object_that_is_not_ours_at_all_gets_the_quiet_answer(self) -> None:
        assert not answers_from_outside_the_run(object())

    def test_the_shipped_web_tools_declare_it_and_the_store_tools_do_not(self) -> None:
        from openstategraph.prebuilt_mcp import McpTool
        from openstategraph.prebuilt_sql import SqlQueryTool
        from openstategraph.prebuilt_web import WebFetchTool, WebSearchTool

        assert answers_from_outside_the_run(WebSearchTool())
        assert answers_from_outside_the_run(WebFetchTool())
        assert not answers_from_outside_the_run(SqlQueryTool())
        # A stranger's server, and in this product's own demos it *is* the
        # store. Unlike `side_effecting`, guessing quiet here costs a warning,
        # never a duplicate action.
        assert McpTool.open_world is False


# ------------------------------------------------------------------ #
# The walk
# ------------------------------------------------------------------ #


def _wire(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _agent(node_id: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": "agent.llm", "data": {"systemPrompt": "Answer.", **data}}


def _ungated(tool_type: str = "tool.web-search") -> dict[str, Any]:
    """in -> agent -> out, with one capability on the agent's `tools` bus."""
    return {
        "version": 2,
        "name": "ungated",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            _agent("a1"),
            {"id": "t1", "type": tool_type, "data": {}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _wire("in1", "text", "a1", "prompt"),
            _wire("t1", "tool", "a1", "tools"),
            _wire("a1", "result", "out1", "result"),
        ],
    }


def _gated(tool_type: str = "tool.web-search") -> dict[str, Any]:
    """The identical document with a number gate drawn between the two."""
    return {
        "version": 2,
        "name": "gated",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            _agent("a1"),
            {"id": "t1", "type": tool_type, "data": {}},
            {"id": "check1", "type": "guard.check", "data": {"check": "numbers_in_prose"}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            _wire("in1", "text", "a1", "prompt"),
            _wire("t1", "tool", "a1", "tools"),
            _wire("a1", "result", "check1", "candidate"),
            _wire("check1", "revise", "a1", "feedback"),
            _wire("check1", "pass", "out1", "result"),
        ],
    }


def _build(tmp_path: Any, document: dict[str, Any], node_id: str) -> Any:
    """Build one node's step through the real runtime and hand back the
    diagnostics — the factory, never the helper. A test that only asked
    whether a walk returned True would stay green against a fix wired
    nowhere."""
    runtime = WorkflowServices(tmp_path).runtime_for(None, document, None, warnings=[])
    plan = WorkflowCompiler().plan(document)
    node = {n["id"]: n for n in document["nodes"]}[node_id]
    runtime.factory(document)(node_id, node, plan)
    return runtime.diagnostics


class TestWhatCountsAsStandingBetween:
    def test_every_producer_is_reached_when_nothing_gates(self) -> None:
        plan = WorkflowCompiler().plan(_ungated())
        assert "a1" in reaches_without_passing("out1", plan, set())

    def test_a_gate_stops_the_walk_and_is_not_itself_reported(self) -> None:
        plan = WorkflowCompiler().plan(_gated())
        found = reaches_without_passing("out1", plan, {"check1"})
        assert "check1" not in found
        assert "a1" not in found

    def test_a_conditional_edge_is_walked(self) -> None:
        """A guard's `pass` and a grader's `pass` are conditional edges, and
        they are the ones that reach an Output in every gated document here."""
        plan = WorkflowCompiler().plan(_gated())
        assert "a1" in reaches_without_passing("out1", plan, set())

    def test_gates_are_found_by_type(self) -> None:
        plan = WorkflowCompiler().plan(_gated())
        types = {n["id"]: n["type"] for n in _gated()["nodes"]}
        assert gated_by(plan, types, "guard.check") == {"check1"}


# ------------------------------------------------------------------ #
# The finding — both directions
# ------------------------------------------------------------------ #


class TestTheDeveloperIsToldTheAnswerCanCarryAnInventedNumber:
    def test_it_fires_and_names_the_output_the_producer_and_the_capability(
        self, tmp_path: Any
    ) -> None:
        diagnostics = _build(tmp_path, _ungated(), "out1")
        (subjects,) = diagnostics.subjects(Finding.UNDECLARED_FALLBACK)
        assert subjects[0] == "out1"
        assert subjects[1] == "a1"
        assert subjects[2] == "tool.web-search"

    def test_the_sentence_names_the_fix_rather_than_the_condition(self, tmp_path: Any) -> None:
        diagnostics = _build(tmp_path, _ungated(), "out1")
        (sentence,) = [w for w in diagnostics.warnings() if "guard.check" in w]
        assert "out1" in sentence and "a1" in sentence

    def test_it_is_a_report_and_can_never_become_an_exit_code(self, tmp_path: Any) -> None:
        assert Finding.UNDECLARED_FALLBACK in REPORT_ONLY
        diagnostics = _build(tmp_path, _ungated(), "out1")
        assert not [w for w in diagnostics.failure_warnings() if "guard.check" in w]


class TestTheFindingStaysSilentOnAGraphThatIsCorrect:
    """The half that decides whether anybody reads the other half."""

    def test_a_gate_between_the_model_and_the_output_silences_it(self, tmp_path: Any) -> None:
        diagnostics = _build(tmp_path, _gated(), "out1")
        assert not diagnostics.any(Finding.UNDECLARED_FALLBACK)

    def test_a_store_tool_on_the_identical_ungated_graph_is_never_reported(
        self, tmp_path: Any
    ) -> None:
        """The ordinary case: an agent bound to the store's own query tools,
        writing straight to an Output. Nothing about it is a hazard, and a
        warning on it is one a developer learns to skip."""
        diagnostics = _build(tmp_path, _ungated(tool_type="tool.sql-query"), "out1")
        assert not diagnostics.any(Finding.UNDECLARED_FALLBACK)

    def test_a_graph_with_no_capability_at_all_is_never_reported(self, tmp_path: Any) -> None:
        document = _ungated()
        document["nodes"] = [n for n in document["nodes"] if n["id"] != "t1"]
        document["edges"] = [e for e in document["edges"] if e["source"]["nodeId"] != "t1"]
        diagnostics = _build(tmp_path, document, "out1")
        assert not diagnostics.any(Finding.UNDECLARED_FALLBACK)


# ------------------------------------------------------------------ #
# The gate — where the line falls between a quantity and prose
# ------------------------------------------------------------------ #


class TestAQuantityNothingRetrievedIsReported:
    def test_the_measured_invention(self) -> None:
        """The defect, in the numbers it was actually measured in."""
        assert ungrounded_numbers("The Persian Gulf has 81 ports.", "port\nRas Tanura\n") == ["81"]

    def test_a_number_the_run_retrieved_is_left_alone(self) -> None:
        assert ungrounded_numbers("There were 1664 kbd in May.", "month,kbd\nMay,1664\n") == []

    def test_thousands_separators_are_the_same_number(self) -> None:
        assert ungrounded_numbers("2,594 voyages.", "voyages\n2594\n") == []

    def test_several_inventions_are_reported_once_each_in_order(self) -> None:
        found = ungrounded_numbers("4031 kbd, then 4031, then 1664.", "x\n1\n")
        assert found == ["4031", "1664"]


class TestLegitimateProseIsNotTheDefect:
    """A gate that rejects a legitimate number is a gate people route around.

    An answer that explains, summarises or qualifies **is the product**.
    """

    def test_a_share_written_in_words_carries_no_digits_at_all(self) -> None:
        assert ungrounded_numbers("Roughly two thirds of them were laden.", "x\n1\n") == []

    def test_a_percentage_is_arithmetic_over_numbers_it_was_given(self) -> None:
        """The deliberate hole, named in the module docstring: an invented
        `81%` passes. Taken because the alternative fires on every honest
        summary that computes a share."""
        assert ungrounded_numbers("That is 67% of the fleet.", "x\n1\n") == []

    def test_a_count_of_the_rows_it_was_handed_is_honest(self) -> None:
        """`12` appears in none of the rows, and saying it is not an
        invention — it is what counting them produces."""
        rows = "vessel\n" + "\n".join(f"v{i}" for i in range(12)) + "\n"
        assert ungrounded_numbers("There are 12 vessels.", rows) == []

    def test_a_rounding_of_a_retrieved_number_is_honest_arithmetic(self) -> None:
        assert ungrounded_numbers("About 27.8 days on average.", "avg\n27.8333\n") == []

    def test_the_users_own_number_is_not_the_models_invention(self) -> None:
        assert (
            ungrounded_numbers(
                "Over the last 100 days.", "x\n1\n", question="vessel count for the last 100 days"
            )
            == []
        )

    def test_a_name_that_contains_digits_is_not_a_quantity(self) -> None:
        assert ungrounded_numbers("The VLCC2 route and gpt-4o.", "x\n1\n") == []

    def test_a_numbered_list_is_formatting(self) -> None:
        assert ungrounded_numbers("1. Ras Tanura\n2. Jubail\n", "port\nRas Tanura\nJubail\n") == []

    def test_a_quantity_that_opens_the_answer_is_still_a_quantity(self) -> None:
        """`launch-readiness/165`, found while writing `counted_rows.py`.

        `_is_candidate` read `before in "_."` with `before` empty at offset 0,
        and `"" in "_."` is True — so every number opening an answer was
        classified as part of an identifier and skipped. An answer beginning
        *"81 ports are in the Persian Gulf"* escaped this gate entirely.
        """
        assert ungrounded_numbers("81 ports are in the Persian Gulf.", "port\nRas Tanura\n") == ["81"]
        assert ungrounded_numbers("1664 kbd in May.", "month,kbd\nMay,1664\n") == []


class TestWhereTheEvidenceComesFrom:
    """Two rails, because a workflow uses one or the other and a check that
    read only one would be silently inert on half the graphs anybody draws."""

    def test_a_tool_result_is_evidence_even_though_it_never_touches_outputs(self) -> None:
        from langchain_core.messages import AIMessage, ToolMessage

        state = {
            "messages": [AIMessage(content="thinking"), ToolMessage(content="1664", tool_call_id="1")],
            "outputs": {},
        }
        assert "1664" in retrieved_evidence(state, [])

    def test_a_deterministic_steps_output_is_evidence(self) -> None:
        state = {"messages": [], "outputs": {"execute1": "month,kbd\nMay,1664\n"}}
        assert "1664" in retrieved_evidence(state, [])

    def test_the_models_own_draft_is_never_its_own_evidence(self) -> None:
        """Otherwise every invented number grounds itself."""
        state = {"messages": [], "outputs": {"a1": "There are 81 ports."}}
        assert retrieved_evidence(state, ["a1"]) == ""

    def test_the_check_passes_and_refuses_on_the_two_states(self) -> None:
        grounded = {"messages": [], "outputs": {"execute1": "kbd\n1664\n"}, "question": "May?"}
        assert check_numbers_in_prose("May was 1664 kbd.", grounded, ["a1"]) == ""

        invented = {"messages": [], "outputs": {"execute1": "kbd\n\n"}, "question": "May?"}
        reason = check_numbers_in_prose("May was 1664 kbd.", invented, ["a1"])
        assert "1664" in reason


# ------------------------------------------------------------------ #
# The gate, wired — the whole point of the ticket
# ------------------------------------------------------------------ #


class TestTheGateRunsInsideAGuardCheckNode:
    """A unit test over the check alone stays green against a graph that never
    runs it. This builds the node through the real runtime and calls it."""

    def _step(self, tmp_path: Any) -> Any:
        document = _gated()
        runtime = WorkflowServices(tmp_path).runtime_for(None, document, None, warnings=[])
        plan = WorkflowCompiler().plan(document)
        node = {n["id"]: n for n in document["nodes"]}["check1"]
        return runtime.factory(document)("check1", node, plan), runtime.diagnostics

    def test_an_invented_number_routes_revise_and_says_which(self, tmp_path: Any) -> None:
        step, _ = self._step(tmp_path)
        result = step(
            {
                "question": "how many ports?",
                "outputs": {"a1": "The Persian Gulf has 81 ports."},
                "messages": [],
            }
        )
        assert result["decisions"]["check1"] == "revise"
        assert "81" in result["feedback"]

    def test_a_grounded_number_passes(self, tmp_path: Any) -> None:
        step, _ = self._step(tmp_path)
        result = step(
            {
                "question": "how many ports?",
                "outputs": {"a1": "There are 68 ports.", "execute1": "count\n68\n"},
                "messages": [],
            }
        )
        assert result["decisions"]["check1"] == "pass"
        assert result["feedback"] == ""

    def test_naming_a_built_in_check_is_not_an_unresolved_function(self, tmp_path: Any) -> None:
        """It resolves without any `functions/` folder — that is the point of
        the built-in table. The check needs the *evidence*, and `fn(text)`
        cannot see it, which is why F3 sat unwritten for three days."""
        step, diagnostics = self._step(tmp_path)
        step({"question": "q", "outputs": {"a1": "fine"}, "messages": []})
        assert not diagnostics.any(Finding.UNRESOLVED_FUNCTION)


class TestTheAgentRailIsNotSilentlyEmpty:
    """`launch-readiness/165`, measured on a live run rather than reasoned.

    This module's own docstring promised that an agent's SQL rows arrive as
    `ToolMessage`s. They arrive in the agent's *loop*; `_agent` returns
    `outputs`, `answer` and `tool_use` and no messages, so on the only shape
    that matters here — a guard downstream of an agent — the evidence was
    empty and every number in the answer read as invented.
    """

    def test_a_query_an_agent_ran_is_evidence(self) -> None:
        state = {
            "messages": [],
            "outputs": {},
            "tool_use": {"a1": {"queries": [{"sql": "SELECT SUM(kbd) FROM t", "result": "kbd\n1664\n"}]}},
        }
        assert "1664" in retrieved_evidence(state, ["a1"])
        assert check_numbers_in_prose("May was 1664 kbd.", state, ["a1"]) == ""
