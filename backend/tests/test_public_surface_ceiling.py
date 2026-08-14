"""CLAUDE.md's ceiling, enforced rather than described.

    "A class with many public members is a design failure, not a convenience.
    If it can be described only with 'and', split it. Ceiling: ~10 public
    members, one reason to change."

`NodeRuntime` was at 26 when the system design review measured it
(reviews-2026-08-14 ticket 07) and failed the "and" test outright: builder
registry **and** model resolver **and** tool binder **and** diagnostics
accumulator **and** mount-identity registry. Its docstring defended only the
first.

This file exists because the count is the part that regrows. Every extraction
is one commit and one good intention; the attribute added six months later to
save a parameter is neither, and nothing would have said so. A ceiling nobody
measures is a preference.

**A member here is one a consumer can reach**: a public attribute set in
`__init__` or a public method. Collaborators count as one — `runtime.services`
is a member, `runtime.services.tools` is not, which is the whole point of the
grouping and also how `WorkflowController` is described in CLAUDE.md.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.compile.node_runtime import NodeRuntime

#: The ceiling, from CLAUDE.md. "~10", read strictly — a rule with a soft edge
#: is a rule that is always nearly kept.
CEILING = 10


def public_members(instance: Any) -> set[str]:
    """What a consumer of this object can reach."""
    methods = {
        name for name, _ in inspect.getmembers(type(instance)) if not name.startswith("_")
    }
    attributes = {name for name in vars(instance) if not name.startswith("_")}
    return methods | attributes


@pytest.mark.parametrize(
    "instance",
    [
        pytest.param(NodeRuntime(model=None), id="NodeRuntime"),
        pytest.param(CompileDiagnostics(), id="CompileDiagnostics"),
    ],
)
def test_it_stays_under_the_ceiling(instance: Any) -> None:
    members = public_members(instance)

    assert len(members) <= CEILING, (
        f"{type(instance).__name__} has {len(members)} public members, "
        f"ceiling is {CEILING}: {sorted(members)}. Add a collaborator, not a member "
        "— or record the exception the way CLAUDE.md records WorkflowModel's."
    )


def test_the_runtimes_members_are_each_nameable_without_and() -> None:
    """The count is the symptom; "described only with and" is the rule.

    Pinned by name rather than by number alone, so that swapping one concern
    for another silently — the refactor that keeps the count and loses the
    design — shows up as a diff here.
    """
    assert public_members(NodeRuntime(model=None)) == {
        # What it is for: turning a node in a document into a graph node.
        "factory",
        "builder_for",
        # Who it collaborates with, as one named object each.
        "services",
        "diagnostics",
        "names",
        # What compiling this document established about the graph's own
        # names — see `machinery_nodes`' docstring for why it is not in
        # `names`.
        "machinery_nodes",
    }
