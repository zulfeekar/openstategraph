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


def _message(content: str, tool_calls: list[dict[str, Any]] | None = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls or [], type="ai")


def _agent_answer(monkeypatch: pytest.MonkeyPatch, messages: list[Any]) -> str:
    """Runs a real `agent.llm` factory whose loop returns `messages`."""
    from openstategraph.abc import agent as agent_family

    class StubTier:
        def __init__(self, **_: Any) -> None: ...

        def build(self) -> Any:
            return SimpleNamespace(invoke=lambda _invocation: {"messages": messages})

    monkeypatch.setattr(agent_family, "agent_node_for_tier", lambda _tier: StubTier)

    document = {"nodes": [{"id": "a1", "type": "agent.llm", "data": {}}], "edges": []}
    plan = CompiledPlan(nodes=["a1"], edges=[], conditional={})
    runtime = NodeRuntime(model=SimpleNamespace(name="stub"))
    run = runtime.factory(document)("a1", document["nodes"][0], plan)
    return run({"question": "q", "attempts": 0, "messages": [], "outputs": {}, "decisions": {}})[
        "answer"
    ]


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
                return SimpleNamespace(
                    invoke=lambda _i: {"messages": [_message(ANSWER), _message("")]}
                )

        monkeypatch.setattr(agent_family, "agent_node_for_tier", lambda _t: StubTier)
        document = {"nodes": [{"id": "a1", "type": "agent.llm", "data": {}}], "edges": []}
        plan = CompiledPlan(nodes=["a1"], edges=[], conditional={})
        runtime = NodeRuntime(model=SimpleNamespace(name="stub"))
        update = runtime.factory(document)("a1", document["nodes"][0], plan)(
            {"question": "q", "attempts": 0, "messages": [], "outputs": {}, "decisions": {}}
        )
        assert update["outputs"]["a1"] == update["answer"] == ANSWER
