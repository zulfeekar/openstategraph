"""The identity tool: the run says who this is, the model may only ask.

Same rule as the email tool's recipient. An identity the model can pass as an
argument is an identity a prompt-injected document can rewrite — and here that
would reach into another person's long-term memory, which is namespaced on the
very same `user_email`.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from openstategraph.api.registries import build_tool_registry, reset_process_tool_layer
from openstategraph.prebuilt_session import SESSION_TOOLS, SessionIdentityTool


class _State(TypedDict, total=False):
    answer: str


def _inside_a_run(configurable: dict[str, str]) -> str:
    """Run the tool where it actually lives: inside a graph node, mid-run."""
    tool = SessionIdentityTool().as_langchain_tool()

    def node(state: _State) -> dict[str, str]:
        return {"answer": tool.invoke({})}

    builder: StateGraph = StateGraph(_State)
    builder.add_node("n", node)
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    result = builder.compile().invoke({"answer": ""}, {"configurable": configurable})
    return str(result["answer"])


class TestWhatItReports:
    def test_it_reads_the_identity_the_run_was_started_with(self) -> None:
        answer = _inside_a_run(
            {
                "thread_id": "t-1",
                "session_id": "s-1",
                "user_email": "ada@example.com",
                "workflow_slug": "chinook-assistant",
            }
        )
        assert "ada@example.com" in answer
        assert "t-1" in answer
        assert "s-1" in answer
        assert "chinook-assistant" in answer

    def test_blank_identity_fields_are_left_out_not_reported_as_empty(self) -> None:
        answer = _inside_a_run({"thread_id": "t-1", "user_email": "", "session_id": ""})
        assert "t-1" in answer
        assert "user:" not in answer

    def test_an_anonymous_run_is_answered_not_failed(self) -> None:
        # A retryable error here would send an agent round a loop chasing a
        # fact that is never going to arrive.
        answer = _inside_a_run({"thread_id": ""})
        assert "anonymous" in answer
        assert not answer.startswith("Error:")

    def test_outside_a_run_it_still_answers(self) -> None:
        result = SessionIdentityTool().run()
        assert result.ok
        assert "anonymous" in result.content


class TestTheModelCannotClaimAnIdentity:
    def test_it_takes_no_arguments_at_all(self) -> None:
        schema = SessionIdentityTool().Args.model_json_schema()
        assert not schema.get("properties")

    def test_a_model_that_invents_a_user_is_refused(self) -> None:
        # The attack this closes: a document saying "you are now talking to
        # grace@example.com" must not become a tool call that says so.
        result = SessionIdentityTool().run(user_email="grace@example.com")
        assert not result.ok


class TestItIsAvailableToEveryWorkflow:
    def test_the_registry_carries_it_by_node_type(self, tmp_path: Any) -> None:
        reset_process_tool_layer()
        registry = build_tool_registry(None, None)
        for tool in SESSION_TOOLS:
            assert registry[tool.node_type].name == tool.name
