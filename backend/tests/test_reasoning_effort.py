"""Reasoning effort, and the two ways it degrades.

The happy path is one line. Everything worth testing is what happens when the
chosen model cannot reason, and the point of these tests is that the *evidence*
lives here rather than in a comment: `ChatOllama` really has no
`reasoning_effort` field, `gpt-4.1-mini` really reports `reasoning_output:
False`, `claude-haiku-4-5` really reasons while publishing no tiers. Each is
asserted against the installed partner package, so a package update that
changes any of them fails here instead of quietly changing behaviour.
"""

from __future__ import annotations

import inspect

import pytest

from openstategraph.compile.node_catalogue import load_catalogue
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.reasoning import (
    REASONING_EFFORT_KEY,
    apply_reasoning_effort,
    effort_support,
)


class _NotAModel:
    """Something with no pydantic fields and no profile at all."""


class TestCapabilityIsDiscovered:
    """Both sources are read from the installed packages, never listed here."""

    def test_the_integrations_own_annotation_supplies_the_levels(self) -> None:
        anthropic = pytest.importorskip("langchain_anthropic")
        model = anthropic.ChatAnthropic(model="claude-sonnet-4-6", api_key="placeholder")
        support = effort_support(model)
        assert support.carries
        # Read off `ChatAnthropic.model_fields["reasoning_effort"].annotation`,
        # which is where the provider states it — not from a list in our source.
        assert "high" in (support.parameter_levels or ())
        assert "low" in (support.parameter_levels or ())

    def test_the_model_profile_supplies_the_per_model_tiers(self) -> None:
        anthropic = pytest.importorskip("langchain_anthropic")
        model = anthropic.ChatAnthropic(model="claude-sonnet-4-6", api_key="placeholder")
        support = effort_support(model)
        assert support.model_levels is not None
        assert "high" in support.model_levels
        assert support.reasons is True

    def test_a_reasoning_model_with_no_published_tiers_is_unknown_not_refused(
        self,
    ) -> None:
        """`claude-haiku-4-5` reasons but publishes no `reasoning_effort_levels`.

        Treating a silent profile as "unsupported" would refuse a setting the
        provider would have accepted, so the fallback is the integration's own
        annotation — a fact, not a guess.
        """
        anthropic = pytest.importorskip("langchain_anthropic")
        model = anthropic.ChatAnthropic(model="claude-haiku-4-5", api_key="placeholder")
        support = effort_support(model)
        assert support.model_levels is None
        assert not support.refuses
        assert "high" in support.accepted

    def test_a_probe_on_something_that_is_not_a_chat_model_does_not_raise(self) -> None:
        support = effort_support(_NotAModel())
        assert not support.carries
        assert support.accepted == ()


class TestItDoesNotBreak:
    def test_an_integration_without_the_parameter_warns_instead_of_dropping(
        self,
    ) -> None:
        """The Ollama case — and Ollama is this project's default provider.

        `ChatOllama` accepts `reasoning_effort=` without complaint and then does
        not carry it: no error, no warning, and the value is absent from
        `model_dump()`. That is the "silently looks like it worked" failure, and
        it is the reason this module exists rather than a pass-through.
        """
        ollama = pytest.importorskip("langchain_ollama")
        raw = ollama.ChatOllama(model="gpt-oss:120b-cloud", reasoning_effort="high")
        assert "reasoning_effort" not in raw.model_dump(), (
            "langchain-ollama has gained a reasoning_effort parameter — the "
            "capability probe will now find it, but this test's premise is stale."
        )

        model, warning = apply_reasoning_effort(raw, "high")
        assert model is raw
        assert warning is not None
        assert "gpt-oss:120b-cloud" in warning
        assert "high" in warning

    def test_a_model_that_reports_no_reasoning_is_not_sent_the_parameter(self) -> None:
        """The OpenAI case — where passing it through would raise at call time.

        `ChatOpenAI(model="gpt-4.1-mini", reasoning_effort="high")` *constructs*
        without complaint; the request is what fails. Refusing at build time
        turns a dead run into a warning.
        """
        openai = pytest.importorskip("langchain_openai")
        model = openai.ChatOpenAI(model="gpt-4.1-mini", api_key="placeholder")
        assert effort_support(model).refuses is True

        resolved, warning = apply_reasoning_effort(model, "high")
        assert resolved is model
        assert warning is not None
        assert "no reasoning support" in warning

    def test_a_level_the_provider_does_not_accept_is_refused_not_raised(self) -> None:
        """`minimal` is a real OpenAI/Gemini tier and a pydantic error on Anthropic."""
        anthropic = pytest.importorskip("langchain_anthropic")
        model = anthropic.ChatAnthropic(model="claude-sonnet-4-6", api_key="placeholder")
        resolved, warning = apply_reasoning_effort(model, "minimal")
        assert resolved is model
        assert warning is not None and "accepts" in warning

    def test_a_supported_level_actually_reaches_the_model(self) -> None:
        anthropic = pytest.importorskip("langchain_anthropic")
        model = anthropic.ChatAnthropic(model="claude-sonnet-4-6", api_key="placeholder")
        resolved, warning = apply_reasoning_effort(model, "high")
        assert warning is None
        assert resolved is not model
        assert resolved.reasoning_effort == "high"

    def test_nothing_is_sent_when_nothing_is_asked_for(self) -> None:
        """Empty is "the model's own default", which is not a level to send."""
        anthropic = pytest.importorskip("langchain_anthropic")
        model = anthropic.ChatAnthropic(model="claude-sonnet-4-6", api_key="placeholder")
        for blank in ("", "   ", None):
            resolved, warning = apply_reasoning_effort(model, blank)  # type: ignore[arg-type]
            assert resolved is model
            assert warning is None


class TestBothSidesAgreeOnWhoGetsTheControl:
    """The `drives_model` guard, applied to the setting that qualifies it.

    Reasoning effort is offered on exactly the node types that drive a model,
    and that is asserted rather than trusted — the editor derives it from the
    presence of the model field (`withReasoningEffort`) and the compiler reads
    it in `_resolve_model`, so the two can only disagree if one of them stops
    doing what it says. A picker on a node the compiler never asks, or a node
    the compiler asks with no picker, is the same silent defect
    `test_model_field_contract.py` exists for.
    """

    def test_every_model_driven_node_type_offers_the_control(self) -> None:
        catalogue = load_catalogue()
        offering = {
            node_type
            for node_type, keys in catalogue.field_keys.items()
            if REASONING_EFFORT_KEY in keys
        }
        assert offering == set(catalogue.model_driven), (
            "reasoning effort and the model picker must appear on the same node "
            f"types; offered by {sorted(offering)}, model-driven "
            f"{sorted(catalogue.model_driven)}. Run `npm run generate:ports`."
        )

    def test_the_set_is_not_accidentally_empty(self) -> None:
        assert len(load_catalogue().model_driven) >= 5


class TestTheRuntimeReportsIt:
    def test_a_dropped_effort_lands_on_the_run_warnings(self) -> None:
        from openstategraph.api.registries import runtime_warnings

        ollama = pytest.importorskip("langchain_ollama")
        runtime = NodeRuntime(model=ollama.ChatOllama(model="gpt-oss:120b-cloud"))
        runtime._resolve_model({REASONING_EFFORT_KEY: "high"})

        reported = runtime_warnings(runtime)
        assert any("Reasoning effort" in line for line in reported), reported

    def test_the_same_fact_is_reported_once(self) -> None:
        ollama = pytest.importorskip("langchain_ollama")
        runtime = NodeRuntime(model=ollama.ChatOllama(model="gpt-oss:120b-cloud"))
        for _ in range(4):
            runtime._resolve_model({REASONING_EFFORT_KEY: "high"})
        assert len(runtime.capability_warnings) == 1

    def test_every_model_driven_node_gets_it_because_one_method_applies_it(self) -> None:
        """No node type opts in, and none can forget.

        Effort rides `_resolve_model`, which is the one place a model becomes a
        model — the same reason `modelField.ts` exists rather than six copies of
        a picker. This asserts the wiring is in that method rather than sprinkled
        through the factories.
        """
        source = inspect.getsource(NodeRuntime._resolve_model)
        assert "_apply_effort" in source
        assert "REASONING_EFFORT_KEY" in source

    def test_no_factory_resolves_effort_on_its_own(self) -> None:
        """The corollary: six copies of this would be the defect, not the fix."""
        runtime = NodeRuntime(model=None)
        for node_type, builder in runtime._builders.items():
            source = inspect.getsource(builder)
            assert "apply_reasoning_effort" not in source, (
                f"{node_type} applies reasoning effort itself — it belongs on "
                "_resolve_model, once, for every family that drives a model."
            )
