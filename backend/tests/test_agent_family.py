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
from openstategraph.abc.prompt import SystemPrompt


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

    def test_merging_a_table_preserves_the_source_order_it_promises(self) -> None:
        """`merge` read the source's private `_slots` — *set* order, not the
        source's own `flatten()` order (ticket 46, item 4).

        Harmless while every live caller merges a plain dict, and wrong the
        moment one does not: ordering the contributions is the single
        guarantee this class exists to give, and a table-to-table merge was
        the one path that did not honour the source's own answer.
        """
        source = MiddlewareSlotTable(order=("core",))
        extra_first, core, extra_second = (FakeMiddleware(t) for t in ("x", "core", "y"))
        # An extra set *before* the canonical slot: dict order and flatten
        # order disagree from here on, which is what makes this observable.
        source.set("x-extra", extra_first)
        source.set("core", core)
        source.set("y-extra", extra_second)
        assert source.flatten() == [core, extra_first, extra_second]

        # A target that does *not* share the source's canonical order, which is
        # where the difference shows: with the same order, the target's own
        # canonical/extra split happens to re-sort the damage away.
        target = MiddlewareSlotTable(order=())
        target.merge(source)

        assert target.flatten() == source.flatten()
        assert target.names() == source.names()

    def test_a_slot_can_be_read_without_reaching_inside(self) -> None:
        """The accessor `merge` uses. Without one, "iterate names()" has
        nothing to read the value through and the private reach returns."""
        table = MiddlewareSlotTable(order=("core",))
        core = FakeMiddleware("core")
        table.set("core", core)

        assert table.get("core") is core
        assert table.get("never-filled") is None

    def test_rubric_is_a_declared_slot_not_an_unknown_one(self) -> None:
        """`node_runtime` contributes `"rubric"`, and the base had never heard
        of it (ticket 46, item 3), so it flattened through the unknown-slot
        bucket — a position chosen by "nobody declared this" rather than by an
        argument. That bucket is for a third party's slot; a first-party
        contribution belongs in the declared order, where it can also be
        replaced by name.
        """
        from openstategraph.abc.agent import AbstractAgentNode

        assert "rubric" in AbstractAgentNode.SLOT_ORDER

    def test_rubric_grades_the_agents_own_output_before_any_post_processing(self) -> None:
        """Last in the order, and the position is the argument.

        `RubricMiddleware` implements `before_agent` and `after_agent` (checked
        against the installed package; the docs describe it as grading once the
        agent has finished reasoning and looping it back on `needs_revision`).
        `after_*` hooks run **last to first**, so last in the list means its
        verdict is taken *first* — on what the agent itself produced, before
        any later after_agent middleware reshapes it. That is the right
        subject: the loop can only ask the agent to revise its own work, and a
        complaint about someone else's post-processing is one it cannot act on.
        """
        from openstategraph.abc.agent import AbstractAgentNode

        assert AbstractAgentNode.SLOT_ORDER[-1] == "rubric"

    def test_a_declared_slot_outranks_a_plugins_unknown_one(self) -> None:
        """What moving it out of the bucket actually buys — the observable
        difference, since with rubric alone the flattened list is unchanged."""
        table = MiddlewareSlotTable(order=("core", "rubric"))
        plugin, rubric = FakeMiddleware("plugin"), FakeMiddleware("rubric")
        table.set("rubric", rubric)
        table.set("some-plugin", plugin)

        assert table.flatten() == [rubric, plugin]

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

        The `None` path still exists for a tier that blanks the default rules
        layer, which the test below pins."""
        prompt = ReactAgentNode(name="a1", model=object()).resolve_prompt()
        assert prompt is not None
        assert "never state a figure you did not obtain" in prompt

    def test_a_tier_that_blanks_the_defaults_still_gets_no_prompt(self) -> None:
        """The escape hatch, so the `None` branch is not dead code: a harness
        that owns its own prompt entirely opts out by declaring a fresh
        `PROMPT` with no defaults layer **and** no output contract.

        `with_defaults("")` alone no longer suffices (`launch-readiness` 27):
        `BaseAgentNode.PROMPT.output_contract` is now a locked,
        always-present anti-narration clause, so a tier must blank that too
        to get a genuinely empty prompt."""

        class BareAgentNode(ReactAgentNode):
            PROMPT = ReactAgentNode.PROMPT.with_defaults("")
            PROMPT = SystemPrompt(preamble=PROMPT.preamble, output_contract="")

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
        """A stock agent now always passes a `system_prompt`, because the
        default rules are a layer it inherits (ticket 10). The omission
        survives for a tier that blanks that layer — which is what this pins,
        so the "no key at all" path does not rot."""

        class BareAgentNode(ReactAgentNode):
            PROMPT = ReactAgentNode.PROMPT.with_defaults("")
            PROMPT = SystemPrompt(preamble=PROMPT.preamble, output_contract="")

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

    def test_custom_graph_has_no_prompt_machinery_at_all(self) -> None:
        """Ticket 45 — the class docstring's claim, made true of the code.

        `CustomGraphNode` said "prompt machinery must never be forced onto
        this class (CLAUDE.md's argument against `AbstractPromptedNode`)" while
        inheriting `PROMPT`, `self.prompt` and `resolve_prompt()` from
        `AbstractAgentNode`. The developer already built the graph; its harness
        owns its own prompt, and a `resolve_prompt()` on it is a seam that
        resolves nothing and an honesty layer nothing applies.

        So the machinery lives on `BaseAgentNode`, where `ReactAgentNode` and
        `DeepAgentNode` both are, and the tier that has no prompt has none.
        """
        node = CustomGraphNode(name="c1", runnable=object())
        assert not hasattr(node, "PROMPT")
        assert not hasattr(node, "prompt")
        assert not hasattr(node, "resolve_prompt")

    def test_the_prompted_tiers_still_have_it(self) -> None:
        # The move must not cost the two tiers that do compose a prompt.
        for cls in (ReactAgentNode, DeepAgentNode):
            node = cls(name="a1", model=object())
            assert hasattr(node, "PROMPT"), cls.__name__
            assert node.resolve_prompt(), cls.__name__


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
