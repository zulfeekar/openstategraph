"""The two sides agree on which node types accept a wired skill.

The sibling of `test_model_field_contract.py`, guarding the same shape of
silence. This runtime reads `plan.skill_bindings` and composes the wired file
into the prompt for five node types; the editor declared the `skill` port on
two of them. The other three had a compiler ready to read something no canvas
could wire — and an absent capability raises nothing, it just never happens.

So the fact is declared once in TypeScript (`src/nodes/skillLayer.ts`, emitted
into `port_specs.json` as `accepts_skill`) and asserted here against the
compiler's own factory table, read from source rather than from a hand-kept
list — a list would be the third declaration this file exists to prevent.

The mode is pinned alongside the port on purpose. A `rulesMode` select on a
node whose builder never calls `_replaces_rules` is a control that reaches
nothing, which is exactly what the worker shipped until ticket 05: its wired
skill *replaced* the tool directive unconditionally, so the switch on its card
would have been decoration.
"""

from __future__ import annotations

import inspect

from openstategraph.compile.node_catalogue import load_catalogue
from openstategraph.compile.node_runtime import NodeRuntime

#: The five prompted families, spelled out once so a set that silently
#: collapses to two cannot pass every assertion below.
MODEL_DRIVEN = {
    "agent.llm",
    "orchestrate.worker",
    "orchestrate.supervisor",
    "route.classifier",
    "route.grader",
}


def _factories_mentioning(needle: str) -> set[str]:
    """Node types whose factory contains `needle`, read from the source."""
    runtime = NodeRuntime(model=None)
    found: set[str] = set()
    for node_type, builder in runtime._builders.items():
        try:
            source = inspect.getsource(builder)
        except (OSError, TypeError):  # pragma: no cover - source always available here
            continue
        if needle in source:
            found.add(node_type)
    return found


class TestTheSkillPortContract:
    def test_every_node_that_reads_a_skill_binding_declares_the_port(self) -> None:
        declared = load_catalogue().accepts_skill
        reading = _factories_mentioning("plan.skill_bindings")
        missing = reading - declared
        assert not missing, (
            f"{sorted(missing)} compose a wired skill in node_runtime.py but declare "
            "no `skill` port in the editor — no canvas can wire the thing they read. "
            "Add `SKILL_PORT` from `src/nodes/skillLayer.ts` to the node definition "
            "and run `npm run generate:ports`."
        )

    def test_no_node_offers_a_skill_port_the_compiler_ignores(self) -> None:
        declared = load_catalogue().accepts_skill
        reading = _factories_mentioning("plan.skill_bindings")
        unread = declared - reading
        assert not unread, (
            f"{sorted(unread)} offer a `skill` port nothing reads — the card would "
            "accept a file that changes nothing about the run."
        )

    def test_the_set_is_the_five_model_driven_families(self) -> None:
        """A contract test that passes because both sides are empty is no test.

        And the set is not arbitrary: a skill goes on the node types that
        compose a prompt, never on a tool or an I/O atom, where the port would
        be a control reaching nothing.
        """
        assert load_catalogue().accepts_skill == MODEL_DRIVEN

    def test_a_skill_port_and_a_rules_mode_always_travel_together(self) -> None:
        """The mode is what says whether a skill adds to the node's rules or
        stands in for them, so a node that takes one without honouring the
        other has a switch that reaches nothing."""
        honouring = _factories_mentioning("_replaces_rules(")
        assert load_catalogue().accepts_skill == honouring


class TestTheEditorAndTheCompilerAgreeOnBothHalves:
    def test_the_skill_accepting_set_is_exactly_the_model_driven_set(self) -> None:
        """Every node that composes a prompt drives a model, and vice versa —
        which is the reason the skill port belongs to these five and nowhere
        else. Stated as a test so a sixth model-driven type cannot quietly ship
        without one."""
        catalogue = load_catalogue()
        assert catalogue.accepts_skill <= catalogue.model_driven
