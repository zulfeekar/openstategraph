"""One registration point per node type — `export-and-eject/03`.

The ticket was filed against a premise that has since half-expired.
`NodeRuntime._builders` was a private dict literal *and* the only dispatch
there was, so a node type nobody had merged into it could not exist at all.
install-experience 08 fixed that half: `NodeFamilyRegistry` lets an installed
distribution contribute a family, and `test_node_families.py` proves its step
runs. What survived is the shape of the built-in half — a dict literal plus
two arms written into `builder_for` as `if`s, which is a dispatch policy no
test could enumerate and a duplicate key could collapse in silence.

So this file pins the *registry behaviour* CLAUDE.md asks of every registry —
"a duplicate id throws, `upsert` is how you say you meant it, `list()`
enumerates, and a fresh one is constructible so registrations do not leak
between tests" — on the Python side, plus the one thing a dict genuinely
cannot express and the reason the second arm existed: an **open namespace**.
`function.<name>` binds a callable named in the *document*, so the set of keys
is not knowable at registration time. A registry that only maps keys cannot
hold that arm, which is why it had stayed an `if`.
"""

from __future__ import annotations

from typing import Any

import pytest

from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.compile.node_types import NodeTypeRegistry


def _builder(name: str):
    def build(node_id: str, node: dict[str, Any], plan: Any) -> Any:  # pragma: no cover
        return name

    build.__name__ = name
    return build


class TestTheRegistryBehavesLikeEveryOtherRegistryHere:
    def test_a_registered_type_resolves_to_its_builder(self) -> None:
        registry = NodeTypeRegistry()
        registry.register("analyse.sentiment", _builder("sentiment"))

        assert registry.resolve("analyse.sentiment").__name__ == "sentiment"

    def test_an_unregistered_type_resolves_to_nothing(self) -> None:
        assert NodeTypeRegistry().resolve("analyse.sentiment") is None

    def test_a_duplicate_registration_throws(self) -> None:
        """Not a returned sentence, as `NodeFamilyRegistry` gives — and the
        difference is the audience. That registry serves *installed* code,
        where one broken plugin must not cost an adopter the rest of the venv.
        This one serves the build's own table, where two claims on one node
        type is a programming error and the loudest moment is import."""
        registry = NodeTypeRegistry()
        registry.register("analyse.sentiment", _builder("first"))

        with pytest.raises(ValueError) as caught:
            registry.register("analyse.sentiment", _builder("second"))

        assert "analyse.sentiment" in str(caught.value)
        assert registry.resolve("analyse.sentiment").__name__ == "first"

    def test_upsert_is_how_you_say_you_meant_it(self) -> None:
        registry = NodeTypeRegistry()
        registry.register("analyse.sentiment", _builder("first"))

        registry.upsert("analyse.sentiment", _builder("second"))

        assert registry.resolve("analyse.sentiment").__name__ == "second"

    def test_list_enumerates_every_registration_including_the_namespaces(self) -> None:
        registry = NodeTypeRegistry()
        registry.register("analyse.sentiment", _builder("sentiment"))
        registry.register_namespace("function.", _builder("discovered"))

        assert [key for key, _ in registry.list()] == ["analyse.sentiment", "function.*"]

    def test_a_fresh_one_carries_no_registrations(self) -> None:
        """The property that keeps registrations from leaking between tests:
        there is no module-level singleton to pollute."""
        NodeTypeRegistry().register("analyse.sentiment", _builder("sentiment"))

        assert NodeTypeRegistry().types() == frozenset()


class TestTheOpenNamespaceIsTheArmADictCouldNotHold:
    def test_any_name_under_the_prefix_resolves(self) -> None:
        registry = NodeTypeRegistry()
        registry.register_namespace("function.", _builder("discovered"))

        assert registry.resolve("function.anything_at_all").__name__ == "discovered"
        assert registry.resolve("functional.no") is None

    def test_an_exact_registration_wins_over_the_namespace_it_falls_under(self) -> None:
        """The order the built-ins depend on: `function.format_report` is a
        built-in, and a package's own `format_report` must not shadow it."""
        registry = NodeTypeRegistry()
        registry.register_namespace("function.", _builder("discovered"))
        registry.register("function.format_report", _builder("built_in"))

        assert registry.resolve("function.format_report").__name__ == "built_in"

    def test_a_duplicate_namespace_throws_too(self) -> None:
        registry = NodeTypeRegistry()
        registry.register_namespace("function.", _builder("first"))

        with pytest.raises(ValueError):
            registry.register_namespace("function.", _builder("second"))

    def test_the_namespaces_are_enumerable(self) -> None:
        registry = NodeTypeRegistry()
        registry.register_namespace("function.", _builder("discovered"))

        assert registry.namespaces() == ("function.",)


class TestTheRuntimeDispatchesThroughIt:
    """Every existing node type resolves exactly as it did, and the two arms
    that used to be `if`s in `builder_for` are now registrations."""

    @pytest.mark.parametrize(
        "node_type,builder_name",
        [
            ("input.text", "_input"),
            ("input.markdown", "_static_text"),
            ("input.skill", "_static_text"),
            ("agent.llm", "_agent"),
            ("route.classifier", "_router"),
            ("route.grader", "_grader"),
            ("human.approval", "_human_approval"),
            ("guard.policy", "_guardrail"),
            ("memory.segment", "_memory_segment"),
            ("orchestrate.supervisor", "_orchestrator"),
            ("orchestrate.worker", "_worker"),
            ("function.format_report", "_format_report_function"),
            ("output.formatted", "_output"),
            # The two conventions, now registered rather than branched on.
            ("workflow.subgraph", "_subgraph"),
            ("function.anything_a_package_defines", "_discovered_function"),
            # And the total fallback, still total.
            ("nobody.implements.this", "_passthrough"),
        ],
    )
    def test_it_resolves_what_it_always_did(self, node_type: str, builder_name: str) -> None:
        assert NodeRuntime(model=None).builder_for(node_type).__name__ == builder_name

    def test_its_public_surface_did_not_grow(self) -> None:
        """CLAUDE.md's ceiling. The registry is a collaborator, and a private
        one — `test_public_surface_ceiling.py` names the eight by hand."""
        runtime = NodeRuntime(model=None)

        assert not hasattr(runtime, "node_types")
