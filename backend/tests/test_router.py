"""Tests for the router ladder.

The property under test is **polymorphism doing real work**: a developer supplies
branches and a sentence of rules, and inherits a working router. If any of these
require a new class, the ladder has failed at its job.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from openstategraph.abc.router import BaseRouter, Classification, IRouter, Router

BRANCHES = ["dataquery", "info", "help", "greeting", "off_topic"]


class FakeModel:
    """Returns a scripted answer and records the system prompt it was given."""

    def __init__(self, answer: str):
        self.answer = answer
        self.system_prompts: list[str] = []

    def invoke(self, messages):  # noqa: ANN001
        self.system_prompts.append(messages[0].content)
        return AIMessage(content=self.answer)


def make(answer: str = "dataquery", **kwargs) -> Router:
    return Router(BRANCHES, fallback="off_topic", model=FakeModel(answer), **kwargs)


class TestPromptComposition:
    """The base owns the contract; the developer owns only the rules."""

    def test_the_developer_supplies_rules_not_machinery(self) -> None:
        router = make(rules="If it mentions revenue or tables, it is a dataquery.")
        prompt = router.resolve_system_prompt()

        assert "If it mentions revenue or tables" in prompt
        # None of this was written by the developer.
        assert BaseRouter.PROMPT.preamble in prompt
        assert BaseRouter.PROMPT.output_contract in prompt
        for branch in BRANCHES:
            assert branch in prompt

    def test_the_output_contract_cannot_be_deleted(self) -> None:
        # The whole reason the contract is not an editable field: a router whose
        # answer cannot be parsed is broken, and that must not be reachable by
        # clearing a textarea.
        assert BaseRouter.PROMPT.output_contract in make(rules="").resolve_system_prompt()

    def test_the_output_contract_comes_after_the_developer_rules(self) -> None:
        prompt = make(rules="Explain your reasoning at length.").resolve_system_prompt()
        # Later instructions win ties, so the contract must be last or a rule
        # like the one above would make every classification unparseable.
        assert prompt.index("Explain your reasoning") < prompt.index(
            BaseRouter.PROMPT.output_contract
        )

    def test_the_fallback_is_named_in_the_prompt(self) -> None:
        # The model should know which branch means "none of these".
        prompt = make().resolve_system_prompt()
        assert "nothing else matches" in prompt

    def test_the_prompt_reaches_the_model(self) -> None:
        router = make(rules="Custom rule here.")
        router.classify("how much revenue?")
        assert "Custom rule here." in router.model.system_prompts[0]  # type: ignore[union-attr]


class TestNoNewClassNeeded:
    """A different router is configuration, not code."""

    def test_two_routers_with_different_rules_are_the_same_class(self) -> None:
        support = make(rules="Billing questions go to help.")
        analytics = make(rules="Anything with a metric goes to dataquery.")
        assert type(support) is type(analytics) is Router
        assert support.resolve_system_prompt() != analytics.resolve_system_prompt()

    def test_a_subclass_need_only_supply_the_rules(self) -> None:
        """There was a `describe_rules()` override point until
        install-experience 19 — `return self.rules.strip()`, one line under the
        attribute it read, and this test was the only thing that ever overrode
        it. Written through the constructor instead, it makes the ladder's own
        claim better: a new kind of router is configuration."""

        class SupportRouter(Router):
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__(
                    *args,
                    rules="Refunds and invoices are help. Everything else is off_topic.",
                    **kwargs,
                )

        router = SupportRouter(BRANCHES, fallback="off_topic", model=FakeModel("help"))
        # Inherited the contract, the branch listing and the classification loop.
        assert BaseRouter.PROMPT.output_contract in router.resolve_system_prompt()
        assert "Refunds and invoices" in router.resolve_system_prompt()
        assert router.classify("where is my refund?").branch == "help"

    def test_the_concrete_router_satisfies_the_interface(self) -> None:
        assert isinstance(make(), IRouter)

    def test_the_base_cannot_be_instantiated(self) -> None:
        # compile_path_map is abstract: only a concrete router knows what its
        # branches connect to.
        with pytest.raises(TypeError):
            BaseRouter(BRANCHES)  # type: ignore[abstract]


class TestNormalisation:
    """A router is the entry point, so a strict parse would be a total outage."""

    def test_an_exact_answer_is_taken(self) -> None:
        assert make("dataquery").classify("q").branch == "dataquery"

    @pytest.mark.parametrize("answer", ["  dataquery  ", '"dataquery"', "dataquery.", "DataQuery"])
    def test_it_tolerates_the_ways_models_actually_answer(self, answer: str) -> None:
        result = make(answer).classify("q")
        assert result.branch == "dataquery"
        assert result.fell_back is False

    def test_it_finds_the_branch_inside_a_chatty_answer(self) -> None:
        # Discarding a decision the model actually made would be wasteful.
        result = make("I think this is a dataquery").classify("q")
        assert result.branch == "dataquery"

    def test_an_ambiguous_answer_falls_back_rather_than_guessing(self) -> None:
        result = make("either help or info").classify("q")
        assert result.branch == "off_topic"
        assert result.fell_back is True
        assert "Ambiguous" in result.reason

    @pytest.mark.parametrize("answer", ["", "   ", "banana"])
    def test_an_unusable_answer_falls_back_with_a_reason(self, answer: str) -> None:
        result = make(answer).classify("q")
        assert result.branch == "off_topic"
        assert result.fell_back is True
        assert result.reason

    def test_no_model_falls_back_instead_of_raising(self) -> None:
        router = Router(BRANCHES, fallback="off_topic")
        assert router.classify("q") == Classification(
            branch="off_topic", fell_back=True, reason="No model configured"
        )


class TestConfiguration:
    def test_an_invalid_fallback_is_replaced_rather_than_raising(self) -> None:
        # A router with an unusable fallback is worse than one with an arbitrary
        # but valid fallback.
        assert Router(BRANCHES, fallback="nonsense").fallback in BRANCHES

    def test_no_branches_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one branch"):
            Router([])


class TestCompilePathMap:
    def test_it_maps_branches_to_the_nodes_they_are_wired_to(self) -> None:
        router = Router(BRANCHES, destinations={"dataquery": "orchestrator", "help": "help_node"})
        assert router.compile_path_map() == {
            "dataquery": "orchestrator",
            "help": "help_node",
        }

    def test_an_unwired_branch_is_omitted_not_pointed_at_end(self) -> None:
        # Omitted, so a half-wired router shows up as a missing destination
        # rather than silently terminating the run.
        router = Router(BRANCHES, destinations={"dataquery": "orchestrator"})
        assert "help" not in router.compile_path_map()
