"""The published answer was our own error string.

`every-workflow-green` 32. In the editor:

    web_search  → results
    web_fetch   → Error: web_fetch is not a valid tool, try one of [...]
    answer      → Error: web_fetch is not a valid tool, try one of [...]

`_final_text` walks back for the last non-empty text. It already refuses two
kinds of message — anything at or before the human turn, and anything carrying
`tool_calls` — and its docstring records why each was added. A `ToolMessage` is
the third of exactly the same family and was never excluded: it has no
`tool_calls`, its `type` is `"tool"`, and its content is whatever the tool
returned.

So a loop that ended on a tool result published the tool result. **A tool
result is evidence for the model, not prose for a person.**

When nothing the model said remains, "" is the right answer: that is a silent
node, which `silent_node_warnings` already has a sentence for (ticket 01).
Publishing the nearest string instead is how a completely broken run looked
completely healthy — no node failed, the output was non-empty, and every health
channel built on this map saw nothing wrong.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from openstategraph.compile.node_runtime import _final_text


class TestATooResultIsNotProse:
    def test_a_trailing_tool_error_is_not_the_answer(self) -> None:
        messages = [
            HumanMessage(content="What is the price?"),
            AIMessage(content="", tool_calls=[{"name": "web_fetch", "args": {}, "id": "1"}]),
            ToolMessage(
                content="Error: web_fetch is not a valid tool, try one of [web_search].",
                tool_call_id="1",
            ),
        ]
        assert _final_text(messages) == ""

    def test_a_trailing_successful_tool_result_is_not_the_answer_either(self) -> None:
        """Nothing about a *successful* result makes it prose. The model has to
        say something; handing over raw evidence is the same defect."""
        messages = [
            HumanMessage(content="What is the price?"),
            AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "1"}]),
            ToolMessage(content="- Bitcoin price today ... $68,493.38", tool_call_id="1"),
        ]
        assert _final_text(messages) == ""

    def test_the_model_text_before_a_tool_result_still_wins(self) -> None:
        """The walk-back's whole purpose — a loop that ended untidily should
        still return what the agent actually said."""
        messages = [
            HumanMessage(content="q"),
            AIMessage(content="Rock earns the most, $826.65."),
            AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}]),
            ToolMessage(content="Error: x is not a valid tool", tool_call_id="1"),
        ]
        assert _final_text(messages) == "Rock earns the most, $826.65."


class TestTheExistingRulesStand:
    def test_a_normal_reply_is_unchanged(self) -> None:
        assert _final_text([HumanMessage(content="q"), AIMessage(content="an answer")]) == (
            "an answer"
        )

    def test_it_still_never_echoes_the_question(self) -> None:
        assert _final_text([HumanMessage(content="q")]) == ""

    def test_it_still_skips_a_message_that_requests_tools(self) -> None:
        messages = [
            HumanMessage(content="q"),
            AIMessage(content="real answer"),
            AIMessage(content="preamble", tool_calls=[{"name": "x", "args": {}, "id": "1"}]),
        ]
        assert _final_text(messages) == "real answer"

    def test_nothing_at_all_is_empty(self) -> None:
        assert _final_text([]) == ""
