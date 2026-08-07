"""The branch identity contract: a branch has a stable id *and* a human name.

Ticket 20 gave the editor's Router branches stable ids so that renaming a
branch no longer drops its edge — the canvas stores ``[{id, name}]`` and names
each output port ``branch:<id>``. The compiler recovers the label by stripping
that prefix, so **the label a conditional edge dispatches on is the id**.

The model, meanwhile, can only classify by *name*: ``b1-data`` is opaque and
``data_query`` is not. So exactly one place has to hold the mapping, and it is
the router — which is the only object that knows the branch table.

These tests pin both halves and the v1 compatibility path, because the gap
between them was live and silent: Python parsed ``branches`` as a newline
string, got nothing from a list, fell back to a single ``"default"`` branch,
and every question routed to whichever destination happened to be first.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dyflow.abc.router import Branch, Classification, Router
from dyflow.compile.node_runtime import NodeRuntime, RunState
from dyflow.compile.workflow_compiler import CompiledPlan


class ScriptedModel:
    """Answers with whatever it was told to, once per call."""

    def __init__(self, *answers: str) -> None:
        self._answers = list(answers)
        self.prompts: list[str] = []

    def invoke(self, messages, **_kwargs):
        self.prompts.append(str(messages[0].content))
        return SimpleNamespace(content=self._answers.pop(0))


class TestBranchNormalisation:
    def test_a_bare_string_is_a_branch_whose_id_is_its_name(self) -> None:
        branch = Branch.of("greeting")
        assert branch.id == "greeting"
        assert branch.name == "greeting"

    def test_a_mapping_carries_a_distinct_id_and_name(self) -> None:
        branch = Branch.of({"id": "b1-data", "name": "data_query"})
        assert branch.id == "b1-data"
        assert branch.name == "data_query"

    def test_a_mapping_with_only_a_name_reuses_it_as_the_id(self) -> None:
        assert Branch.of({"name": "greeting"}).id == "greeting"

    def test_a_mapping_with_only_an_id_reuses_it_as_the_name(self) -> None:
        assert Branch.of({"id": "b1"}).name == "b1"

    def test_an_empty_branch_is_refused_rather_than_silently_dropped(self) -> None:
        with pytest.raises(ValueError):
            Branch.of({"id": "", "name": ""})


class TestRouterHoldsTheMapping:
    def test_branches_still_reads_as_the_list_of_names(self) -> None:
        """`IRouter.branches` is `list[str]`, and the prompt shows names."""
        router = Router([{"id": "b1-data", "name": "data_query"}, "greeting"])
        assert router.branches == ["data_query", "greeting"]

    def test_route_key_maps_a_name_to_its_stable_id(self) -> None:
        router = Router([{"id": "b1-data", "name": "data_query"}])
        assert router.route_key("data_query") == "b1-data"

    def test_route_key_is_identity_when_no_id_was_supplied(self) -> None:
        router = Router(["greeting"])
        assert router.route_key("greeting") == "greeting"

    def test_route_key_passes_an_unknown_name_through_untouched(self) -> None:
        """A misroute is recoverable; raising inside the entry point is not."""
        router = Router([{"id": "b1", "name": "data_query"}])
        assert router.route_key("nonsense") == "nonsense"

    def test_the_prompt_never_shows_an_id(self) -> None:
        """An opaque id in the prompt is noise the model would try to emit."""
        prompt = Router([{"id": "b1-data", "name": "data_query"}]).resolve_system_prompt()
        assert "data_query" in prompt
        assert "b1-data" not in prompt

    def test_fallback_may_be_given_as_an_id_and_resolves_to_its_name(self) -> None:
        router = Router(
            [{"id": "b1", "name": "data_query"}, {"id": "b2", "name": "greeting"}],
            fallback="b2",
        )
        assert router.fallback == "greeting"
        assert router.route_key(router.fallback) == "b2"

    def test_fallback_may_still_be_given_as_a_name(self) -> None:
        router = Router(
            [{"id": "b1", "name": "data_query"}, {"id": "b2", "name": "greeting"}],
            fallback="greeting",
        )
        assert router.fallback == "greeting"

    def test_classify_returns_the_name_and_route_key_turns_it_into_the_id(self) -> None:
        router = Router(
            [{"id": "b1-data", "name": "data_query"}, {"id": "b4-greeting", "name": "greeting"}],
            model=ScriptedModel("greeting"),
        )
        decision = router.classify("hello there")
        assert decision.branch == "greeting"
        assert router.route_key(decision.branch) == "b4-greeting"


class TestRouterNodeFactory:
    """The canvas document → `state["decisions"]` path, which is what the
    compiler's conditional edge actually reads."""

    @staticmethod
    def _decide(branches, answer: str, **data) -> str:
        runtime = NodeRuntime(model=ScriptedModel(answer))
        node = {"id": "router1", "type": "route.classifier", "data": {"branches": branches, **data}}
        plan = CompiledPlan()
        run = runtime._router("router1", node, plan)
        update = run(RunState(question="anything"))  # type: ignore[typeddict-item]
        return update["decisions"]["router1"]

    def test_v2_array_branches_decide_by_id(self) -> None:
        """The id is what `branch:<id>` port labels dispatch on."""
        decided = self._decide(
            [{"id": "b1-data", "name": "data_query"}, {"id": "b4-greeting", "name": "greeting"}],
            answer="greeting",
        )
        assert decided == "b4-greeting"

    def test_v1_newline_branches_still_work(self) -> None:
        """Files saved before ticket 20 must keep routing."""
        decided = self._decide("dataquery\ngreeting", answer="greeting")
        assert decided == "greeting"

    def test_every_branch_is_reachable_not_just_the_first(self) -> None:
        """The exact symptom of the bug: one destination absorbed everything."""
        branches = [
            {"id": "b1-data", "name": "data_query"},
            {"id": "b2-analysis", "name": "analysis"},
            {"id": "b3-general", "name": "general"},
            {"id": "b4-greeting", "name": "greeting"},
        ]
        decided = [self._decide(branches, answer=name) for name in
                   ("data_query", "analysis", "general", "greeting")]
        assert decided == ["b1-data", "b2-analysis", "b3-general", "b4-greeting"]

    def test_an_unusable_answer_falls_back_to_the_declared_branch_id(self) -> None:
        decided = self._decide(
            [{"id": "b1-data", "name": "data_query"}, {"id": "b3-general", "name": "general"}],
            answer="I have no idea",
            fallback="general",
        )
        assert decided == "b3-general"

    def test_a_router_with_no_branches_at_all_still_produces_a_decision(self) -> None:
        assert self._decide([], answer="anything") == "default"


class TestClassificationShape:
    def test_classification_carries_the_name_the_model_chose(self) -> None:
        assert Classification(branch="greeting").branch == "greeting"
