"""The long control chain — classify, answer, grade, gate — and where it stops.

Gallery example 19. Four control molecules in one graph, and two things that
graph used to reveal about what the vocabulary could not express:

- **The grader can send it back, through the router.** `agent.feedback` is
  `maxConnections: 1`, so a `revise` edge from one grader onto three branch
  agents would have to pick one — and a technical failure routed into the
  billing desk is worse than no loop at all. `workflow-gallery` 48 settled
  this: the edge lands on the *router* instead, which re-dispatches to
  whichever branch its own last decision named rather than reclassifying, so
  the correction always reaches the desk that actually wrote the rejected
  draft. `docs/decisions/router-feedback-input.md` is the decision;
  `test_a_router_re_dispatches_a_revision.py` (backend) is the mechanism,
  pinned against a live compiled run. This file pins the *shape*: which edge
  is wired, and where it lands.
- **The rejection is not a result.** `human.approval.rejected` is a `feedback`
  output, and `output.formatted.result` accepts only `result`/`text`. A
  "rejected sink" therefore cannot be an output node; it is an agent that turns
  the reviewer's note into an internal record, and *that* reaches an output.

Both are asserted from the compiled plan, not from prose. No model is called;
the approve and reject paths were driven through the HTTP API and are recorded
in `AGENTS.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.package_testing import (
    assert_document_shape,
    load_document,
)

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


@pytest.fixture(scope="module")
def plan(doc: dict):
    return WorkflowCompiler().plan(doc)


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_every_control_molecule_is_present(doc: dict) -> None:
    """The row's own claim, as a set: classify, answer, grade, gate."""
    types = [n["type"] for n in doc["nodes"]]
    assert types.count("route.classifier") == 1
    assert types.count("route.grader") == 1
    assert types.count("human.approval") == 1
    assert types.count("agent.llm") == 4, "three desks and the held-ticket note"


def test_three_desks_are_three_exclusive_branches(plan) -> None:
    assert plan.conditional["router1"] == {
        "b-billing": "a-billing",
        "b-technical": "a-technical",
        "b-account": "a-account",
    }


def test_the_run_has_two_ends(plan) -> None:
    """Sent and held are different outcomes and must be different exits."""
    assert sorted(plan.exits) == ["out-held", "out-sent"]


class TestTheGraderSendsItBackThroughTheRouter:
    def test_the_grader_has_a_pass_edge_and_a_revise_edge(self, plan) -> None:
        assert plan.conditional["grader1"] == {"pass": "gate1", "revise": "router1"}

    def test_the_revise_edge_lands_on_the_router_not_a_desk(self, doc: dict) -> None:
        """`workflow-gallery` 48's mechanism, stated as a fact about the file:
        the revise edge names the router's `feedback` port, never a desk's.
        """
        revise_edge = next(
            e
            for e in doc["edges"]
            if e["source"] == {"nodeId": "grader1", "portId": "revise"}
        )
        assert revise_edge["target"] == {"nodeId": "router1", "portId": "feedback"}

    def test_no_desk_agent_has_a_feedback_edge(self, doc: dict) -> None:
        """A desk's own `feedback` port is still never wired directly — the
        correction reaches it by re-dispatch (the compiler traces the
        grader's revise edge through the router relay), not by a second edge
        onto one arbitrarily chosen desk. Choosing one desk to wire directly
        is exactly the shape `workflow-gallery` 48 rejected.
        """
        desks = {"a-billing", "a-technical", "a-account"}
        feedback_targets = {
            e["target"]["nodeId"]
            for e in doc["edges"]
            if e["target"]["portId"] == "feedback"
        }
        assert not (feedback_targets & desks)


class TestNothingReachesACustomerWithoutTheGate:
    def test_the_gate_stands_between_the_grader_and_the_output(self, plan) -> None:
        assert plan.conditional["gate1"] == {"approved": "out-sent", "rejected": "hold1"}

    def test_no_desk_reaches_an_output_directly(self, doc: dict) -> None:
        outputs = {n["id"] for n in doc["nodes"] if n["type"] == "output.formatted"}
        desks = {"a-billing", "a-technical", "a-account"}
        for edge in doc["edges"]:
            assert not (
                edge["source"]["nodeId"] in desks and edge["target"]["nodeId"] in outputs
            ), "a desk reply reaching an output without passing the gate"

    def test_the_rejected_sink_is_an_agent_not_an_output(self, doc: dict) -> None:
        """`rejected` is a `feedback` port; an output accepts `result`/`text`.

        So the sink cannot be an output node, and the shape that works is an
        agent whose only incoming edge is the rejection — it answers the
        original question with the reviewer's note as its feedback, which is
        exactly an internal record of why the ticket was held.
        """
        sink = next(n for n in doc["nodes"] if n["id"] == "hold1")
        assert sink["type"] == "agent.llm"
        incoming = [e for e in doc["edges"] if e["target"]["nodeId"] == "hold1"]
        assert len(incoming) == 1
        assert incoming[0]["target"]["portId"] == "feedback"
        assert incoming[0]["source"]["portId"] == "rejected"
