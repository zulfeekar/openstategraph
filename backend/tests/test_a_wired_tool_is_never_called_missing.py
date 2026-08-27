"""production-ready 88 — a wired, configured tool reported as missing.

Reproduced live, twice, on `chinook-assistant`: an Email Send node configured
with a recipient and wired `-> agent-chat:tools`, and the agent answered *"I
can't send that email because this workflow doesn't include an email-sending
capability"* — two supersteps, no tool call.

The ticket offered two causes and reasoned its way to the first. It is the
**second**. `plan.tool_bindings` carries `agent-chat: [the email node]` and
`runtime.last_bound_tools` for that node is `['send_email', ...]`, so the
binding is fine and `openstategraph validate` says so too. What the agent was
told is the defect: that package's `agent-chat` rules open *"You hold no tools
and no database access"* and repeat *"You have no tools, so you have consulted
nothing."* Both were true when they were written. Then the capability door
wired a tool to that agent, and nothing in the prompt caught up — the model was
told only what could be **added** to it (`advisor_context`) and never what it
already **holds**.

So the fix is a generated context section naming the tools actually bound, with
an explicit precedence sentence, because the stale claim is authored prose and
authored prose renders after context. It is not a fix to that one package's
wording: every agent whose rules mention its tools goes stale the moment the
door adds one.
"""

from __future__ import annotations

from typing import Any

from openstategraph.api.services import WorkflowServices
from openstategraph.compile.node_runtime import held_tools_context
from openstategraph.compile.workflow_compiler import WorkflowCompiler


def _runtime(tmp_path: Any, document: dict[str, Any], model: Any = None) -> Any:
    """A runtime carrying the real prebuilt tool registry — a bare
    `NodeRuntime` has an empty one, which would make this whole file pass by
    proving nothing."""
    return WorkflowServices(tmp_path).runtime_for(None, document, model, warnings=[])


class _Tool:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


class TestHeldToolsContext:
    def test_it_names_every_tool_bound_to_this_node(self) -> None:
        text = held_tools_context([_Tool("send_email", "Send an email report.")])
        assert "send_email" in text
        assert "Send an email report." in text

    def test_it_overrides_a_stale_claim_of_having_none(self) -> None:
        """The load-bearing sentence. Context renders *before* rules, and the
        rules are where the false claim lives, so saying only "you have
        send_email" leaves the contradiction for the model to resolve by
        recency. It has to be told which side is authoritative."""
        text = held_tools_context([_Tool("send_email")]).lower()
        assert "authoritative" in text
        assert "rules" in text

    def test_it_forbids_calling_a_held_capability_missing(self) -> None:
        """The exact sentence the live run produced, forbidden by name — and
        the counterpart to `advisor_context`'s "a tool that ran and returned an
        error is NOT a missing capability"."""
        text = held_tools_context([_Tool("send_email")]).lower()
        assert "never" in text
        assert "missing" in text

    def test_an_agent_with_no_tools_gets_nothing(self) -> None:
        """Most agents hold nothing; they must not pay for this, and must not
        be handed an empty list to reason about."""
        assert held_tools_context([]) == ""


def _routed_document() -> dict[str, Any]:
    """The shape of the live defect: an agent reached by a **router branch**,
    with a tool bound to it, whose authored rules deny holding any tool.

    The branch matters. `workflow-gallery` 32 found a conditional edge missing
    from `plan.edges`, and the ticket's first lead was that the same gap ate
    the tool binding here. It does not — bindings are gathered from the binding
    edge itself, not from an upstream walk — and this document is what proves
    the branch is not the variable.
    """
    return {
        "version": 2,
        "name": "front-desk",
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {
                "id": "router1",
                "type": "route.classifier",
                "data": {"rules": "- chat — anything conversational", "fallback": "chat"},
            },
            {
                "id": "agent-chat",
                "type": "agent.llm",
                "data": {
                    "tier": "react",
                    "systemPrompt": (
                        "You are the front desk. You hold no tools and no database "
                        "access. You have no tools, so you have consulted nothing."
                    ),
                },
            },
            {"id": "mail1", "type": "tool.email-send", "data": {"to": "boss@example.com"}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "router1", "portId": "question"},
            },
            {
                "source": {"nodeId": "router1", "portId": "branch:chat"},
                "target": {"nodeId": "agent-chat", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "mail1", "portId": "tool"},
                "target": {"nodeId": "agent-chat", "portId": "tools"},
            },
            {
                "source": {"nodeId": "agent-chat", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


class TestTheAgentIsToldWhatItHolds:
    """The end-to-end half: not that a registry contains `tool.email-send`, but
    that the string reaching *this* agent's model names the tool it was wired.
    """

    def _system_prompt(self, tmp_path: Any, document: dict[str, Any]) -> str:
        captured: dict[str, str] = {}

        from openstategraph.abc import agent as agent_family

        original = agent_family.BaseAgentNode.build

        class _Stub:
            async def ainvoke(self, _payload: Any) -> dict[str, Any]:
                return {"messages": []}

        def spy(self: Any) -> Any:
            # `resolve_prompt()` rather than the `system_prompt=` kwarg, so the
            # assertion is on the seam the architecture names as the single
            # place config becomes a prompt.
            captured["prompt"] = self.resolve_prompt() or ""
            return _Stub()

        agent_family.BaseAgentNode.build = spy  # type: ignore[method-assign]
        try:
            plan = WorkflowCompiler().plan(document)
            # A model that is merely *not None*: `_agent` short-circuits to an
            # empty answer without one, and never composes a prompt at all.
            # A real fake rather than a bare sentinel, because
            # `SummarizationMiddleware` inspects the model while the node is
            # still being assembled — before `build` is ever reached.
            from langchain_core.language_models.fake_chat_models import (
                GenericFakeChatModel,
            )

            runtime = _runtime(
                tmp_path, document, model=GenericFakeChatModel(messages=iter([]))
            )
            node = {n["id"]: n for n in document["nodes"]}["agent-chat"]
            from conftest import drive_node

            step = runtime.factory(document)("agent-chat", node, plan)
            drive_node(step, {"question": "email the boss a summary"})
        finally:
            agent_family.BaseAgentNode.build = original  # type: ignore[method-assign]
        return captured.get("prompt", "")

    def test_the_binding_itself_was_never_the_defect(self, tmp_path: Any) -> None:
        """Half of the ticket, settled before anything is asserted about the
        prompt: the tool *is* bound to an agent behind a router branch."""
        document = _routed_document()
        plan = WorkflowCompiler().plan(document)
        assert plan.tool_bindings == {"agent-chat": ["mail1"]}

        runtime = _runtime(tmp_path, document)
        node = {n["id"]: n for n in document["nodes"]}["agent-chat"]
        runtime.factory(document)("agent-chat", node, plan)
        assert "send_email" in runtime.last_bound_tools

    def test_the_prompt_names_the_tool_the_canvas_wired(self, tmp_path: Any) -> None:
        prompt = self._system_prompt(tmp_path, _routed_document())
        assert "send_email" in prompt

    def test_the_authored_denial_is_still_present_and_still_overruled(self, tmp_path: Any) -> None:
        """We do not edit the developer's rules — they are the one part that is
        theirs. The correction sits above them and says which wins."""
        prompt = self._system_prompt(tmp_path, _routed_document())
        assert "You hold no tools" in prompt
        assert "authoritative" in prompt.lower()

    def test_the_list_is_the_wiring_and_not_a_catalogue(self, tmp_path: Any) -> None:
        """Unwire the tool and the claim goes with it. The block reports what
        was bound, so it can never become a second, staler catalogue of its
        own — the failure it exists to fix.

        Note the block itself does not vanish here: a memory store binds
        `save_memory` and friends to every agent alive, and those are tools the
        agent genuinely holds. `held_tools_context([])` is where the empty case
        is pinned."""
        document = _routed_document()
        document["edges"] = [e for e in document["edges"] if e["source"]["nodeId"] != "mail1"]
        document["nodes"] = [n for n in document["nodes"] if n["id"] != "mail1"]
        prompt = self._system_prompt(tmp_path, document)
        assert "send_email" not in prompt
