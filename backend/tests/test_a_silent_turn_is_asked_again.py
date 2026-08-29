"""A model that ends its turn without writing is asked once for the answer.

`launch-readiness/185`, and the measurement that decided it. The owner asked
`chinook-assistant` *"combine most sold tracks and top artists"* and got

    I could not produce an answer after 3 attempts. The last review said:
    The answer is empty.

after thirty seconds of real work — seven model calls and seven tool calls on
the first lap alone.

**The extraction was not the defect.** `185` asked first whether the agent's
final message is genuinely empty or lost after the agent, because those are two
defects with two owners. It was captured off a live reproduction:

    {"type": "ai", "content": "", "tool_calls": [],
     "response_metadata": {"done_reason": "stop", "eval_count": 92,
                           "model": "gpt-oss:120b-cloud"}}

`eval_count` is 92 — the model generated ninety-two tokens and published none
of them as content. `_final_text` returned "" and was **right** to: there was
nothing there. `production-ready/96` had already settled the same fact off the
raw Ollama wire, and this is the second measurement of it.

**What was the defect is that nothing tried again.** The grader's revise edge
sent `The answer is empty.` back to the agent, which re-ran the whole tool
sequence and ended silent again, three times, because a silent turn is not a
content problem and no amount of feedback about the content addresses it. The
recovery is one more ask, with the tool results already in the conversation and
no tools bound — measured on the reproduction, it recovered **four of five**
silent turns, at a cost of one short model call on a path that otherwise
produced nothing at all.

This is the tolerant-reading rule (`CLAUDE.md`) applied one layer out. Tolerance
here is narrow on purpose and the narrowness is the safety: the nudge is asked
**once**, only when the loop actually got somewhere, and its reply is subject
to exactly the checks any other answer is. A silent nudge stays silent — the
nearest string is never published, which is `_final_text`'s own rule and the one
that keeps a tool's error out of a customer's chat.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from openstategraph.compile.silent_turn import NUDGE, text_or_ask_again


class Recorder:
    """A model that records what it was asked and answers from a script."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.calls: list[list[Any]] = []

    async def ainvoke(self, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        self.calls.append(list(messages))
        if not self.replies:
            raise AssertionError("asked more times than the script allows")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def worked_then_said_nothing() -> list[Any]:
    """The shape measured live: tools ran, then the turn ended empty."""
    return [
        HumanMessage(content="combine most sold tracks and top artists"),
        AIMessage(content="", tool_calls=[{"name": "chinook_execute_sql", "args": {}, "id": "1"}]),
        ToolMessage(content="| Track | Units |\n| Balls to the Wall | 2 |", tool_call_id="1"),
        AIMessage(content=""),
    ]


class TestTheAnswerThatIsThereIsNeverPaidForTwice:
    def test_a_turn_that_said_something_returns_it(self) -> None:
        model = Recorder()
        messages = [HumanMessage(content="q"), AIMessage(content="Rock, $826.65")]
        assert asyncio.run(text_or_ask_again(messages, model)) == "Rock, $826.65"

    def test_and_never_calls_the_model(self) -> None:
        model = Recorder()
        messages = [HumanMessage(content="q"), AIMessage(content="Rock, $826.65")]
        asyncio.run(text_or_ask_again(messages, model))
        assert model.calls == []


class TestASilentTurnIsAskedOnce:
    def test_the_nudged_reply_becomes_the_answer(self) -> None:
        model = Recorder(AIMessage(content="Iron Maiden, 140 units."))
        answer = asyncio.run(text_or_ask_again(worked_then_said_nothing(), model))
        assert answer == "Iron Maiden, 140 units."

    def test_exactly_once(self) -> None:
        model = Recorder(AIMessage(content="Iron Maiden, 140 units."))
        asyncio.run(text_or_ask_again(worked_then_said_nothing(), model))
        assert len(model.calls) == 1

    def test_the_ask_carries_the_whole_turn_and_one_instruction(self) -> None:
        # The tool results are the reason this works at all: the model is not
        # being asked to do the work again, it is being asked to write down
        # what it already has.
        model = Recorder(AIMessage(content="done"))
        asyncio.run(text_or_ask_again(worked_then_said_nothing(), model))
        asked = model.calls[0]
        assert len(asked) == 5
        assert asked[:4] == worked_then_said_nothing()
        assert asked[-1].content == NUDGE

    def test_the_instruction_forbids_more_tool_calls(self) -> None:
        # A nudge that invited another tool call would restart the loop this
        # is meant to end, and the node has no budget left to spend on one.
        assert "tool" in NUDGE.lower()

    def test_a_reply_in_content_blocks_is_read_the_same_way(self) -> None:
        # `content_text`, not `str(content)`. A provider that answers in
        # blocks is the case that made `_final_text` skip a full message and
        # publish the user's own question back — the-editor-makes-a-real-
        # package 03, and the one wrong answer nothing downstream can catch.
        model = Recorder(
            AIMessage(content=[{"type": "text", "text": "Iron Maiden, 140 units."}])
        )
        answer = asyncio.run(text_or_ask_again(worked_then_said_nothing(), model))
        assert answer == "Iron Maiden, 140 units."


class TestSilenceStaysSilent:
    def test_a_nudge_that_says_nothing_publishes_nothing(self) -> None:
        model = Recorder(AIMessage(content=""))
        assert asyncio.run(text_or_ask_again(worked_then_said_nothing(), model)) == ""

    def test_the_tool_result_is_never_published_instead(self) -> None:
        # `_final_text`'s rule, unchanged by this one: a tool result is
        # evidence for the model, not prose for a person.
        model = Recorder(AIMessage(content=""))
        answer = asyncio.run(text_or_ask_again(worked_then_said_nothing(), model))
        assert "Balls to the Wall" not in answer

    def test_a_nudge_that_raises_costs_the_answer_and_not_the_run(self) -> None:
        # Tolerant, for `Grader.normalise`'s reason: a recoverable silence
        # must not become a dead run because the second ask hit a 500 — which
        # is exactly what this provider was observed doing under this load.
        model = Recorder(RuntimeError("Internal Server Error (status code: 500)"))
        assert asyncio.run(text_or_ask_again(worked_then_said_nothing(), model)) == ""


class TestWhatIsNeverWorthAModelCall:
    def test_no_model_asks_nobody(self) -> None:
        assert asyncio.run(text_or_ask_again(worked_then_said_nothing(), None)) == ""

    def test_a_conversation_that_never_left_the_human_turn(self) -> None:
        # Nothing ran, so there is nothing to write the answer *from*, and a
        # nudge would only ask the model to answer from memory — which is the
        # one thing every grounded node in this catalogue forbids.
        model = Recorder()
        assert asyncio.run(text_or_ask_again([HumanMessage(content="q")], model)) == ""
        assert model.calls == []

    def test_an_empty_conversation(self) -> None:
        model = Recorder()
        assert asyncio.run(text_or_ask_again([], model)) == ""
        assert model.calls == []
