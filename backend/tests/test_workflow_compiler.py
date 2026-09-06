"""Tests for the workflow compiler.

The behaviour that matters most is the one that is easy to get silently wrong:
**not every canvas edge is a graph edge.** A tool wired to an agent is a binding,
not a step. If the compiler sequenced it, the tool would run once on its own
before the agent ever called it — and the agent would call it too, doubling the
work and producing a plausible-looking result.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

import pytest
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages

#: `set_node_defaults`/`error_handler` require `langgraph>=1.2`.
_HAS_SET_NODE_DEFAULTS = hasattr(StateGraph, "set_node_defaults")
_SKIP_IF_OLD = pytest.mark.skipif(
    not _HAS_SET_NODE_DEFAULTS,
    reason="`set_node_defaults`/`error_handler` require `langgraph>=1.2`",
)

from openstategraph.compile.workflow_compiler import (
    CompiledPlan,
    WorkflowCompiler,
    default_port_resolver,
    safe_name,
)


class State(TypedDict):
    messages: Annotated[list, add_messages]
    decisions: dict


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def doc(nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    return {"version": 1, "name": "test", "nodes": nodes, "edges": edges}


LINEAR = doc(
    [
        node("in1", "input.text"),
        node("ag1", "agent.llm"),
        node("out1", "output.formatted"),
    ],
    [edge("in1", "text", "ag1", "prompt"), edge("ag1", "result", "out1", "result")],
)


@pytest.fixture
def compiler() -> WorkflowCompiler:
    return WorkflowCompiler()


def build(compiler: WorkflowCompiler, document: dict[str, Any]) -> Any:
    return compiler.build(document, State, lambda _id, _n, _p: (lambda s: {}))


class TestControlFlow:
    def test_a_linear_workflow_becomes_a_linear_graph(self, compiler) -> None:
        plan = compiler.plan(LINEAR)
        assert plan.nodes == ["ag1", "in1", "out1"]
        assert plan.edges == [("ag1", "out1"), ("in1", "ag1")]
        assert plan.entry == ["in1"]
        assert plan.exits == ["out1"]

    def test_it_compiles_to_a_runnable_graph(self, compiler) -> None:
        graph = build(compiler, LINEAR)
        diagram = graph.get_graph().draw_mermaid()
        for name in ("in1", "ag1", "out1"):
            assert name in diagram

    def test_annotations_are_not_graph_nodes(self, compiler) -> None:
        document = doc([*LINEAR["nodes"], node("note1", "annotate.note")], LINEAR["edges"])
        assert "note1" not in compiler.plan(document).nodes

    def test_an_edge_with_an_unknown_endpoint_is_dropped_with_a_warning(self, compiler) -> None:
        document = doc(LINEAR["nodes"], [*LINEAR["edges"], edge("ghost", "text", "ag1", "prompt")])
        plan = compiler.plan(document)
        assert any("unknown endpoint" in w for w in plan.warnings)
        assert len(plan.edges) == 2


class TestBindingsAreNotSteps:
    """The distinction that would be a silent, doubling bug if missed."""

    def test_a_tool_is_bound_not_sequenced(self, compiler) -> None:
        document = doc(
            [*LINEAR["nodes"], node("t1", "tool.chinook-execute-sql")],
            [*LINEAR["edges"], edge("t1", "tool", "ag1", "tools")],
        )
        plan = compiler.plan(document)

        assert plan.tool_bindings == {"ag1": ["t1"]}
        # Not an edge. Sequencing it would run the tool once on its own *and*
        # let the agent call it — the same work twice.
        assert ("t1", "ag1") not in plan.edges

    def test_a_bound_tool_is_not_wired_to_end_either(self, compiler) -> None:
        document = doc(
            [*LINEAR["nodes"], node("t1", "tool.chinook-execute-sql")],
            [*LINEAR["edges"], edge("t1", "tool", "ag1", "tools")],
        )
        plan = compiler.plan(document)
        # It has no control-flow successor, but it is not an exit — otherwise
        # every tool would terminate the graph.
        assert "t1" not in plan.exits

    def test_several_tools_bind_to_one_agent(self, compiler) -> None:
        document = doc(
            [
                *LINEAR["nodes"],
                node("t1", "tool.chinook-get-schema"),
                node("t2", "tool.chinook-execute-sql"),
            ],
            [
                *LINEAR["edges"],
                edge("t1", "tool", "ag1", "tools"),
                edge("t2", "tool", "ag1", "tools"),
            ],
        )
        assert compiler.plan(document).tool_bindings["ag1"] == ["t1", "t2"]

    def test_a_skill_is_bound_not_sequenced(self, compiler) -> None:
        document = doc(
            [*LINEAR["nodes"], node("md1", "input.markdown")],
            [*LINEAR["edges"], edge("md1", "skill", "ag1", "skill")],
        )
        plan = compiler.plan(document)
        assert plan.skill_bindings == {"ag1": ["md1"]}
        assert ("md1", "ag1") not in plan.edges

    def test_a_tool_bound_to_a_worker_is_bound_not_sequenced(self, compiler) -> None:
        """Regression: `WORKER_TYPE`'s port spec never declared `tools`/`skill`.

        Found live: an edge into either fell through `default_port_resolver`'s
        "unknown port" fallback and was treated as ordinary control flow, so
        `plan.tool_bindings` never saw it — a worker wired to Chinook tools on
        the canvas silently ran with none, and the model answered from
        parametric knowledge with nothing to ground it. The agent's own
        `tools`/`skill` ports were covered by `test_a_tool_is_bound_not_sequenced`
        above; the worker's identically-named ports were not, and that gap is
        exactly where the bug lived.
        """
        document = doc(
            [
                node("in1", "input.text"),
                node("orch1", "orchestrate.supervisor"),
                node("w1", "orchestrate.worker"),
                node("t1", "tool.chinook-execute-sql"),
                node("md1", "input.markdown"),
            ],
            [
                edge("in1", "text", "orch1", "instruction"),
                edge("orch1", "workers", "w1", "dispatch"),
                edge("t1", "tool", "w1", "tools"),
                edge("md1", "skill", "w1", "skill"),
            ],
        )
        plan = compiler.plan(document)

        assert plan.tool_bindings == {"w1": ["t1"]}
        assert plan.skill_bindings == {"w1": ["md1"]}
        assert ("t1", "w1") not in plan.edges
        assert ("md1", "w1") not in plan.edges


class TestRouter:
    def test_each_branch_becomes_a_declared_destination(self, compiler) -> None:
        document = doc(
            [
                node("in1", "input.text"),
                node("r1", "route.classifier", branches="dataquery\nhelp"),
                node("ag1", "agent.llm"),
                node("out1", "output.formatted"),
            ],
            [
                edge("in1", "text", "r1", "question"),
                edge("r1", "branch:dataquery", "ag1", "prompt"),
                edge("r1", "branch:help", "out1", "result"),
            ],
        )
        plan = compiler.plan(document)

        # The complete declared destination set — without it every renderer must
        # assume the router reaches any node (ticket 03).
        assert plan.conditional["r1"] == {"dataquery": "ag1", "help": "out1"}
        assert not any(src == "r1" for src, _ in plan.edges)

    def test_the_branch_prefix_is_stripped_to_the_label(self, compiler) -> None:
        document = doc(
            [node("r1", "route.classifier"), node("out1", "output.formatted")],
            [edge("r1", "branch:off-topic", "out1", "result")],
        )
        assert compiler.plan(document).conditional["r1"] == {"off-topic": "out1"}

    def test_it_compiles_to_conditional_edges(self, compiler) -> None:
        document = doc(
            [
                node("in1", "input.text"),
                node("r1", "route.classifier"),
                node("a", "agent.llm"),
                node("b", "output.formatted"),
            ],
            [
                edge("in1", "text", "r1", "question"),
                edge("r1", "branch:x", "a", "prompt"),
                edge("r1", "branch:y", "b", "result"),
            ],
        )
        diagram = build(compiler, document).get_graph().draw_mermaid()
        # Dotted lines are how Mermaid renders a conditional edge.
        assert "-.->" in diagram or "-." in diagram


class TestGraderLoop:
    def _document(self) -> dict[str, Any]:
        return doc(
            [
                node("in1", "input.text"),
                node("ag1", "agent.llm"),
                node("g1", "route.grader"),
                node("out1", "output.formatted"),
            ],
            [
                edge("in1", "text", "ag1", "prompt"),
                edge("ag1", "result", "g1", "candidate"),
                edge("g1", "pass", "out1", "result"),
                edge("g1", "revise", "ag1", "feedback"),
            ],
        )

    def test_pass_and_revise_become_one_conditional_edge(self, compiler) -> None:
        plan = compiler.plan(self._document())
        assert plan.conditional["g1"] == {"pass": "out1", "revise": "ag1"}

    def test_the_revise_edge_does_not_steal_the_entry_node(self, compiler) -> None:
        plan = compiler.plan(self._document())
        # The loop target is usually the entry node. Counting the revise edge as
        # "incoming" would leave the graph with nothing wired to START.
        assert plan.entry == ["in1"]
        assert not plan.warnings

    def test_the_loop_compiles(self, compiler) -> None:
        graph = build(compiler, self._document())
        diagram = graph.get_graph().draw_mermaid()
        assert "g1" in diagram and "ag1" in diagram


class TestNodeNaming:
    def test_graph_node_names_are_workflow_ids_not_labels(self, compiler) -> None:
        # LangGraph treats node names as identity: renaming one hard-breaks an
        # interrupted thread (ticket 04). Ids survive renames and re-layouts.
        document = doc([node("ag1", "agent.llm", title="My Agent")], [])
        assert compiler.plan(document).nodes == ["ag1"]


class TestPortResolution:
    def test_a_router_branch_port_resolves_by_prefix(self) -> None:
        spec = default_port_resolver("route.classifier", "branch:anything")
        assert spec.direction == "out"

    def test_an_unknown_node_type_defaults_to_control_flow(self) -> None:
        # Safe direction: an extra sequencing edge is visible in the preview,
        # whereas a missed one silently drops a step.
        assert default_port_resolver("some.future.node", "in").type == "text"

    def test_the_table_is_injectable_so_it_can_be_replaced_by_generated_output(self) -> None:
        # The duplication with the TypeScript catalogue is deliberate and
        # temporary (ticket 02). It must be replaceable without touching the
        # compiler, or it becomes permanent.
        from openstategraph.compile.workflow_compiler import PortSpec

        calls: list[tuple[str, str]] = []

        def resolver(node_type: str, port_id: str) -> PortSpec:
            calls.append((node_type, port_id))
            return PortSpec("text", "in")

        WorkflowCompiler(port_resolver=resolver).plan(LINEAR)
        assert calls, "the compiler must go through the injected resolver"


class TestPresentationKeysAreIgnored:
    """A link's `vertices` are the editor's business, and only the editor's.

    Waypoints — the points a user drags a run through — are stored on the edge
    in `workflow.json`. The compiler must neither read them nor trip over them:
    where a line is drawn has no bearing on what graph it compiles to, and an
    older build that has never heard of the key must compile the same document
    to the same graph. That is precisely the "additive, so do not bump the
    schema version" rule in `openstategraph/schema.py`, asserted rather than
    assumed.
    """

    def test_a_link_carrying_waypoints_compiles_to_the_same_graph(self, compiler) -> None:
        routed = doc(
            [
                node("in1", "input.text"),
                node("ag1", "agent.llm"),
                node("out1", "output.formatted"),
            ],
            [
                {**edge("in1", "text", "ag1", "prompt"), "vertices": [{"x": 220, "y": 40}]},
                {**edge("ag1", "result", "out1", "result"), "vertices": []},
            ],
        )
        assert compiler.plan(routed).edges == compiler.plan(LINEAR).edges

    def test_the_document_version_did_not_move_for_it(self) -> None:
        """Presentation keys stayed additive — that claim is unchanged.

        The number itself moved to 3 for an unrelated reason: `team.workflow`
        collapsed into `workflow.subgraph`, and a node type id changing is one
        of the listed bumps (production-ready ticket 16). Pinning the literal
        here made this test assert *someone else's* change, so it now asserts
        what it is named for — that vertices and positions bumped nothing.
        """
        from openstategraph.schema import MIGRATIONS

        # v1 -> v2 is the identity: the difference was additive only, which is
        # the property this test exists to protect.
        assert MIGRATIONS[1]({"nodes": []}) == {"nodes": []}


class TestPlanIsInspectable:
    def test_the_plan_is_data_the_generator_can_reuse(self, compiler) -> None:
        # The interpreter and the future code generator must agree. Sharing this
        # plan makes that true by construction rather than by discipline.
        plan = compiler.plan(LINEAR)
        assert isinstance(plan, CompiledPlan)
        assert plan.edges and plan.entry and plan.exits


class TestRealCanvasIds:
    """Regressions from compiling a document actually exported from the canvas.

    Both of these sailed past every hand-written fixture, because fixtures use
    tidy ids like `ag1` and wire only what the test is about. Neither bug was
    hypothetical — the first raised, the second silently doubled work.
    """

    REAL_ID = "node:agent.llm-1"

    def test_a_real_node_id_is_made_graph_legal(self) -> None:
        # LangGraph reserves ':' in node names, so `add_node` raised outright.
        assert ":" not in safe_name(self.REAL_ID)
        assert safe_name(self.REAL_ID) == "node_agent_llm_1"

    def test_distinct_ids_stay_distinct_after_sanitising(self) -> None:
        assert safe_name("node:a.b-1") != safe_name("node:a.b-2")

    def test_a_document_with_real_ids_compiles(self, compiler) -> None:
        document = doc(
            [node("node:input.text-1", "input.text"), node(self.REAL_ID, "agent.llm")],
            [edge("node:input.text-1", "text", self.REAL_ID, "prompt")],
        )
        graph = build(compiler, document)
        assert "node_agent_llm_1" in graph.get_graph().draw_mermaid()

    def test_a_bound_tool_is_not_a_graph_node_at_all(self, compiler) -> None:
        document = doc(
            [*LINEAR["nodes"], node("t1", "tool.reddit-search")],
            [*LINEAR["edges"], edge("t1", "tool", "ag1", "tools")],
        )
        plan = compiler.plan(document)

        # The bug this replaces: excluding it from `exits` but not from `nodes`
        # left it with no incoming edge, so it became an `entry` and was wired
        # from START — the tool ran once at graph start *and* again when the
        # agent called it. The earlier tests only asserted `exits`, so they
        # passed while the doubling was live.
        assert "t1" not in plan.nodes
        assert "t1" not in plan.entry
        assert plan.bound_only == ["t1"]

    def test_a_node_that_is_both_bound_and_sequenced_stays_a_graph_node(
        self, compiler
    ) -> None:
        # A markdown file feeding an agent's skill *and* an output node is a real
        # step as well as a binding, so excluding it would drop the step.
        document = doc(
            [*LINEAR["nodes"], node("md1", "input.markdown")],
            [
                *LINEAR["edges"],
                edge("md1", "skill", "ag1", "skill"),
                edge("md1", "skill", "out1", "result"),
            ],
        )
        plan = compiler.plan(document)
        assert "md1" in plan.nodes


class FaultState(TypedDict, total=False):
    outputs: dict
    calls: int


class TestFaultTolerance:
    """`set_node_defaults(retry_policy=..., error_handler=...)` (see `build`).

    Not a theoretical nicety: a live run this session hit a real, transient
    `ollama._types.ResponseError` mid-workflow, and retrying resolved it on
    the next attempt. These pin both halves — the retry actually happens,
    and a node that never recovers still lets the run finish rather than
    crashing the whole graph.
    """

    @staticmethod
    def _linear(node_id: str = "n1") -> dict[str, Any]:
        return doc(
            [node("in1", "input.text"), node(node_id, "agent.llm"), node("out1", "output.formatted")],
            [
                edge("in1", "text", node_id, "prompt"),
                edge(node_id, "result", "out1", "result"),
            ],
        )

    @_SKIP_IF_OLD
    def test_a_node_that_fails_twice_then_succeeds_is_retried_not_aborted(
        self, compiler
    ) -> None:
        calls = {"n": 0}

        def flaky_factory(node_id: str, _node: dict[str, Any], _plan: Any) -> Any:
            if node_id != "n1":
                return lambda state: {}

            def run(state: FaultState) -> dict[str, Any]:
                calls["n"] += 1
                if calls["n"] < 3:
                    raise ConnectionError("transient provider error")
                return {"outputs": {"n1": "recovered"}}

            return run

        graph = compiler.build(self._linear(), FaultState, flaky_factory)
        final = graph.invoke({})

        assert calls["n"] == 3
        assert final["outputs"]["n1"] == "recovered"

    @_SKIP_IF_OLD
    def test_a_node_that_never_recovers_still_lets_the_run_finish(
        self, compiler
    ) -> None:
        def always_fails_factory(node_id: str, _node: dict[str, Any], _plan: Any) -> Any:
            if node_id != "n1":
                return lambda state: {}

            def run(state: FaultState) -> dict[str, Any]:
                raise RuntimeError("boom")

            return run

        graph = compiler.build(self._linear(), FaultState, always_fails_factory)
        # Must not raise: the error handler recovers and the graph reaches END.
        final = graph.invoke({})

        assert "failed after retries" in final["outputs"]["n1"]
        assert "boom" in final["outputs"]["n1"]

    @_SKIP_IF_OLD
    def test_the_failure_is_filed_under_the_canvas_id_not_the_graph_name(
        self, compiler
    ) -> None:
        """`n1` cannot prove this: `safe_name` leaves it unchanged.

        LangGraph names the failing node with whatever `add_node` was given —
        `safe_name(id)`, which rewrites every non-alphanumeric character — but
        every reader of `outputs` uses the *canvas* id (`_upstream_text`, the
        `update` frame's output lookup, the trace). Filing the failure under
        the mangled name writes it where nothing looks, so a node that failed
        after retries reads downstream as a node that produced nothing: the
        grader calls it an empty answer and burns its whole retry budget on a
        provider outage it is never told about.

        Every id in the existing fault tests survives `safe_name` untouched,
        which is the same collision that hid the mounted-output defect.
        """

        def always_fails_factory(node_id: str, _node: dict[str, Any], _plan: Any) -> Any:
            if node_id != "agent-sql":
                return lambda state: {}

            def run(state: FaultState) -> dict[str, Any]:
                raise RuntimeError("boom")

            return run

        graph = compiler.build(self._linear("agent-sql"), FaultState, always_fails_factory)
        final = graph.invoke({})

        assert "agent_sql" not in final["outputs"], (
            "the failure was filed under the graph's name for the node, which "
            "no reader of `outputs` ever uses"
        )
        assert "boom" in final["outputs"]["agent-sql"]

    @_SKIP_IF_OLD
    def test_the_error_handler_does_not_mask_a_programming_error_by_retrying_it(
        self, compiler
    ) -> None:
        """`default_retry_on` excludes `ValueError`/`TypeError` etc. — a bug
        should fail fast, once, not be retried into a longer timeout."""
        calls = {"n": 0}

        def buggy_factory(node_id: str, _node: dict[str, Any], _plan: Any) -> Any:
            if node_id != "n1":
                return lambda state: {}

            def run(state: FaultState) -> dict[str, Any]:
                calls["n"] += 1
                raise ValueError("this is a bug, not a flaky network call")

            return run

        graph = compiler.build(self._linear(), FaultState, buggy_factory)
        final = graph.invoke({})

        assert calls["n"] == 1
        assert "this is a bug" in final["outputs"]["n1"]
