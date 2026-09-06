"""`launch-readiness/106`: a retry is told what its own findings store holds.

Read `abc/narration.py`'s `findings_inventory` and `compile/context.py`'s
`retry_inventory` before this file — this pins the seam between them: the
per-thread store `launch-readiness/105` built already survives across
attempts within a run; what was missing was the agent being *directed* to it
when `feedback` arrives. `compile/node_runtime.py`'s `_agent` composes it now,
right where it already composes `revision_request` on the `if feedback:` arm.

This file proves the mechanism with the real classes — `ReactAgentNode`,
`NarrationMiddleware`, `retry_inventory`, `revision_request` — rather than
through the full document compiler, because those are the pieces the ticket
asked to be exercised and a document-level test would exercise mostly
plumbing already covered elsewhere. Two identically-scripted runs differ in
exactly one thing: whether the second attempt's payload carries the
inventory line. That is the whole mechanism under test.

The `NarrationMiddleware` instance is built here and handed to the node as a
`middleware={"narration": ...}` contribution — never read back off the node
— because that is how `compile/node_runtime.py`'s compiler does it too
(`launch-readiness/106`): it builds the instance itself, alongside `rubric`
and `summarization`, and keeps its own reference for the retry path. Nothing
on `ReactAgentNode` grows a member for this.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from openstategraph.abc.agent import ReactAgentNode
from openstategraph.abc.narration import build_narration_middleware
from openstategraph.compile.context import retry_inventory, revision_request

CONFIG = {"configurable": {"thread_id": "t1"}}


def _reply(message: AIMessage) -> ChatResult:
    return ChatResult(generations=[ChatGeneration(message=message)])


def _make_tool(log: list[str]):
    @tool
    def mcp_describe_table(table: str) -> str:
        """Describe a table's schema."""
        log.append(table)
        return "id int, name text"

    return mcp_describe_table


class _ScriptedModel(GenericFakeChatModel):
    """Calls the tool exactly when it has no other way to answer.

    Once a real tool result is in the conversation, it answers from that.
    Failing that, it answers directly *only* when the inventory line names
    the finding it would otherwise have to fetch — modelling an agent that
    reads what it already knows instead of re-deriving it. Otherwise it
    calls the tool, exactly as a first attempt (or an uninformed retry)
    would.

    `generate_calls` counts every model round-trip — this is what `106`
    actually saves. `launch-readiness/105`'s read-through cache already
    de-duplicates the *tool execution* for an identical repeated call within
    a thread, so counting the tool's own log undercounts the waste: an
    uninformed retry still spends a full extra model turn asking for
    something the cache would have served for free, and that round-trip is
    what this ticket removes.
    """

    generate_calls: int = 0

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Any:
        return self.bind(tools=tools, tool_choice=tool_choice, **kwargs)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        object.__setattr__(self, "generate_calls", self.generate_calls + 1)
        if any(isinstance(m, ToolMessage) for m in messages):
            return _reply(AIMessage(content="Answer from the schema."))
        text = "\n".join(str(m.content) for m in messages)
        if "mcp_describe_table(" in text:
            return _reply(AIMessage(content="Answer reused from what this run already knows."))
        return _reply(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "mcp_describe_table", "args": {"table": "dim_vessel"}, "id": "call_1"}
                ],
            )
        )


def _run_two_attempts(*, carry_inventory: bool) -> tuple[list[str], int]:
    """One thread, two attempts. Returns the log of tables the tool was
    actually asked to describe, and the model round-trips spent on attempt
    two — the two things worth counting, for the two reasons above."""
    log: list[str] = []
    model = _ScriptedModel(messages=iter([]))
    # Built by this test the same way `compile/node_runtime.py` builds it —
    # as a contribution the compiler keeps its own reference to, never as
    # something fetched back off the node.
    narration_mw = build_narration_middleware()
    node = ReactAgentNode(
        name="agent_a1",
        model=model,
        tools=[_make_tool(log)],
        rules="",
        middleware={"narration": narration_mw},
    )
    agent = node.build()

    question = HumanMessage(content="Which vessel earned the most?")
    agent.invoke({"messages": [question]}, CONFIG)

    feedback_msg = HumanMessage(
        content=revision_request("Answer from the schema.", "Wrong table used.", role="author")
    )
    payload = [question, feedback_msg]
    if carry_inventory:
        entries = narration_mw.findings_inventory("t1")
        inventory_text = retry_inventory(entries)
        if inventory_text:
            payload.append(HumanMessage(content=inventory_text))
    object.__setattr__(model, "generate_calls", 0)
    agent.invoke({"messages": payload}, CONFIG)
    return log, model.generate_calls


class TestARetryIsCheaperThanTheFirstAttempt:
    def test_an_informed_retry_answers_in_one_model_call(self) -> None:
        log, calls = _run_two_attempts(carry_inventory=True)
        assert log == ["dim_vessel"], "the tool ran only on attempt one, as expected"
        assert calls == 1, (
            "the informed retry should answer directly from the inventory, "
            "not re-ask the model whether to call the tool"
        )

    def test_an_uninformed_retry_spends_a_second_model_call_asking_anyway(self) -> None:
        log, calls = _run_two_attempts(carry_inventory=False)
        # `launch-readiness/105`'s read-through cache still saves the tool's
        # own execution (the log gains nothing new) — but the model was not
        # told anything, so it spends a full extra round-trip asking for the
        # tool call before the cache silently answers it, then reasons again
        # over the cached result. That round-trip is exactly what 106 saves.
        assert log == ["dim_vessel"], "the tool cache (105) still avoids re-running the tool"
        assert calls == 2, (
            "baseline drifted — an uninformed retry must still cost the extra "
            "model round-trip or the comparison below is meaningless"
        )

    def test_the_measured_reduction(self) -> None:
        """The evidence the ticket asks for: a count, not a claim."""
        _, informed_calls = _run_two_attempts(carry_inventory=True)
        _, uninformed_calls = _run_two_attempts(carry_inventory=False)
        assert uninformed_calls - informed_calls == 1, (
            f"expected one avoided model round-trip; got {uninformed_calls} vs {informed_calls}"
        )


class TestTheMechanismIsInertWithNothingToOffer:
    def test_a_first_attempt_carries_no_inventory(self) -> None:
        """`retry_inventory` is only ever reached from the `if feedback:` arm
        in `_agent` — a first attempt has no feedback and never calls it.
        Pinned here at the composer level: nothing to inventory composes to
        nothing to say."""
        assert retry_inventory([]) == ""

    def test_an_empty_store_composes_to_nothing(self) -> None:
        from openstategraph.abc.narration import NarrationMiddleware

        mw = NarrationMiddleware(quiet=True)
        assert retry_inventory(mw.findings_inventory("some-thread-with-nothing-in-it")) == ""
