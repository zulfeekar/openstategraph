"""A Team promises an outcome nothing enforces — production-ready ticket 03.

`TeamNode` carries an `Expected outcome` textarea. The value **never reaches
the compiler**: `_subgraph` reads `data["workflow"]` and `data["overrides"]`
and nothing else. So a user writes a constraint, reasonably believes it binds
the run, and gets no signal that it does not — the RouterNode lesson in a
different field, a surface presenting a machine-owned promise as if it were
configuration.

Worse, a document with **no grader at all** can be mounted as a Team. It still
says Team, still runs, and still displays an outcome nobody checks.

The editor half is copy (`TeamNode`'s label and hint) and the card census. This
is the run half: loud, not fatal, on the channel unresolved capabilities
already use. Not fatal on purpose — a Team without a loop is a legal graph that
answers questions; what it cannot do is keep the promise printed on its card.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.diagnostics import Finding
from openstategraph.api.registries import runtime_warnings
from openstategraph.compile.node_runtime import NodeRuntime, RuntimeServices
from openstategraph.compile.workflow_compiler import CompiledPlan

LOOPING = {
    "nodes": [
        {"id": "cin", "type": "input.text", "data": {}},
        {"id": "agent1", "type": "agent.llm", "data": {}},
        {"id": "grader1", "type": "route.grader", "data": {}},
        {"id": "cout", "type": "output.formatted", "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "cin", "portId": "text"}, "target": {"nodeId": "agent1", "portId": "prompt"}},
        {"source": {"nodeId": "agent1", "portId": "result"}, "target": {"nodeId": "grader1", "portId": "candidate"}},
        {"source": {"nodeId": "grader1", "portId": "pass"}, "target": {"nodeId": "cout", "portId": "result"}},
        {"source": {"nodeId": "grader1", "portId": "revise"}, "target": {"nodeId": "agent1", "portId": "feedback"}},
    ],
}

GRADERLESS = {
    "nodes": [
        {"id": "cin", "type": "input.text", "data": {}},
        {"id": "agent1", "type": "agent.llm", "data": {}},
        {"id": "cout", "type": "output.formatted", "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "cin", "portId": "text"}, "target": {"nodeId": "agent1", "portId": "prompt"}},
        {"source": {"nodeId": "agent1", "portId": "result"}, "target": {"nodeId": "cout", "portId": "result"}},
    ],
}

#: A grader that judges but never sends anything back — no loop closes.
OPEN_LOOP = {
    "nodes": GRADERLESS["nodes"] + [{"id": "grader1", "type": "route.grader", "data": {}}],
    "edges": [
        {"source": {"nodeId": "cin", "portId": "text"}, "target": {"nodeId": "agent1", "portId": "prompt"}},
        {"source": {"nodeId": "agent1", "portId": "result"}, "target": {"nodeId": "grader1", "portId": "candidate"}},
        {"source": {"nodeId": "grader1", "portId": "pass"}, "target": {"nodeId": "cout", "portId": "result"}},
    ],
}


def mount(child: dict[str, Any], node_type: str = "workflow.subgraph") -> NodeRuntime:
    runtime = NodeRuntime(
        services=RuntimeServices(model=None, document_loader=lambda _slug: child)
    )
    node = {
        "id": "team1",
        "type": node_type,
        "data": {"workflow": "child-pkg", "outcome": "Must cite a source for every claim."},
    }
    runtime._subgraph("team1", node, CompiledPlan())
    return runtime


class TestTheGapIsReported:
    def test_a_grader_less_child_is_reported(self) -> None:
        """The case a user can reach today with no warning at all."""
        assert mount(GRADERLESS).diagnostics.any(Finding.UNENFORCED_OUTCOME)

    def test_a_grader_that_never_revises_is_reported_too(self) -> None:
        """Present is not the same as wired.

        A grader with no `revise` destination judges once and passes whatever
        it got — there is no loop for the outcome to be enforced by.
        """
        assert mount(OPEN_LOOP).diagnostics.any(Finding.UNENFORCED_OUTCOME)

    def test_a_real_looping_team_is_not_reported(self) -> None:
        assert not mount(LOOPING).diagnostics.any(Finding.UNENFORCED_OUTCOME)

    def test_a_mount_that_promises_nothing_is_never_reported(self) -> None:
        """The rule is the promise, not the card.

        This asserted that a `workflow.subgraph` mount is never reported, which
        was the same thing while `team.workflow` existed. Since schema v3 there
        is one mount type (ticket 16), so what earns the warning is prose on
        the card claiming an outcome — a mount with none claims nothing.
        """
        runtime = NodeRuntime(
            services=RuntimeServices(model=None, document_loader=lambda _slug: GRADERLESS)
        )
        runtime._subgraph(
            "mount1",
            {"id": "mount1", "type": "workflow.subgraph", "data": {"workflow": "child-pkg"}},
            CompiledPlan(),
        )
        assert not runtime.diagnostics.any(Finding.UNENFORCED_OUTCOME)

    def test_an_unresolvable_child_is_left_to_its_own_warning(self) -> None:
        """`UNRESOLVED_SUBGRAPH` already says the child could not be loaded.

        Adding "and its outcome is unenforced" would report a second, weaker
        consequence of the same fact.
        """
        runtime = NodeRuntime(
            services=RuntimeServices(
                model=None, document_loader=lambda _slug: (_ for _ in ()).throw(FileNotFoundError())
            )
        )
        node = {"id": "team1", "type": "team.workflow", "data": {"workflow": "missing"}}
        runtime._subgraph("team1", node, CompiledPlan())
        assert not runtime.diagnostics.any(Finding.UNENFORCED_OUTCOME)


class TestTheWarningReadsLikeAProduct:
    def _warning(self) -> str:
        warnings = runtime_warnings(mount(GRADERLESS))
        matching = [w for w in warnings if "team1" in w]
        assert matching, warnings
        return matching[0]

    def test_it_names_the_node_and_the_child(self) -> None:
        warning = self._warning()
        assert "team1" in warning
        assert "child-pkg" in warning

    def test_it_says_the_outcome_is_not_checked(self) -> None:
        assert "outcome" in self._warning().lower()

    def test_it_points_at_the_fix_rather_than_only_the_fault(self) -> None:
        """Where enforcement actually lives — a grader in the child."""
        assert "grader" in self._warning().lower()

    def test_it_carries_no_stack_trace(self) -> None:
        warning = self._warning()
        assert "Traceback" not in warning
        assert ".py" not in warning


class TestItIsLoudNotFatal:
    def test_the_mount_still_compiles_and_runs(self) -> None:
        """A Team without a loop is a legal graph that answers questions.

        What it cannot do is keep the promise printed on its card, which is a
        thing to say, not a thing to refuse.
        """
        runtime = mount(GRADERLESS)
        assert runtime.diagnostics.any(Finding.UNENFORCED_OUTCOME)
        assert not runtime.diagnostics.any(Finding.UNRESOLVED_SUBGRAPH)
