"""The agent ladder: ``IAgent`` → ``AbstractAgentNode`` → ``Base/React/Deep/Custom``.

CLAUDE.md's three-tier table made concrete. The base holds the minimum —
the three resolvers and one template method — and a concrete supplies only
what makes it that tier: which constructor it calls and which middleware
slots it presets. ``DeepAgentNode`` is a **sibling** of ``ReactAgentNode``,
never a subclass: the deepagents stack is data (a slot preset), and
expressing it as inheritance was already tried and retracted (CLAUDE.md).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from openstategraph.abc.agent import (
    AbstractAgentNode,
    BaseAgentNode,
    CustomGraphNode,
    DeepAgentNode,
    IAgent,
    ReactAgentNode,
    agent_node_for_tier,
)
from openstategraph.abc.middleware import MiddlewareSlotTable


class FakeMiddleware:
    """Stands in for a langchain AgentMiddleware; identity is all we need."""

    def __init__(self, tag: str) -> None:
        self.tag = tag


class TestMiddlewareSlotTable:
    def test_flattens_in_canonical_order_not_insertion_order(self) -> None:
        table = MiddlewareSlotTable(order=("summarize", "limit", "patch"))
        patch, summarize = FakeMiddleware("patch"), FakeMiddleware("summarize")
        table.set("patch", patch)
        table.set("summarize", summarize)
        assert table.flatten() == [summarize, patch]

    def test_replacement_is_by_slot_name(self) -> None:
        table = MiddlewareSlotTable(order=("logging",))
        first, second = FakeMiddleware("a"), FakeMiddleware("b")
        table.set("logging", first)
        table.set("logging", second)
        assert table.flatten() == [second]

    def test_unknown_slots_append_after_canonical_in_insertion_order(self) -> None:
        table = MiddlewareSlotTable(order=("core",))
        core, custom1, custom2 = (FakeMiddleware(t) for t in ("core", "c1", "c2"))
        table.set("my-first", custom1)
        table.set("core", core)
        table.set("my-second", custom2)
        assert table.flatten() == [core, custom1, custom2]

    def test_remove_empties_a_slot(self) -> None:
        table = MiddlewareSlotTable(order=("a",))
        table.set("a", FakeMiddleware("a"))
        table.remove("a")
        assert table.flatten() == []

    def test_no_numeric_ordering_api_exists(self) -> None:
        """A priority integer would claim to express what before/after/wrap
        semantics make inexpressible; the API must not offer one."""
        assert not hasattr(MiddlewareSlotTable, "insert_at")
        assert not hasattr(MiddlewareSlotTable, "priority")


class Recorder:
    """Captures what a concrete's constructor call would have received."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(kind="compiled-agent", **kwargs)


class TestAbstractAgentNode:
    def test_the_ladder_shape(self) -> None:
        assert issubclass(BaseAgentNode, AbstractAgentNode)
        assert issubclass(ReactAgentNode, BaseAgentNode)
        assert issubclass(DeepAgentNode, BaseAgentNode)
        # Sibling, not child: deep must NOT inherit react's identity.
        assert not issubclass(DeepAgentNode, ReactAgentNode)

    def test_satisfies_the_protocol(self) -> None:
        node = ReactAgentNode(name="a1", model=object())
        assert isinstance(node, IAgent)

    def test_resolve_prompt_composes_rules_when_present(self) -> None:
        node = ReactAgentNode(name="a1", model=object(), rules="Answer in French.")
        prompt = node.resolve_prompt()
        assert prompt is not None and "Answer in French." in prompt

    def test_an_unconfigured_agent_inherits_the_base_default_rules(self) -> None:
        """**Reversed by one-chinook ticket 10, deliberately.** This used to
        assert `resolve_prompt() is None` — "no prompt means create_agent gets
        no system_prompt at all, and an empty string would still override the
        library's default".

        That reading lost to the owner's bar: an Agent dropped on a blank
        canvas, nothing typed and nothing wired, must still behave. An agent
        with no rules is the exact state that let a tool-holding agent answer
        a database question out of parametric memory. So the bottom layer is
        now never empty, and "nothing configured" means "inherit this node
        type's own minimum" rather than "defer to the library".

        The `None` path still exists for a tier that blanks `DEFAULT_RULES`,
        which the test below pins."""
        prompt = ReactAgentNode(name="a1", model=object()).resolve_prompt()
        assert prompt is not None
        assert "never state a figure you did not obtain" in prompt

    def test_a_tier_that_blanks_the_defaults_still_gets_no_prompt(self) -> None:
        """The escape hatch, so the `None` branch is not dead code: a harness
        that owns its own prompt entirely opts out by emptying the ClassVar."""

        class BareAgentNode(ReactAgentNode):
            DEFAULT_RULES = ""

        assert BareAgentNode(name="a1", model=object()).resolve_prompt() is None

    def test_context_rides_above_the_rules(self) -> None:
        node = ReactAgentNode(
            name="a1", model=object(), rules="Cite figures.", context="Skill text here."
        )
        prompt = node.resolve_prompt()
        assert prompt is not None
        assert prompt.index("Skill text here.") < prompt.index("Cite figures.")

    def test_resolve_middleware_carries_extras_from_config(self) -> None:
        extra = FakeMiddleware("x")
        node = ReactAgentNode(name="a1", model=object(), middleware={"mine": extra})
        assert extra in node.resolve_middleware().flatten()


class TestConcreteTiers:
    def test_react_builds_through_its_recorded_constructor(self, monkeypatch) -> None:
        recorder = Recorder()
        node = ReactAgentNode(name="a1", model="MODEL", tools=["t1"], rules="Be terse.")
        monkeypatch.setattr(node, "_constructor", recorder)
        node.build()
        (call,) = recorder.calls
        assert call["model"] == "MODEL"
        assert call["tools"] == ["t1"]
        assert "Be terse." in call["system_prompt"]
        assert call["name"] == "a1"

    def test_react_omits_system_prompt_only_when_there_are_no_rules_at_all(
        self, monkeypatch
    ) -> None:
        """A stock agent now always passes a `system_prompt`, because
        `DEFAULT_RULES` is a layer it inherits (ticket 10). The omission
        survives for a tier that blanks that layer — which is what this pins,
        so the "no key at all" path does not rot."""

        class BareAgentNode(ReactAgentNode):
            DEFAULT_RULES = ""

        recorder = Recorder()
        node = ReactAgentNode(name="a1", model="MODEL")
        monkeypatch.setattr(node, "_constructor", recorder)
        node.build()
        assert "system_prompt" in recorder.calls[0]

        bare_recorder = Recorder()
        bare = BareAgentNode(name="a2", model="MODEL")
        monkeypatch.setattr(bare, "_constructor", bare_recorder)
        bare.build()
        assert "system_prompt" not in bare_recorder.calls[0]

    def test_deep_passes_subagents_through(self, monkeypatch) -> None:
        recorder = Recorder()
        subagents = [{"name": "critic", "description": "reviews", "system_prompt": "…"}]
        node = DeepAgentNode(name="d1", model="MODEL", subagents=subagents)
        monkeypatch.setattr(node, "_constructor", recorder)
        node.build()
        assert recorder.calls[0]["subagents"] == subagents

    def test_middleware_flattens_into_the_constructor_call(self, monkeypatch) -> None:
        recorder = Recorder()
        mine = FakeMiddleware("mine")
        node = ReactAgentNode(name="a1", model="M", middleware={"mine": mine})
        monkeypatch.setattr(node, "_constructor", recorder)
        node.build()
        assert recorder.calls[0]["middleware"] == [mine]

    def test_custom_graph_returns_the_users_runnable_untouched(self) -> None:
        runnable = SimpleNamespace(kind="user-graph")
        node = CustomGraphNode(name="c1", runnable=runnable)
        assert node.build() is runnable

    def test_custom_graph_refuses_a_missing_runnable_loudly(self) -> None:
        with pytest.raises(ValueError):
            CustomGraphNode(name="c1", runnable=None).build()


class TestTierSelection:
    """The one place a canvas `tier` string becomes a class."""

    def test_known_tiers(self) -> None:
        assert agent_node_for_tier("react") is ReactAgentNode
        assert agent_node_for_tier("deep") is DeepAgentNode

    def test_default_and_unknown_fall_back_to_react(self) -> None:
        assert agent_node_for_tier("") is ReactAgentNode
        assert agent_node_for_tier("nonsense") is ReactAgentNode

    def test_custom_is_not_reachable_by_tier_string(self) -> None:
        """A custom graph needs a runnable, which no tier string can supply;
        falling back beats crashing deep in a compile."""
        assert agent_node_for_tier("custom") is ReactAgentNode


class TestRealConstructorSmoke:
    """One test that goes through the real create_agent, no fakes, no model
    call — proving the family's kwargs match the installed library."""

    def test_react_compiles_with_the_real_create_agent(self) -> None:
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

        model = GenericFakeChatModel(messages=iter([]))
        node = ReactAgentNode(name="smoke", model=model, rules="Be brief.")
        compiled = node.build()
        assert hasattr(compiled, "invoke")
