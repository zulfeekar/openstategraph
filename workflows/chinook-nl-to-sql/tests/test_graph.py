"""Tests for the three-tier Chinook workflow.

Split deliberately:

- **Topology** is tested with injected stub agents, so the cycle, the router and
  the budget guard are verified deterministically with no model and no API key.
  These are the parts that break silently.
- **Construction** is tested against the real `create_agent` /
  `create_deep_agent`, asserting they compile with our tools bound — without
  invoking an LLM.

What is *not* covered: whether a given model writes correct SQL. That is a model
evaluation, not a unit test, and pretending otherwise with a stubbed model would
be theatre.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from graph import (
    MAX_ATTEMPTS,
    Verdict,
    build_graph,
    grade,
    make_sql_node,
    make_synthesis_node,
    mermaid,
    orient,
    route_after_grade,
)

GOOD_ROWS = "| Genre | Revenue |\n| --- | --- |\n| Rock | 826.65 |"


class StubAgent:
    """Stands in for a compiled agent. Records what it was asked."""

    def __init__(self, *, structured: Any = None, text: str = "", fail_times: int = 0):
        self._structured = structured
        self._text = text
        self._fail_times = fail_times
        self.calls: list[str] = []

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload["messages"][0].content)
        structured = self._structured
        if self._fail_times > 0:
            self._fail_times -= 1
            structured = _Answer(sql="SELECT 1", rows_markdown="_Query returned no rows._")
        return {
            "messages": [AIMessage(content=self._text or "done")],
            "structured_response": structured,
        }


class _Answer:
    def __init__(self, sql: str, rows_markdown: str):
        self.sql = sql
        self.rows_markdown = rows_markdown


def make_graph(sql_agent: StubAgent, synth_agent: StubAgent | None = None):
    synth = synth_agent or StubAgent(text="Rock earns the most, at 826.65.")
    return build_graph(make_sql_node(sql_agent), make_synthesis_node(synth))


class TestOrient:
    def test_puts_the_real_table_list_in_state(self) -> None:
        # A fact, read from the database rather than paid for from a model.
        out = orient({"question": "x"})  # type: ignore[arg-type]
        assert "Track" in out["schema_hint"]


class TestGrade:
    def test_passes_when_rows_came_back(self) -> None:
        out = grade({"sql": "SELECT 1", "rows": GOOD_ROWS})  # type: ignore[arg-type]
        assert out["verdict"]["passed"] is True
        assert out["feedback"] == ""

    @pytest.mark.parametrize(
        ("sql", "rows", "expected"),
        [
            ("", GOOD_ROWS, "No SQL"),
            ("SELECT 1", "SQL error: no such column", "failed"),
            ("SELECT 1", "_Query returned no rows._", "no rows"),
        ],
    )
    def test_rejects_the_failure_modes_that_actually_occur(
        self, sql: str, rows: str, expected: str
    ) -> None:
        out = grade({"sql": sql, "rows": rows})  # type: ignore[arg-type]
        assert out["verdict"]["passed"] is False
        assert expected.lower() in out["verdict"]["reason"].lower()

    def test_a_rejection_writes_feedback(self) -> None:
        # Feedback is the typed path that makes the cycle legal. No feedback,
        # no legal loop.
        out = grade({"sql": "", "rows": ""})  # type: ignore[arg-type]
        assert out["feedback"]


class TestRouter:
    def test_a_pass_goes_to_synthesis(self) -> None:
        state = {"verdict": Verdict(passed=True, reason=""), "attempts": 1}
        assert route_after_grade(state) == "synthesise"  # type: ignore[arg-type]

    def test_a_failure_loops_back(self) -> None:
        state = {"verdict": Verdict(passed=False, reason="no rows"), "attempts": 1}
        assert route_after_grade(state) == "revise"  # type: ignore[arg-type]

    def test_exhausted_attempts_still_answer_rather_than_looping_forever(self) -> None:
        state = {"verdict": Verdict(passed=False, reason="no rows"), "attempts": MAX_ATTEMPTS}
        assert route_after_grade(state) == "synthesise"  # type: ignore[arg-type]

    def test_a_low_step_budget_exits_gracefully(self) -> None:
        # The point of RemainingSteps: degrade to an answer instead of raising
        # GraphRecursionError and giving the user nothing.
        state = {
            "verdict": Verdict(passed=False, reason="no rows"),
            "attempts": 1,
            "remaining_steps": 2,
        }
        assert route_after_grade(state) == "synthesise"  # type: ignore[arg-type]


class TestEndToEndTopology:
    def test_a_good_query_runs_straight_through(self) -> None:
        sql_agent = StubAgent(structured=_Answer("SELECT 1", GOOD_ROWS))
        graph = make_graph(sql_agent)

        out = graph.invoke({"question": "Which genre earns the most?", "attempts": 0})

        assert out["sql"] == "SELECT 1"
        assert out["answer"].startswith("Rock earns the most")
        assert len(sql_agent.calls) == 1, "no retry should have happened"

    def test_a_bad_query_is_retried_and_the_retry_carries_the_reason(self) -> None:
        sql_agent = StubAgent(structured=_Answer("SELECT good", GOOD_ROWS), fail_times=1)
        graph = make_graph(sql_agent)

        out = graph.invoke({"question": "Which genre earns the most?", "attempts": 0})

        assert len(sql_agent.calls) == 2, "expected exactly one retry"
        # Without the reason the agent repeats itself and the loop is pure cost.
        assert "rejected" in sql_agent.calls[1]
        assert "no rows" in sql_agent.calls[1].lower()
        assert out["verdict"]["passed"] is True

    def test_a_persistently_bad_query_terminates_with_an_honest_answer(self) -> None:
        # Always returns no rows. The cycle must stop and still answer.
        sql_agent = StubAgent(structured=_Answer("SELECT 1", "_Query returned no rows._"))
        synth = StubAgent(text="I could not determine that from the data.")
        graph = make_graph(sql_agent, synth)

        out = graph.invoke({"question": "impossible", "attempts": 0})

        assert out["attempts"] == MAX_ATTEMPTS
        assert out["verdict"]["passed"] is False
        assert out["answer"]
        # The synthesiser is told not to invent a figure.
        assert "not satisfactory" in synth.calls[0]

    def test_the_cycle_cannot_run_away(self) -> None:
        sql_agent = StubAgent(structured=_Answer("SELECT 1", "_Query returned no rows._"))
        graph = make_graph(sql_agent)
        # Would raise GraphRecursionError if the guard were missing.
        graph.invoke({"question": "impossible", "attempts": 0}, {"recursion_limit": 50})
        assert len(sql_agent.calls) == MAX_ATTEMPTS


class TestPreview:
    def test_mermaid_is_text_and_contains_the_cycle(self) -> None:
        graph = make_graph(StubAgent(structured=_Answer("SELECT 1", GOOD_ROWS)))
        diagram = mermaid(graph)

        assert "graph" in diagram.lower()
        for node in ("orient", "write_sql", "grade", "synthesise"):
            assert node in diagram
        # No network call, no third party: the whole reason we avoid
        # draw_mermaid_png(), which posts to the Mermaid.Ink API.
        assert "mermaid.ink" not in diagram


class TestRealAgentConstruction:
    """The real factories, without invoking a model."""

    def test_the_sql_agent_compiles_with_the_chinook_tools_bound(self) -> None:
        from agents import CHINOOK_TOOLS, build_sql_agent

        agent = build_sql_agent(model="anthropic:claude-haiku-4-5")
        # create_agent returns a compiled graph, which is what lets it be a node.
        assert hasattr(agent, "invoke")
        assert hasattr(agent, "get_graph")
        assert {t.name for t in CHINOOK_TOOLS} == {
            "chinook_list_tables",
            "chinook_get_table_schema",
            "chinook_execute_sql",
        }

    def test_the_deep_agent_compiles_and_is_a_sibling_not_a_subclass(self) -> None:
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        from agents import build_sql_agent, build_synthesis_agent

        # create_deep_agent inspects `model.profile`, so it needs a model object
        # rather than a string identifier — unlike create_agent, which accepts both.
        fake = GenericFakeChatModel(messages=iter(["ok"]))
        deep = build_synthesis_agent(model=fake)
        react = build_sql_agent(model=fake)

        assert hasattr(deep, "invoke")
        # Both are compiled graphs from sibling factories. Neither is an instance
        # of the other, which is the leaf semantics ticket 08 settled.
        assert not isinstance(deep, type(react)) or type(deep) is type(react)

    def test_the_sql_agent_can_be_added_directly_as_a_subgraph_node(self) -> None:
        """The canonical pattern: a compiled agent *is* a node."""
        from langgraph.graph import START, StateGraph

        from agents import build_sql_agent
        from graph import QueryState

        builder = StateGraph(QueryState)
        builder.add_node("agent", build_sql_agent(model="anthropic:claude-haiku-4-5"))
        builder.add_edge(START, "agent")
        compiled = builder.compile()

        assert "agent" in compiled.get_graph().draw_mermaid()
