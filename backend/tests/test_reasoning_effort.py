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
from typing import Any

import pytest

from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_catalogue import load_catalogue
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.reasoning import (
    REASONING_EFFORT_KEY,
    apply_reasoning_effort,
    effort_support,
    enumerates_effort_levels,
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

    def test_a_reasoning_model_with_no_published_tiers_still_reasons(self) -> None:
        """`claude-haiku-4-5` reasons — via `thinking` — and publishes no tiers.

        The two facts are independent, and conflating them is what broke:
        `reasoning_output: True` says the model thinks, not that it accepts the
        `effort` parameter. Anthropic's thinking models reach it through
        `thinking={"type": "enabled", "budget_tokens": N}`, which this module
        does not send — see `TestAProviderThatEnumeratesWhichModelsTakeIt`.
        """
        anthropic = pytest.importorskip("langchain_anthropic")
        model = anthropic.ChatAnthropic(model="claude-haiku-4-5", api_key="placeholder")
        support = effort_support(model)
        assert support.model_levels is None
        assert not support.refuses
        assert support.reasons is True

    def test_a_probe_on_something_that_is_not_a_chat_model_does_not_raise(self) -> None:
        support = effort_support(_NotAModel())
        assert not support.carries
        assert support.accepted == ()


class TestAProviderThatEnumeratesWhichModelsTakeIt:
    """The fourth state: a silence that *is* a no, because the field is filled in.

    Reproduced live on 2026-08-16 against `langchain-anthropic` 1.5.4: an
    `agent.llm` node on `anthropic/claude-haiku-4-5` with `reasoningEffort:
    "high"` streamed an `error` terminal frame rather than a warning —

        BadRequestError: 400 - This model does not support the effort parameter.

    Which is exactly what this module exists to prevent. The parameter is real
    on the *integration* (`ChatAnthropic.reasoning_effort` is annotated, and
    maps to `output_config.effort`) and rejected by the *API* per model, so the
    annotation answered a question nobody asked.

    The discriminator was already in the profile and was being read past. This
    package's own dataset publishes `reasoning_effort_levels` for eight of its
    fifteen models. So the key's absence means different things per integration,
    and the fact that separates them is discoverable: **does this integration
    fill the field in for anybody?** Where it does, a model left out is read as
    a no. Where it never does, the field is unpopulated and says nothing, and
    the annotation still answers.

    On 2026-08-22 `langchain-openai` crossed from the second case to the first,
    and the confirmation this class's tripwire demanded found the dataset
    **incomplete** — see
    `test_the_datasets_the_gate_reads_are_the_ones_it_was_reasoned_about`. The
    rule is unchanged; what changed is that it is now known to over-refuse, is
    said so in the warning, and is measured here.

    No model ids and no provider names in `reasoning.py`, per CLAUDE.md. The
    ids below are in the *test*, where a package update that moves them is
    supposed to fail.
    """

    @staticmethod
    def _anthropic(model_id: str) -> Any:
        anthropic = pytest.importorskip("langchain_anthropic")
        return anthropic.ChatAnthropic(model=model_id, api_key="placeholder")

    @pytest.mark.parametrize("model_id", ["claude-haiku-4-5", "claude-sonnet-4-5"])
    def test_the_model_that_400s_is_refused_rather_than_sent(self, model_id: str) -> None:
        """Both models from the live reproduction, at the level that killed it."""
        model = self._anthropic(model_id)
        assert effort_support(model).accepted == ()

        resolved, warning = apply_reasoning_effort(model, "high")
        assert resolved is model
        assert warning is not None
        assert model_id in warning
        assert "no reasoning-effort tiers" in warning

    def test_a_model_that_publishes_tiers_still_receives_it(self) -> None:
        """The other half: refusing everything would be a different bug."""
        model = self._anthropic("claude-sonnet-4-6")
        resolved, warning = apply_reasoning_effort(model, "high")
        assert warning is None
        assert resolved.reasoning_effort == "high"

    def test_a_model_the_dataset_has_never_heard_of_is_refused(self) -> None:
        """An unlisted id degrades to a warning, and that direction is chosen.

        A model released tomorrow may well accept `effort`, and refusing it is a
        false negative — but a false negative here costs a sentence in the run
        warnings, and a false positive costs the run. The module's whole premise
        is that those two are not symmetric.
        """
        resolved, warning = apply_reasoning_effort(self._anthropic("claude-not-yet"), "high")
        assert resolved is not None and warning is not None

    def test_the_openai_model_that_takes_it_receives_it_either_way(self) -> None:
        """`gpt-5` gets the parameter under both readings of the dataset.

        Under `langchain-openai` 1.1.6 it publishes no tiers, the integration
        enumerates for nobody, and the annotation answers. Under 1.6.0 it
        publishes `none/low/medium/high/xhigh` and is sent the value because it
        is on its own list. Two different code paths, one correct outcome, and
        this is the half that would break if the fix to the other half were a
        blanket refusal.
        """
        openai = pytest.importorskip("langchain_openai")
        model = openai.ChatOpenAI(model="gpt-5", api_key="placeholder")
        resolved, warning = apply_reasoning_effort(model, "high")
        assert warning is None
        assert resolved.reasoning_effort == "high"

    def test_an_enumerating_integration_gates_and_a_silent_one_does_not(self) -> None:
        """The rule itself, asserted against whatever is installed.

        Version-independent on purpose. `langchain-openai` 1.1.6 publishes
        tiers for nobody and 1.6.0 publishes them for twenty-seven models, and
        this repository has both in front of it — a local checkout and a CI
        runner that resolves `langchain-openai>=1.0,<2` to the newest release.
        A test that pins one of those two states is the drift
        `test_deep_agent_slot_facts.py` hit on the same push.

        So the invariant is asserted rather than the reading: for every
        integration, a model with no published tiers is sent the parameter if
        and only if that integration enumerates for nobody.
        """
        for module_name, model_id in (
            ("langchain_anthropic", "claude-haiku-4-5"),
            ("langchain_openai", "o3"),
        ):
            module = pytest.importorskip(module_name)
            factory = getattr(module, "ChatAnthropic", None) or module.ChatOpenAI
            model = factory(model=model_id, api_key="placeholder")
            support = effort_support(model)
            assert support.model_levels is None, (
                f"{model_id} has gained published tiers — this case is no "
                "longer the silent one it was chosen to exercise."
            )
            _, warning = apply_reasoning_effort(model, "high")
            gated = enumerates_effort_levels(model)
            assert (warning is not None) is gated, (
                f"{model_id}: integration enumerates={gated}, "
                f"warning={warning!r} — the gate and the dataset disagree."
            )

    def test_the_datasets_the_gate_reads_are_the_ones_it_was_reasoned_about(
        self,
    ) -> None:
        """The replacement tripwire, and what it fires on.

        The one it replaces asserted `langchain-openai` publishes tiers for
        nobody. On 2026-08-22 that stopped being true — 1.6.0 publishes them
        for twenty-seven models — and the confirmation the message asked for
        was done: **the dataset is not complete.** Every one of the twenty-seven
        is a `gpt-5*` entry hand-written into
        `langchain_openai/data/profile_augmentations.toml`; `o1`, `o3`,
        `o3-mini`, `o3-pro`, `o1-pro` and `o4-mini` report
        `reasoning_output: True`, have no override table at all, and are
        documented by OpenAI to accept the effort parameter. They were not left
        out on purpose — they were never reached.

        So the premise the `excluded` inference rests on is **false for
        `langchain-openai`**, and it was only ever verified for
        `langchain-anthropic`, where a live 400 supplied the evidence. The rule
        is kept anyway, for the asymmetry the module is built on: over-refusing
        `o3` costs one sentence in the run warnings, and sending `effort` to
        `claude-haiku-4-5` costs the run. The cost of that choice is real and
        is filed as `providers-and-credentials/11` rather than absorbed here.

        Which makes this the assertion worth keeping: the two facts that would
        change the decision, either of which fires here first.

        - Anthropic stops enumerating → the gate goes blind and the 400 is back.
        - The OpenAI omissions gain tiers → the known false negative is gone
          and the rule can be narrowed.

        Both readings of `langchain-openai` this repository has measured —
        silent (1.1.6) and enumerating-but-partial (1.6.0) — are green, because
        both have been reasoned about. A third is not.
        """
        anthropic = pytest.importorskip("langchain_anthropic")
        openai = pytest.importorskip("langchain_openai")

        assert (
            enumerates_effort_levels(
                anthropic.ChatAnthropic(model="claude-haiku-4-5", api_key="placeholder")
            )
            is True
        ), (
            "langchain-anthropic no longer publishes reasoning_effort_levels for "
            "any model — the per-model gate has gone blind and the 400 is back."
        )

        omitted = {
            model_id: effort_support(
                openai.ChatOpenAI(model=model_id, api_key="placeholder")
            ).model_levels
            for model_id in ("o1", "o3", "o3-mini", "o3-pro", "o4-mini")
        }
        assert all(levels is None for levels in omitted.values()), (
            "langchain-openai now publishes reasoning_effort_levels for the "
            f"o-series ({omitted}). That is the measured incompleteness closing: "
            "re-check whether the `excluded` rule still over-refuses, and close "
            "providers-and-credentials/11 if it does not."
        )

    def test_the_refusal_says_it_is_an_inference_and_not_the_provider_speaking(
        self,
    ) -> None:
        """A warning may not overstate what the dataset actually established.

        Until 2026-08-22 this message said sending the value *"would fail the
        request"*. For `claude-haiku-4-5` that was measured — a live 400. For an
        omitted model in general it is a guess, and `o3` is the counter-example:
        omitted, refused, and documented to accept the parameter. A product that
        must not promise what is not possible must equally not report a
        certainty it does not have.
        """
        model = self._anthropic("claude-haiku-4-5")
        _, warning = apply_reasoning_effort(model, "high")
        assert warning is not None
        assert "inference" in warning
        assert "published tiers are incomplete" in warning
        assert "would fail the request" not in warning

    def test_a_probe_of_something_with_no_dataset_does_not_raise(self) -> None:
        """`langchain-ollama` ships no `data._profiles` at all."""
        assert enumerates_effort_levels(_NotAModel()) is False


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

    def test_a_node_on_an_excluded_model_reports_it_and_runs_without_it(self) -> None:
        """The caller's view of the refusal, at the layer that runs the node.

        `apply_reasoning_effort` being right is not the same as a node being
        right — the trap this repo has paid for twice. So both directions are
        driven through `_resolve_model`, which is the only place a model becomes
        a model, and asserted on what the node ends up holding.
        """
        from openstategraph.api.registries import runtime_warnings

        anthropic = pytest.importorskip("langchain_anthropic")
        runtime = NodeRuntime(
            model=anthropic.ChatAnthropic(model="claude-haiku-4-5", api_key="placeholder")
        )
        model = runtime._resolve_model({REASONING_EFFORT_KEY: "high"})

        assert model.reasoning_effort is None, (
            "an excluded model was handed the parameter that 400s it"
        )
        assert any("Reasoning effort" in line for line in runtime_warnings(runtime))

    def test_a_node_on_a_model_that_takes_it_is_handed_it(self) -> None:
        """And the other half, or the fix would be a blanket refusal."""
        from openstategraph.api.registries import runtime_warnings

        anthropic = pytest.importorskip("langchain_anthropic")
        runtime = NodeRuntime(
            model=anthropic.ChatAnthropic(model="claude-sonnet-4-6", api_key="placeholder")
        )
        model = runtime._resolve_model({REASONING_EFFORT_KEY: "high"})

        assert model.reasoning_effort == "high"
        assert not [line for line in runtime_warnings(runtime) if "Reasoning effort" in line]

    def test_the_same_fact_is_reported_once(self) -> None:
        ollama = pytest.importorskip("langchain_ollama")
        runtime = NodeRuntime(model=ollama.ChatOllama(model="gpt-oss:120b-cloud"))
        for _ in range(4):
            runtime._resolve_model({REASONING_EFFORT_KEY: "high"})
        assert len(runtime.diagnostics.subjects(Finding.CAPABILITY_FAILED)) == 1

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
