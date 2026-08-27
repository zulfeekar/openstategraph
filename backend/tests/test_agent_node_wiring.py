"""`NodeRuntime._agent` delegates to the agent family — no inline construction.

Pins the two behaviours the old inline `create_agent(...)` call silently
lacked: a node's authored ``systemPrompt`` reaches the constructor (it used
to be dropped — three nodes in the video-game workflow carried one and none
did anything), and ``tier: "deep"`` selects ``create_deep_agent`` for the
*agent itself* (previously only Router/Grader honoured their tier).
"""

from __future__ import annotations

import openstategraph.abc.agent as agent_module
from openstategraph.abc.agent import DeepAgentNode, ReactAgentNode
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import CompiledPlan

from conftest import drive_node


class RecordingNode(ReactAgentNode):
    """A ReactAgentNode whose build records instead of constructing."""

    built: list["RecordingNode"] = []

    def build(self):
        RecordingNode.built.append(self)
        return None  # runtime treats an unbuildable agent as model-missing


class RecordingDeepNode(DeepAgentNode):
    built: list["RecordingDeepNode"] = []

    def build(self):
        RecordingDeepNode.built.append(self)
        return None


def _run_factory(monkeypatch, data: dict) -> None:
    RecordingNode.built.clear()
    RecordingDeepNode.built.clear()
    monkeypatch.setattr(
        agent_module,
        "agent_node_for_tier",
        lambda tier: RecordingDeepNode if tier == "deep" else RecordingNode,
    )
    # A real fake chat model rather than the `object()` sentinel this used to
    # pass. Summarization is on by default now, so building an agent
    # constructs `SummarizationMiddleware`, which asks the model for
    # `_llm_type` to tune its token counter — a question `object()` cannot
    # answer. In production the model is always a `BaseChatModel` or the
    # `UnconfiguredProvider` stand-in, never a bare object.
    runtime = NodeRuntime(model=_summarizing_model())
    node = {"id": "a1", "type": "agent.llm", "data": data}
    run = runtime._agent("a1", node, CompiledPlan())
    drive_node(run, RunState(question="q"))  # type: ignore[typeddict-item]


class TestAgentNodeDelegation:
    def test_the_authored_system_prompt_reaches_the_family(self, monkeypatch) -> None:
        _run_factory(monkeypatch, {"systemPrompt": "You are a data analyst."})
        (built,) = RecordingNode.built
        prompt = built.resolve_prompt()
        assert prompt is not None and "You are a data analyst." in prompt

    def test_tier_deep_selects_the_deep_sibling(self, monkeypatch) -> None:
        _run_factory(monkeypatch, {"tier": "deep"})
        assert len(RecordingDeepNode.built) == 1
        assert not RecordingNode.built

    def test_default_tier_is_react(self, monkeypatch) -> None:
        _run_factory(monkeypatch, {})
        assert len(RecordingNode.built) == 1


def _summarizing_model(summary: str = "SUMMARY OF EARLIER TURNS"):
    """A model that answers any summarization request with `summary`."""
    from langchain_core.language_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    return GenericFakeChatModel(messages=iter([AIMessage(content=summary)] * 50))


def _long_conversation(turns: int, words_per_turn: int = 400) -> list:
    """A conversation whose approximate token count clears the absolute trigger.

    `count_tokens_approximately` is what the middleware counts with, so the
    test builds real messages and lets it do the counting rather than asserting
    against a number this file invented.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    filler = " ".join(f"word{index}" for index in range(words_per_turn))
    messages: list = []
    for turn in range(turns):
        messages.append(HumanMessage(content=f"question {turn}: {filler}"))
        messages.append(AIMessage(content=f"answer {turn}: {filler}"))
    return messages


class TestSummarizationFires:
    """It is not enough that the slot is filled — it has to *fire*.

    The test this replaces (`test_summarize_true_contributes_the_slot`) asserted
    the middleware was *contributed*, and it was green for a year over a
    `SummarizationMiddleware(model=model)` built with **no trigger** — which the
    library documents as "will not trigger automatically". A developer who found
    the toggle and turned it on got nothing, and the suite said the feature
    worked. So the assertion moves to the only thing that was ever the point: a
    conversation that crosses the threshold comes back summarized, with its
    recent tail intact.
    """

    def _built_with(self, monkeypatch, data: dict) -> RecordingNode:
        RecordingNode.built.clear()
        monkeypatch.setattr(
            agent_module, "agent_node_for_tier", lambda tier: RecordingNode
        )
        runtime = NodeRuntime(model=_summarizing_model())
        node = {"id": "a1", "type": "agent.llm", "data": data}
        run = runtime._agent("a1", node, CompiledPlan())
        drive_node(run, RunState(question="q"))  # type: ignore[typeddict-item]
        (built,) = RecordingNode.built
        return built

    def _summarization(self, monkeypatch, data: dict):
        return self._built_with(monkeypatch, data)._middleware_contributions[
            "summarization"
        ]

    def test_an_unconfigured_agent_summarizes_a_long_conversation(
        self, monkeypatch
    ) -> None:
        """The whole feature, end to end: no configuration at all, a thread
        that got long, and a state update that replaced it with a summary."""
        from langchain_core.messages import RemoveMessage

        middleware = self._summarization(monkeypatch, {})
        messages = _long_conversation(turns=100)
        update = middleware.before_model({"messages": messages}, None)
        assert update is not None, "a 100-turn conversation did not summarize"
        new_messages = update["messages"]
        assert isinstance(new_messages[0], RemoveMessage)
        assert any(
            "SUMMARY OF EARLIER TURNS" in str(getattr(message, "content", ""))
            for message in new_messages
        )

    def test_the_recent_tail_is_kept_verbatim(self, monkeypatch) -> None:
        """`keep` is pinned, not inherited: the last turns must survive the
        summary, or the agent forgets what it was just asked."""
        middleware = self._summarization(monkeypatch, {})
        messages = _long_conversation(turns=100)
        update = middleware.before_model({"messages": messages}, None)
        assert update is not None
        kept = [
            message
            for message in update["messages"]
            if getattr(message, "id", None) is not None
            and message in messages
        ]
        assert len(kept) >= 10, "the recent tail was not preserved"
        assert kept[-1] is messages[-1]

    def test_a_short_conversation_is_left_alone(self, monkeypatch) -> None:
        """The other half of a trigger: below the threshold it does nothing.
        A middleware that summarized every turn would be as broken as one that
        never did."""
        middleware = self._summarization(monkeypatch, {})
        assert middleware.before_model({"messages": _long_conversation(turns=2)}, None) is None

    def test_the_fraction_clause_fires_where_a_model_reports_a_profile(
        self, monkeypatch
    ) -> None:
        """The owner's 0.8, doing its job.

        The absolute clause alone would not fire here — the conversation is far
        under it — so a pass proves the fraction reached the model's profile.
        """
        model = _summarizing_model()
        monkeypatch.setattr(
            type(model), "profile", property(lambda _self: {"max_input_tokens": 4_000}),
            raising=False,
        )
        RecordingNode.built.clear()
        monkeypatch.setattr(
            agent_module, "agent_node_for_tier", lambda tier: RecordingNode
        )
        runtime = NodeRuntime(model=model)
        run = runtime._agent("a1", {"id": "a1", "type": "agent.llm", "data": {}}, CompiledPlan())
        drive_node(run, RunState(question="q"))  # type: ignore[typeddict-item]
        (built,) = RecordingNode.built
        middleware = built._middleware_contributions["summarization"]
        # Enough messages to leave a cutoff after `keep=("messages", 20)`, and
        # nowhere near the 100k absolute — so only the fraction can explain a
        # pass.
        messages = _long_conversation(turns=30, words_per_turn=60)
        assert middleware.before_model({"messages": messages}, None) is not None

    def test_summarize_defaults_to_on(self, monkeypatch) -> None:
        """A document that never mentions `summarize` gets it. The 22 shipped
        examples are exactly that document."""
        built = self._built_with(monkeypatch, {})
        assert "summarization" in built._middleware_contributions

    def test_an_explicit_false_is_still_a_choice(self, monkeypatch) -> None:
        """The toggle still turns it off — and an editor-saved document written
        before the default flipped carries a literal `false`, which stays a
        `false`. Opening a document must never change what it does."""
        built = self._built_with(monkeypatch, {"summarize": False})
        assert "summarization" not in built._middleware_contributions


def _mount_chain() -> tuple[dict, dict]:
    """Parent mounts child mounts grandchild; the agent is at the bottom.

    Ticket 36's second half — *"the same holds one and two mounts deep"* — and
    it is not a formality: the `machinery_nodes` merge proved that a level can
    be silently dropped between a parent and a grandchild, so "the compiler
    does it everywhere" is a claim to test rather than to assume.
    """
    grandchild = {
        "version": 2,
        "name": "grandchild",
        "nodes": [
            {"id": "gin", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "g-agent", "type": "agent.llm", "position": {"x": 200, "y": 0}, "data": {}},
            {"id": "gout", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "gin", "portId": "text"},
                "target": {"nodeId": "g-agent", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "g-agent", "portId": "result"},
                "target": {"nodeId": "gout", "portId": "result"},
            },
        ],
    }
    child = {
        "version": 2,
        "name": "child",
        "nodes": [
            {"id": "cin", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "c-mount",
                "type": "workflow.subgraph",
                "position": {"x": 200, "y": 0},
                "data": {"workflow": "grandchild-flow"},
            },
            {"id": "cout", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "cin", "portId": "text"},
                "target": {"nodeId": "c-mount", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "c-mount", "portId": "report"},
                "target": {"nodeId": "cout", "portId": "result"},
            },
        ],
    }
    parent = {
        "version": 2,
        "name": "parent",
        "nodes": [
            {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "p-mount",
                "type": "workflow.subgraph",
                "position": {"x": 200, "y": 0},
                "data": {"workflow": "child-flow"},
            },
            {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "p-mount", "portId": "candidate"},
            },
            {
                "source": {"nodeId": "p-mount", "portId": "report"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }
    return parent, {"child-flow": child, "grandchild-flow": grandchild}


class TestTheDefaultReachesEveryDepth:
    """A mounted document's agents inherit the same default, or the promise is
    only true for whatever happens to be the outermost document."""

    def test_an_agent_two_mounts_deep_summarizes_too(self, monkeypatch) -> None:
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        RecordingNode.built.clear()
        monkeypatch.setattr(
            agent_module, "agent_node_for_tier", lambda tier: RecordingNode
        )
        parent, documents = _mount_chain()
        runtime = NodeRuntime(
            model=_summarizing_model(), document_loader=documents.__getitem__
        )
        graph = WorkflowCompiler().build(parent, RunState, runtime.factory(parent))
        graph.invoke(RunState(question="q"))  # type: ignore[typeddict-item]

        assert RecordingNode.built, "the grandchild's agent was never built"
        (built,) = RecordingNode.built
        middleware = built._middleware_contributions["summarization"]
        assert (
            middleware.before_model({"messages": _long_conversation(turns=100)}, None)
            is not None
        )
