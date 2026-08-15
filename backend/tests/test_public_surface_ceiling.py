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

**A member here is one a consumer can reach**: a public attribute assigned to
`self` anywhere in the class, or a public method. Collaborators count as one —
`runtime.services` is a member, `runtime.services.tools` is not, which is the
whole point of the grouping and also how `WorkflowController` is described in
CLAUDE.md.

**It measures a class, not an instance, and that took a second attempt.** Until
the 2026-08-15 audit this file called `vars()` on a *fresh* `NodeRuntime`, so it
could not see `last_bound_tools` — assigned inside `build_agent` rather than
`__init__`, and read by eight assertions across four test modules. A runtime
that had built one agent was a member wider than the pin claimed was possible,
and the pin could not fail. Attributes are therefore found by reading the class,
not by inspecting one object that happens not to have been used yet.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from openstategraph.compile.diagnostics import CompileDiagnostics
from openstategraph.compile.node_runtime import NodeRuntime

#: The ceiling, from CLAUDE.md. "~10", read strictly — a rule with a soft edge
#: is a rule that is always nearly kept.
CEILING = 10


def assigned_to_self(cls: type) -> set[str]:
    """Public attributes the class gives itself, wherever it does it.

    `__init__` is the usual place and not the only one, which is exactly the
    defect this replaced: an attribute a method adds is as reachable as one the
    constructor adds, and considerably easier to add without noticing.
    """
    try:
        source = textwrap.dedent(inspect.getsource(cls))
    except (OSError, TypeError):  # pragma: no cover — no source (C, REPL)
        return set()
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and not target.attr.startswith("_")
            ):
                found.add(target.attr)
    return found


def public_members(subject: type) -> set[str]:
    """What a consumer of this class can reach."""
    methods = {name for name, _ in inspect.getmembers(subject) if not name.startswith("_")}
    return methods | assigned_to_self(subject)


@pytest.mark.parametrize(
    "subject",
    [
        pytest.param(NodeRuntime, id="NodeRuntime"),
        pytest.param(CompileDiagnostics, id="CompileDiagnostics"),
    ],
)
def test_it_stays_under_the_ceiling(subject: type) -> None:
    members = public_members(subject)

    assert len(members) <= CEILING, (
        f"{subject.__name__} has {len(members)} public members, "
        f"ceiling is {CEILING}: {sorted(members)}. Add a collaborator, not a member "
        "— or record the exception the way CLAUDE.md records WorkflowModel's."
    )


def test_an_attribute_a_method_adds_is_counted() -> None:
    """The pin's own failure mode, held open.

    `NodeRuntime.last_bound_tools` is the real instance of this and is asserted
    by name below; a fixture is what keeps the *counting* honest if that
    attribute ever moves into `__init__` and the class stops being the example.
    """

    class Sneaks:
        def __init__(self) -> None:
            self.declared = 1

        def later(self) -> None:
            self.added = 2

    assert public_members(Sneaks) == {"declared", "added", "later"}


def test_the_runtimes_members_are_each_nameable_without_and() -> None:
    """The count is the symptom; "described only with and" is the rule.

    Pinned by name rather than by number alone, so that swapping one concern
    for another silently — the refactor that keeps the count and loses the
    design — shows up as a diff here.
    """
    assert public_members(NodeRuntime) == {
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
        # The seventh, named rather than hidden. Written by `_agent` after it
        # binds (`node_runtime.py:1459`) so a test can assert the wiring
        # produced the tools without a model — a test seam, and a test seam on
        # the public surface is still on the public surface. It is what the old
        # `vars()`-on-a-fresh-instance pin could not see.
        "last_bound_tools",
    }
