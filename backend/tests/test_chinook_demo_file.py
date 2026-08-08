"""End-to-end proof for the flagship's **real saved file**.

`workflows/chinook-nl-to-sql/workflow.json` (ticket 39) is the canvas
document for the workflow `graph.py` hand-builds. Like
`test_intent_routed_demo_file.py`, this loads the actual artifact from disk
rather than a hand-built document — the only kind of test that can catch a
frontend-authoring or serialization regression in the file itself.

The shape under test is the evaluator-optimizer loop:

    input.text -> agent.llm (ReAct + the three Chinook SQL tools)
               -> route.grader --pass--> output.formatted
                              '-revise-> back to the agent's feedback port

Both paths run with a scripted model: the straight pass, and one lap of the
revise cycle proving the rejection reason actually reaches the agent's
retry prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from openstategraph.compile.node_runtime import NodeRuntime, RunState, chinook_tool_registry
from openstategraph.compile.workflow_compiler import WorkflowCompiler

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent.parent / "workflows" / "chinook-nl-to-sql" / "workflow.json"
)

CHINOOK_TOOL_NAMES = {
    "chinook_list_tables",
    "chinook_get_table_schema",
    "chinook_execute_sql",
}

SQL_ANSWER = (
    "SQL: SELECT g.Name, SUM(il.UnitPrice * il.Quantity) AS revenue "
    "FROM InvoiceLine il JOIN Track t ON il.TrackId = t.TrackId "
    "JOIN Genre g ON t.GenreId = g.GenreId GROUP BY g.Name ORDER BY revenue DESC LIMIT 1\n"
    "Rock earns the most revenue: 826.65."
)

RouteRule = tuple[Callable[[str], bool], str]


class RespondingModel(GenericFakeChatModel):
    """Predicate-scripted model — see `test_intent_routed_demo_file.py`."""

    rules: list[RouteRule] = []
    default: str = "PASS"
    calls: list[str] = []

    def __init__(self, rules: list[RouteRule], default: str = "PASS"):
        super().__init__(messages=iter([]))
        object.__setattr__(self, "rules", rules)
        object.__setattr__(self, "default", default)
        object.__setattr__(self, "calls", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        content = "\n".join(str(m.content) for m in messages)
        self.calls.append(content)
        answer = self.default
        for predicate, reply in self.rules:
            if predicate(content):
                answer = reply
                break
        return self._reply(answer)

    def _reply(self, text: str):  # noqa: ANN001
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):  # noqa: ANN001
        """The agent has three real Chinook tool bindings, so `create_agent`
        calls `bind_tools`; the base fake raises by default."""
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)


def load_real_document() -> dict[str, Any]:
    payload = json.loads(WORKFLOW_PATH.read_text())
    return payload["document"]


def run(question: str, model: Any) -> dict[str, Any]:
    document = load_real_document()
    runtime = NodeRuntime(model=model, tools=chinook_tool_registry())
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
        {"recursion_limit": 60},
    )


class TestTheRealFileCompiles:
    def test_the_saved_document_has_no_compiler_warnings(self) -> None:
        plan = WorkflowCompiler().plan(load_real_document())
        assert plan.warnings == []

    def test_all_three_chinook_tools_are_bound_to_the_agent(self) -> None:
        """The tools bus must survive serialization: three tool edges in the
        file, three bindings in the plan, three langchain tools on the agent."""
        plan = WorkflowCompiler().plan(load_real_document())
        assert set(plan.tool_bindings["agent-sql"]) == {
            "tool-tables",
            "tool-schema",
            "tool-sql",
        }

        model = RespondingModel([], default=SQL_ANSWER)
        document = load_real_document()
        runtime = NodeRuntime(model=model, tools=chinook_tool_registry())
        WorkflowCompiler().build(document, RunState, runtime.factory(document))
        assert set(runtime.last_bound_tools) == CHINOOK_TOOL_NAMES

    def test_the_grader_routes_both_ways(self) -> None:
        plan = WorkflowCompiler().plan(load_real_document())
        assert set(plan.conditional["grader-sql"].keys()) == {"pass", "revise"}


class TestThePassPath:
    def test_a_good_answer_flows_straight_to_the_output(self) -> None:
        model = RespondingModel(
            [(lambda c: "You are a grader" in c, "PASS")],
            default=SQL_ANSWER,
        )
        final = run("Which genre earns the most revenue?", model)

        assert final["decisions"]["grader-sql"] == "pass"
        assert final["answer"] == SQL_ANSWER
        assert final["outputs"]["out1"] == SQL_ANSWER
        assert final["attempts"] == 1


class TestTheReviseLoop:
    def test_a_rejected_answer_loops_back_with_the_reason(self) -> None:
        grader_verdicts = iter(["FAIL\nState the SQL you executed.", "PASS"])
        model = RespondingModel(
            [(lambda c: "You are a grader" in c, "")],  # reply chosen below
            default=SQL_ANSWER,
        )

        # The first grader call fails, the second passes. A predicate rule
        # returns a fixed string, so route the varying verdict through
        # `_generate` by swapping the rule's reply per call.
        original_generate = model._generate

        def generate(messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
            content = "\n".join(str(m.content) for m in messages)
            if "You are a grader" in content:
                model.calls.append(content)
                return model._reply(next(grader_verdicts))
            return original_generate(messages, stop=stop, run_manager=run_manager, **kwargs)

        object.__setattr__(model, "_generate", generate)

        final = run("Which genre earns the most revenue?", model)

        assert final["decisions"]["grader-sql"] == "pass"
        assert final["attempts"] == 2
        assert final["answer"] == SQL_ANSWER

        # The rejection reason must reach the agent's retry prompt — a revise
        # loop that carries no feedback is pure cost.
        retry_prompts = [
            c
            for c in model.calls
            if "Your previous answer was rejected" in c and "You are a grader" not in c
        ]
        assert retry_prompts, "the agent never saw the grader's feedback"
        assert "State the SQL you executed." in retry_prompts[0]
