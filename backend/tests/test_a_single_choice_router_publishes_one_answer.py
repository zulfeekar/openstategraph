"""One verdict, one destination — `osg-agent-experience/80`.

The owner asked a router document a question on rc15 and the run's own
transcript said:

> This run finished at more than one Output and every answer is published,
> joined in the order they are drawn: "Ask back" (ask1), "Answer — …", …

The classifier's verdict was a single branch. Five answers were published.
Reproduced here with no model anywhere, and the reproduction found **two**
mechanisms rather than the one the ticket guessed at (it guessed the
conditional map fell back to "every declared branch"; it does not):

- `_router_for` fell through to the **first declared destination** when the
  verdict named a branch nobody had drawn an edge from. So one answer was
  published from a branch the verdict did not name — and the sentence
  reporting it called the router a *"Grader"* and said the answer
  *"shipped as-is"*.
- The steps hanging off the unwired branches had **no incoming edge at all**,
  so `plan.entry` wired each of them straight from `START`. They ran on every
  run, whatever the verdict said, and each published its own Output.

Both are fixed at the compiler seam, and both halves are asserted below —
a test that only pinned the first would still have watched four answers get
published.
"""

from __future__ import annotations

from typing import Any

from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import (
    ROUTE_CHECK_TYPE,
    WorkflowCompiler,
    run_health_from_state,
)

DESKS = [
    {"id": "b1", "name": "desk_one"},
    {"id": "b2", "name": "desk_two"},
    {"id": "b3", "name": "desk_three"},
    {"id": "b4", "name": "desk_four"},
]


def _edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


def _document(*, fallback_wired: bool = False, lenses: bool = False) -> dict[str, Any]:
    """input -> route.check with four desks, edges drawn on two of them.

    `lenses` adds the owner's shape: a step and an Output drawn for each
    *unwired* branch, joined to nothing, which is what a half-wired document
    looks like on the canvas.
    """
    nodes: list[dict[str, Any]] = [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {}},
        {
            "id": "r1",
            "type": ROUTE_CHECK_TYPE,
            "position": {"x": 200, "y": 0},
            "data": {"check": "pick_a_desk", "branches": DESKS},
        },
        {"id": "out_one", "type": "output.formatted", "position": {"x": 600, "y": 0}, "data": {}},
        {"id": "out_two", "type": "output.formatted", "position": {"x": 600, "y": 90}, "data": {}},
    ]
    edges = [
        _edge("in1", "text", "r1", "candidate"),
        _edge("r1", "branch:b1", "out_one", "result"),
        _edge("r1", "branch:b2", "out_two", "result"),
    ]
    if fallback_wired:
        nodes.append(
            {"id": "out_back", "type": "output.formatted", "position": {"x": 600, "y": 180}, "data": {}}
        )
        edges.append(_edge("r1", "fallback", "out_back", "result"))
    if lenses:
        for tag in ("three", "four"):
            nodes.append(
                {
                    "id": f"lens_{tag}",
                    "type": "function.format_report",
                    "position": {"x": 400, "y": 300},
                    "data": {},
                }
            )
            nodes.append(
                {
                    "id": f"out_{tag}",
                    "type": "output.formatted",
                    "position": {"x": 600, "y": 300},
                    "data": {},
                }
            )
            edges.append(_edge(f"lens_{tag}", "result", f"out_{tag}", "result"))
    return {"version": 2, "name": "single-choice-router", "nodes": nodes, "edges": edges}


def _run(document: dict[str, Any], verdict: str) -> dict[str, Any]:
    """The whole graph, with a package function standing in for the model.

    The defect is in the edge map, not in the model, so nothing here resolves
    one: `route.check` is `route.classifier`'s shape with a function where the
    judgement is.
    """
    runtime = NodeRuntime(functions={"function.pick_a_desk": lambda text: verdict})
    graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))
    return graph.invoke(
        {"question": "which desk?", "attempts": 0, "decisions": {}, "outputs": {}, "revisions": {}}
    )


def _published(final: dict[str, Any]) -> list[str]:
    return sorted(final.get("published") or {})


class TestAVerdictNamingAnUnwiredBranch:
    """The first mechanism: never the first destination."""

    def test_it_takes_the_declared_fallback_when_one_is_wired(self) -> None:
        final = _run(_document(fallback_wired=True), "desk_three")

        assert final["decisions"]["r1"] == "b3"
        assert _published(final) == ["out_back"]

    def test_it_stops_at_the_node_when_no_fallback_is_wired(self) -> None:
        """Not the first branch's Output, which is what used to happen."""
        final = _run(_document(), "desk_three")

        assert _published(final) == []
        assert "out_one" not in (final.get("outputs") or {})

    def test_the_developer_channel_names_the_node_and_the_branch(self) -> None:
        final = _run(_document(), "desk_three")
        said = " ".join(run_health_from_state(final).silent)

        assert "r1" in said
        assert "b3" in said

    def test_it_does_not_claim_an_answer_shipped(self) -> None:
        """The sentence used to end *"so the answer shipped as-is"*. None did."""
        final = _run(_document(), "desk_three")
        said = " ".join(run_health_from_state(final).silent)

        assert "shipped as-is" not in said

    def test_it_does_not_call_a_router_a_grader(self) -> None:
        final = _run(_document(), "desk_three")
        said = " ".join(run_health_from_state(final).silent)

        assert "Grader" not in said

    def test_a_wired_verdict_is_untouched(self) -> None:
        final = _run(_document(fallback_wired=True), "desk_two")

        assert _published(final) == ["out_two"]
        assert "unrouted" not in final or not final["unrouted"]


class TestTheOwnersTranscriptShape:
    """Five Outputs from one verdict. Neutral names, same shape."""

    def test_only_the_branch_the_verdict_named_publishes(self) -> None:
        final = _run(_document(fallback_wired=True, lenses=True), "desk_three")

        assert _published(final) == ["out_back"]

    def test_a_step_on_an_unwired_branch_does_not_run_from_start(self) -> None:
        final = _run(_document(fallback_wired=True, lenses=True), "desk_three")
        outputs = final.get("outputs") or {}

        assert "lens_three" not in outputs
        assert "lens_four" not in outputs

    def test_the_run_does_not_finish_at_more_than_one_output(self) -> None:
        final = _run(_document(fallback_wired=True, lenses=True), "desk_three")
        said = " ".join(run_health_from_state(final).silent)

        assert "more than one Output" not in said


class TestWhatStartsARun:
    def test_the_input_node_is_still_the_entry(self) -> None:
        plan = WorkflowCompiler().plan(_document(lenses=True))

        assert plan.entry == ["in1"]

    def test_a_node_the_preference_dropped_is_named(self) -> None:
        """Not scheduling it is the fix; not saying so would be the same defect.

        An advisory, not a warning: a half-wired canvas is what a canvas looks
        like mid-build, so this may never move VALID to INVALID.
        """
        plan = WorkflowCompiler().plan(_document(lenses=True))
        said = " ".join(plan.advisories)

        assert "lens_three" in said
        assert "lens_four" in said
        assert not [w for w in plan.warnings if "lens_three" in w]

    def test_a_document_with_nothing_else_to_start_it_still_runs(self) -> None:
        """A lone step on a fresh canvas is an entry, as it always was.

        The rule is *prefer* a node that can start a run — not a refusal.
        """
        document = {
            "version": 2,
            "name": "lone-step",
            "nodes": [
                {"id": "solo", "type": "agent.llm", "position": {"x": 0, "y": 0}, "data": {}}
            ],
            "edges": [],
        }

        assert WorkflowCompiler().plan(document).entry == ["solo"]
