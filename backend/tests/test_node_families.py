"""A node family is contributed, not merged — install-experience ticket 08.

The extendability walk of 2026-08-15 checked both halves of CLAUDE.md's **O**
("extend by registering, never by editing the engine"). The editor's half held;
the compiler's did not. `NodeRuntime._builders` was a private dict literal
inside `__init__`, so a node *family* the engine had never heard of resolved to
`_passthrough`: it compiled, it ran, and it did nothing.

What this file pins is the whole seam — the registry's refusals, the
entry-point group, and the two properties that make the answer honest rather
than merely present: a registered family's step **actually runs**, and an
unregistered one is still **loud**.
"""

from __future__ import annotations

from typing import Any

import pytest

from openstategraph.abc import BaseNodeFamily, NodeBuildContext
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.node_families import NodeFamilyRegistry
from openstategraph.compile.node_runtime import NodeRuntime
from openstategraph.extensions import NODE_FAMILIES_GROUP, entry_point_node_families
from test_extensions import FakeEntryPoint, install


class SentimentFamily(BaseNodeFamily):
    """The family a third-party distribution would ship."""

    node_type = "analyse.sentiment"

    def respond(self, text: str, context: NodeBuildContext) -> str:
        lexicon = str(context.data.get("positive") or ":)")
        return "positive" if lexicon in text else "negative"


class ShadowingInput(BaseNodeFamily):
    """A family claiming a node type this build implements itself."""

    node_type = "input.text"

    def respond(self, text: str, context: NodeBuildContext) -> str:
        return "not the built-in"


class ExplodingFamily(BaseNodeFamily):
    node_type = "analyse.explode"

    def build(self, context: NodeBuildContext) -> Any:
        raise RuntimeError("this family cannot build")

    def respond(self, text: str, context: NodeBuildContext) -> str:  # pragma: no cover
        return ""


def _document(node_type: str) -> dict[str, Any]:
    """in -> the node under test -> out. The smallest graph that proves it ran."""
    return {
        "version": 1,
        "name": "families",
        "settings": {},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}, "position": {"x": 0, "y": 0}},
            {"id": "s1", "type": node_type, "data": {}, "position": {"x": 200, "y": 0}},
            {
                "id": "o1",
                "type": "output.formatted",
                "data": {},
                "position": {"x": 400, "y": 0},
            },
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "s1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "s1", "portId": "result"},
                "target": {"nodeId": "o1", "portId": "text"},
            },
        ],
    }


def _run(document: dict[str, Any], question: str) -> tuple[str, NodeRuntime]:
    """Compile and run one document, with no model anywhere near it."""
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    runtime = NodeRuntime(model=None)
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    result = graph.invoke({"question": question})
    return str(result.get("answer", "")), runtime


class TestTheRegistryRefusesBeforeItAccepts:
    """Every refusal returns one sentence naming who to go and fix, never raises.

    One half-installed plugin in a venv must not cost an adopter every other
    capability in it — the rule `extensions` states and this obeys.
    """

    def test_a_family_is_reachable_by_the_node_type_it_declares(self) -> None:
        registry = NodeFamilyRegistry()

        assert registry.register(SentimentFamily(), source="acme") is None
        assert registry.get("analyse.sentiment") is not None
        assert registry.types() == frozenset({"analyse.sentiment"})
        assert registry.source_of("analyse.sentiment") == "acme"

    def test_a_family_declaring_no_node_type_is_refused(self) -> None:
        class Unplaceable(BaseNodeFamily):
            def respond(self, text: str, context: NodeBuildContext) -> str:
                return text

        refusal = NodeFamilyRegistry().register(Unplaceable(), source="acme")

        assert refusal is not None and "node_type" in refusal and "acme" in refusal

    def test_an_object_that_is_not_a_family_is_refused(self) -> None:
        class NotAFamily:
            node_type = "analyse.sentiment"

        refusal = NodeFamilyRegistry().register(NotAFamily(), source="acme")

        assert refusal is not None and "build(context)" in refusal

    @pytest.mark.parametrize("node_type", ["function.my_fn", "workflow.subgraph"])
    def test_the_compilers_own_conventions_are_reserved(self, node_type: str) -> None:
        """A `function.<name>` node binds a callable named in the *document*.

        A distribution able to inject one would change what a package's own
        node resolves to, with nowhere in the document to name the provider or
        even to see that a provider exists — `extensions`' own reasoning for
        refusing an `openstategraph.functions` group.
        """
        refusal = NodeFamilyRegistry().register(_family(node_type), source="acme")

        assert refusal is not None and "reserved" in refusal

    def test_two_distributions_claiming_one_node_type_are_both_named(self) -> None:
        registry = NodeFamilyRegistry()
        registry.register(SentimentFamily(), source="acme")

        refusal = registry.register(SentimentFamily(), source="globex")

        assert refusal is not None
        assert "acme" in refusal and "globex" in refusal


def _family(node_type: str) -> BaseNodeFamily:
    class Anonymous(BaseNodeFamily):
        def respond(self, text: str, context: NodeBuildContext) -> str:
            return text

    family = Anonymous()
    family.node_type = node_type  # type: ignore[misc]
    return family


class TestAFamilyFromAnInstalledDistribution:
    def test_it_reaches_the_compilers_dispatch(self, monkeypatch) -> None:
        install(
            monkeypatch,
            FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "openstategraph-acme", SentimentFamily),
        )

        assert "analyse.sentiment" in entry_point_node_families().values.types()
        assert NodeRuntime(model=None).builder_for("analyse.sentiment").__name__ != "_passthrough"

    def test_an_instance_works_as_well_as_a_class(self, monkeypatch) -> None:
        install(
            monkeypatch,
            FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", SentimentFamily()),
        )

        assert "analyse.sentiment" in entry_point_node_families().values.types()

    def test_its_step_actually_runs(self, monkeypatch) -> None:
        """The whole ticket in one assertion.

        Before this seam the same document compiled, ran, returned 200 — and
        answered the user's own question back, because the unknown node
        forwarded its input unchanged.
        """
        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", SentimentFamily))

        answer, _runtime = _run(_document("analyse.sentiment"), "the release shipped :)")

        assert answer == "positive"

    def test_it_reads_its_own_nodes_configuration(self, monkeypatch) -> None:
        """`context.data` is the node's card, as the editor saved it."""
        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", SentimentFamily))
        document = _document("analyse.sentiment")
        document["nodes"][1]["data"] = {"positive": "shipped"}

        answer, _runtime = _run(document, "the release shipped")

        assert answer == "positive"

    def test_a_broken_family_costs_its_node_and_not_the_compile(self, monkeypatch) -> None:
        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", ExplodingFamily))

        answer, runtime = _run(_document("analyse.explode"), "does this compile?")

        assert "this family cannot build" in " ".join(runtime.diagnostics.warnings())
        # Degraded to the passthrough, which says so in the answer rather than
        # forwarding the question and looking like it worked.
        assert "analyse.explode" in answer or "produced nothing" in answer

    def test_plugins_can_be_switched_off_entirely(self, monkeypatch) -> None:
        from openstategraph.extensions import DISABLE_PLUGINS_ENV

        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", SentimentFamily))
        monkeypatch.setenv(DISABLE_PLUGINS_ENV, "1")

        assert entry_point_node_families().values.types() == frozenset()


class TestABuiltInCanNeverBeShadowed:
    """A bundled *tool* is replaceable; a built-in *family* is not.

    That asymmetry is deliberate and is stated at `NODE_FAMILIES_GROUP`: a tool
    is a capability, while a built-in node family is part of what a document
    *means*. `input.text` resolving to somebody else's code would change every
    workflow in the venv, including the ones that never heard of the plugin.
    """

    def test_the_built_in_still_wins(self, monkeypatch) -> None:
        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", ShadowingInput))

        assert NodeRuntime(model=None).builder_for("input.text").__name__ == "_input"

    def test_the_attempt_is_reported_and_names_the_distribution(self, monkeypatch) -> None:
        """Silence here would leave a plugin author debugging a family that
        registered cleanly and is never built."""
        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme-dist", ShadowingInput))

        sentences = NodeRuntime(model=None).diagnostics.warnings()

        assert any("acme-dist" in s and "input.text" in s for s in sentences)


class TestValidationKnowsWhatTheProcessCanBuild:
    def test_a_registered_family_is_no_longer_an_unknown_type(self, monkeypatch) -> None:
        """Otherwise the seam is only half open: the node runs, and the
        validator a user reads still calls it unknown."""
        from openstategraph.validation import validate_document

        install(monkeypatch, FakeEntryPoint("acme", NODE_FAMILIES_GROUP, "acme", SentimentFamily))

        _valid, findings = validate_document(_document("analyse.sentiment"))

        assert not any("analyse.sentiment" in finding for finding in findings)

    def test_an_unregistered_family_is_still_named(self) -> None:
        from openstategraph.validation import validate_document

        valid, findings = validate_document(_document("analyse.sentiment"))

        assert valid is False
        assert any("analyse.sentiment" in finding for finding in findings)


class TestAnUnregisteredFamilyStaysLoud:
    """The ticket's honest question: should the fallback still be a passthrough?

    Answer, recorded on the ticket: **yes, and it must keep saying so.** The
    HTTP run path deliberately does not gate on validation — a canvas mid-edit
    is invalid most of the time — so refusing to compile would make the editor
    unusable, while `errors.py`'s rule ("degrade loud, never silent") is
    already satisfied by the two things asserted here.
    """

    def test_the_type_and_the_node_are_both_reported(self) -> None:
        runtime = NodeRuntime(model=None)
        document = _document("analyse.sentiment")

        runtime.factory(document)("s1", document["nodes"][1], _plan(document))

        assert ("analyse.sentiment", "s1") in runtime.diagnostics.subjects(
            Finding.UNKNOWN_NODE_TYPE
        )

    def test_the_run_says_the_step_produced_nothing(self) -> None:
        """Not the user's own question echoed back, which is how this hid."""
        answer, _runtime = _run(_document("analyse.sentiment"), "what is 2+2?")

        assert answer != "what is 2+2?"
        assert "produced nothing" in answer


def _plan(document: dict[str, Any]) -> Any:
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    return WorkflowCompiler().plan(document)
