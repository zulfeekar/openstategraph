"""The compiler half of `every-workflow-green` 27.

`abc.router` can now name several branches. This is the part that turns that
into several nodes actually running: LangGraph's conditional edge accepts a
list of destinations and runs them in parallel in the next superstep — its own
documentation says so, and ships a `classify → [a, b, c] → synthesize` recipe.

`decisions[node_id]` stays a **single** label. The compiler dispatches on that
exact key and ticket 09 is the record of what widening it costs, so the set
travels in its own channel and every existing reader, trace row and test keeps
seeing what it always saw.
"""

from __future__ import annotations

from openstategraph.compile.workflow_compiler import WorkflowCompiler


class TestTheDispatchFunction:
    def _route(self, destinations: dict[str, str]):
        return WorkflowCompiler._router_for("r1", destinations)

    def test_one_decision_dispatches_to_one_branch(self) -> None:
        """The label, not the node name: `add_conditional_edges` receives a
        path map and resolves it, so this function has always returned a
        label."""
        route = self._route({"b-a": "node_a", "b-b": "node_b"})
        assert route({"decisions": {"r1": "b-a"}}) == "b-a"

    def test_a_missing_decision_falls_to_the_first_declared(self) -> None:
        """A stall here would be a hang, not an error."""
        route = self._route({"b-a": "node_a", "b-b": "node_b"})
        assert route({"decisions": {}}) == "b-a"

    def test_an_unknown_label_falls_to_the_first_declared(self) -> None:
        route = self._route({"b-a": "node_a", "b-b": "node_b"})
        assert route({"decisions": {"r1": "b-nope"}}) == "b-a"


class TestTheMultiMatchChannel:
    def _route(self, destinations: dict[str, str]):
        return WorkflowCompiler._router_for("r1", destinations)

    def test_two_routes_dispatch_to_both_nodes(self) -> None:
        route = self._route({"b-a": "node_a", "b-b": "node_b"})
        chosen = route({"decisions": {"r1": "b-a"}, "routes": {"r1": ["b-a", "b-b"]}})
        assert chosen == ["b-a", "b-b"]

    def test_a_single_route_stays_a_plain_string(self) -> None:
        """One destination must not become a one-item list — the trace, the
        highlight and every existing test read a name here."""
        route = self._route({"b-a": "node_a", "b-b": "node_b"})
        assert route({"decisions": {"r1": "b-a"}, "routes": {"r1": ["b-a"]}}) == "b-a"

    def test_an_unwired_branch_in_the_set_is_dropped_not_fatal(self) -> None:
        """A half-wired router is a warning at plan time, not a crash here."""
        route = self._route({"b-a": "node_a"})
        assert route({"decisions": {"r1": "b-a"}, "routes": {"r1": ["b-a", "b-b"]}}) == "b-a"

    def test_a_set_of_only_unwired_branches_falls_back(self) -> None:
        route = self._route({"b-a": "node_a", "b-b": "node_b"})
        assert route({"decisions": {"r1": "b-a"}, "routes": {"r1": ["b-zz"]}}) == "b-a"

    def test_no_routes_key_behaves_exactly_as_before(self) -> None:
        """The regression net: every workflow shipping today has no such key."""
        route = self._route({"b-a": "node_a", "b-b": "node_b"})
        assert route({"decisions": {"r1": "b-b"}}) == "b-b"
