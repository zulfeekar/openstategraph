"""The two sides agree on which node types drive a model.

This is the guard for a defect that produced no error at all. The editor
declared the model picker on `agent.llm` alone; the compiler's
`NodeRuntime._resolve_model(data)` read `data["model"]` for six node types.
Five of them therefore ran whichever model the *request* resolved, silently,
while their cards offered no way to say otherwise — and a wrong model does not
raise, it just answers slightly worse.

So the fact is declared once in TypeScript (`src/nodes/modelField.ts`, emitted
into `port_specs.json` as `drives_model`) and asserted here against the
compiler's own factory table. A new model-driven node type that forgets the
field, or a factory that starts resolving a model without one, fails here.
"""

from __future__ import annotations

import inspect

from openstategraph.compile.node_catalogue import load_catalogue
from openstategraph.compile.node_runtime import NodeRuntime


def _factories_resolving_a_model() -> set[str]:
    """Node types whose factory calls `_resolve_model`, read from the source.

    Reading the source rather than maintaining a hand-written list is the whole
    point: a list would be a third declaration to keep in step, which is the
    class of bug this test exists to catch.
    """
    runtime = NodeRuntime(model=None)
    resolving: set[str] = set()
    for node_type, builder in runtime._builders.items():
        try:
            source = inspect.getsource(builder)
        except (OSError, TypeError):  # pragma: no cover - source always available here
            continue
        if "_resolve_model(" in source:
            resolving.add(node_type)
    return resolving


class TestTheModelFieldContract:
    def test_the_editor_declares_a_picker_for_every_node_that_resolves_a_model(
        self,
    ) -> None:
        declared = load_catalogue().model_driven
        resolving = _factories_resolving_a_model()
        missing = resolving - declared
        assert not missing, (
            f"{sorted(missing)} resolve a model in node_runtime.py but declare no "
            "`model` field in the editor — nobody can choose the model these nodes "
            "run on. Add `modelField(providers)` to the node definition and run "
            "`npm run generate:ports`."
        )

    def test_no_node_offers_a_picker_the_compiler_ignores(self) -> None:
        declared = load_catalogue().model_driven
        resolving = _factories_resolving_a_model()
        unread = declared - resolving
        assert not unread, (
            f"{sorted(unread)} offer a model picker the compiler never reads — the "
            "card would promise a choice that changes nothing."
        )

    def test_the_set_is_not_accidentally_empty(self) -> None:
        """A contract test that passes because both sides are empty is no test."""
        assert len(load_catalogue().model_driven) >= 5
