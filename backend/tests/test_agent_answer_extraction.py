"""An agent reports what it actually said, not whatever message came last.

From a live `chinook-assistant` run (2026-08-13), captured off the wire:

    agent-sql  → ""      (attempt 1)
    agent-sql  → ""      (attempt 2)
    agent-sql  → ""      (attempt 3)
    grader-sql → "I could not produce an answer after 3 attempts.
                  The last review said: The answer is empty."

The same question invoked against the same node outside the stream answered
correctly, with a two-join `GROUP BY` and the five artists. The provider
(Ollama cloud) intermittently ends a tool-heavy loop on a message with no
content — a 500 swallowed by the loop, or a dangling tool call — and
`messages[-1].content` then records "" as the agent's entire answer.

`_final_text` exists for exactly this and carries the reasoning (ticket 61,
found under concurrent fan-out). `_worker` and `_ModelShim` both use it.
`_agent` — the node type every shipped workflow is built from — did not, so
the one place the defect was most visible was the one place unprotected.

The cost is not only a blank card: a grader downstream reads "" as a failed
answer and spends its whole retry budget re-asking a question that was
already answered correctly.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import any_chat_model, drive_node


def _message(content: str, tool_calls: list[dict[str, Any]] | None = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls or [], type="ai")


def _agent_answer(monkeypatch: pytest.MonkeyPatch, messages: list[Any]) -> str:
    """Runs a real `agent.llm` factory whose loop returns `messages`."""
    from openstategraph.abc import agent as agent_family

    class StubTier:
        def __init__(self, **_: Any) -> None: ...

        def build(self) -> Any:
            async def ainvoke(_invocation: Any) -> Any:
                return {"messages": messages}

            return SimpleNamespace(ainvoke=ainvoke)

    monkeypatch.setattr(agent_family, "agent_node_for_tier", lambda _tier: StubTier)

    document = {"nodes": [{"id": "a1", "type": "agent.llm", "data": {}}], "edges": []}
    plan = CompiledPlan(nodes=["a1"], edges=[], conditional={})
    runtime = NodeRuntime(model=any_chat_model())
    run = runtime.factory(document)("a1", document["nodes"][0], plan)
    return drive_node(
        run, {"question": "q", "attempts": 0, "messages": [], "outputs": {}, "decisions": {}}
    )["answer"]


ANSWER = "Iron Maiden leads with $138.60.\n\n```sql\nSELECT ...\n```"


class TestAnAgentKeepsWhatItSaid:
    def test_a_loop_that_ends_on_an_empty_message_still_reports_the_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect itself, in the shape the wire recorded it."""
        answer = _agent_answer(
            monkeypatch, [_message("q"), _message(ANSWER), _message("")]
        )
        assert answer == ANSWER

    def test_a_dangling_tool_call_is_not_the_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A message that *requests* tools is preamble, never the reply —
        the failure that rendered `{"path": ...}` to a customer."""
        answer = _agent_answer(
            monkeypatch,
            [
                _message(ANSWER),
                _message('{"query": "SELECT 1"}', [{"name": "chinook_execute_sql"}]),
            ],
        )
        assert answer == ANSWER

    def test_a_normal_loop_is_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _agent_answer(monkeypatch, [_message("q"), _message(ANSWER)]) == ANSWER

    def test_a_loop_that_truly_said_nothing_still_reports_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The floor belongs to `_output`, which is the one node that can
        promise the run says something (`test_never_an_empty_answer`). This
        node must not invent an answer to fill the gap."""
        assert _agent_answer(monkeypatch, [_message(""), _message("")]) == ""

    def test_the_agents_output_channel_agrees_with_its_answer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`outputs[node]` is what a grader downstream reads; the two drifting
        apart is how a correct answer gets three retries."""
        from openstategraph.abc import agent as agent_family

        class StubTier:
            def __init__(self, **_: Any) -> None: ...

            def build(self) -> Any:
                async def ainvoke(_i: Any) -> Any:
                    return {"messages": [_message(ANSWER), _message("")]}

                return SimpleNamespace(ainvoke=ainvoke)

        monkeypatch.setattr(agent_family, "agent_node_for_tier", lambda _t: StubTier)
        document = {"nodes": [{"id": "a1", "type": "agent.llm", "data": {}}], "edges": []}
        plan = CompiledPlan(nodes=["a1"], edges=[], conditional={})
        runtime = NodeRuntime(model=any_chat_model())
        update = drive_node(
            runtime.factory(document)("a1", document["nodes"][0], plan),
            {"question": "q", "attempts": 0, "messages": [], "outputs": {}, "decisions": {}},
        )
        assert update["outputs"]["a1"] == update["answer"] == ANSWER


class TestStreamedContentBlocks:
    """The same extraction, against the shape token streaming actually produces.

    Found by ticket 03, driving the wheel in a browser: `POST /api/runs`
    answered `49` and `POST /api/runs/stream` answered **the question**, same
    workflow, same server, seconds apart. Both shipped UIs — the editor's Ask
    panel and the customer `/chat` — use the streaming endpoint, so every run
    a person could see was wrong while every run a test made was right.

    The cause is one `isinstance` against a documented union. LangChain's
    message `content` is "loosely-typed, supporting strings and lists of
    untyped objects", and an Anthropic `AIMessage` in particular "can either
    be a single string or a list of content blocks". Adding `"messages"` to
    `stream_mode` makes the settled AI message arrive in the block form:

        content=[{'text': '30', 'type': 'text', 'index': 0}]

    `isinstance(content, str)` is False for that, so the walk-back designed to
    skip *empty* messages skipped a full one — and kept walking, onto the
    `HumanMessage`, and returned the user's own question as the agent's answer.

    Two fixes, because two things were wrong. `_content_text` reads both
    shapes — joining only the `text` blocks, so a thinking model's reasoning
    stays out — and the walk now stops at the last human turn: an answer can
    be missing, but it can never be something the *user* said.
    """

    def test_a_streamed_block_list_reads_as_its_text(self) -> None:
        from langchain_core.messages import AIMessage, HumanMessage

        from openstategraph.compile.node_runtime import _final_text

        messages = [
            HumanMessage(content="What is 5 * 6? Reply with just the number."),
            AIMessage(content=[{"text": "30", "type": "text", "index": 0}]),
        ]

        assert _final_text(messages) == "30"

    def test_multiple_text_blocks_are_joined_in_order(self) -> None:
        from langchain_core.messages import AIMessage

        from openstategraph.compile.node_runtime import _final_text

        message = AIMessage(
            content=[
                {"text": "The genre is ", "type": "text", "index": 0},
                {"text": "Rock.", "type": "text", "index": 1},
            ]
        )

        assert _final_text([message]) == "The genre is Rock."

    def test_a_reasoning_block_is_not_the_answer(self) -> None:
        # Thinking models put reasoning in the same list. Concatenating it
        # blind would show a customer the model's private deliberation.
        from langchain_core.messages import AIMessage

        from openstategraph.compile.node_runtime import _final_text

        message = AIMessage(
            content=[
                {"type": "thinking", "thinking": "6 times 5 is 30", "signature": "x"},
                {"type": "text", "text": "30"},
            ]
        )

        assert _final_text([message]) == "30"

    def test_it_never_returns_the_users_own_question(self) -> None:
        # The failure this ticket found, reduced. Whatever goes wrong upstream,
        # echoing the question back is the one answer that must never happen:
        # it is indistinguishable from a real reply, so nothing downstream —
        # not the grader, not the customer — can tell it failed.
        from langchain_core.messages import AIMessage, HumanMessage

        from openstategraph.compile.node_runtime import _final_text

        messages = [
            HumanMessage(content="Which genre earns the most revenue?"),
            AIMessage(content=""),
        ]

        assert _final_text(messages) == ""

    def test_it_does_not_reach_back_past_a_human_turn(self) -> None:
        # A multi-turn thread: an earlier answer is not this turn's answer.
        # Returning it would be a stale reply presented as a fresh one.
        from langchain_core.messages import AIMessage, HumanMessage

        from openstategraph.compile.node_runtime import _final_text

        messages = [
            HumanMessage(content="What is 2 + 2?"),
            AIMessage(content="4"),
            HumanMessage(content="And 3 + 3?"),
            AIMessage(content=""),
        ]

        assert _final_text(messages) == ""
