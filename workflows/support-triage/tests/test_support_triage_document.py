"""The long control chain — classify, answer, grade, gate — and where it stops.

Gallery example 19. Four control molecules in one graph, and the two things
that graph reveals are both about what the vocabulary cannot express:

- **The grader cannot send it back.** `agent.feedback` is `maxConnections: 1`,
  so a `revise` edge from one grader onto three branch agents would have to
  pick one — and a technical failure routed into the billing desk is worse than
  no loop at all. So the grader has a `pass` edge and nothing else, and this
  file pins what the compiler then does with a `revise` verdict.
- **The rejection is not a result.** `human.approval.rejected` is a `feedback`
  output, and `output.formatted.result` accepts only `result`/`text`. A
  "rejected sink" therefore cannot be an output node; it is an agent that turns
  the reviewer's note into an internal record, and *that* reaches an output.

Both are asserted from the compiled plan, not from prose. No model is called;
the approve and reject paths were driven through the HTTP API and are recorded
in `AGENTS.md`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def doc() -> dict:
    envelope = json.loads((PACKAGE / "workflow.json").read_text())
    assert envelope["version"] == 1
    document = envelope["document"]
    assert document["version"] == 3
    return document


@pytest.fixture(scope="module")
def plan(doc: dict):
    return WorkflowCompiler().plan(doc)


def test_the_model_is_pinned_to_ollama_cloud(doc: dict) -> None:
    assert doc["settings"]["model"] == "ollama:gpt-oss:120b-cloud"


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


def test_it_compiles_without_a_warning(plan) -> None:
    assert plan.warnings == []


def test_the_run_has_two_ends(plan) -> None:
    """Sent and held are different outcomes and must be different exits."""
    assert sorted(plan.exits) == ["out-held", "out-sent"]


class TestTheGraderCannotSendItBack:
    def test_the_grader_has_only_a_pass_edge(self, plan) -> None:
        assert plan.conditional["grader1"] == {"pass": "gate1"}

    def test_a_revise_verdict_routes_to_the_gate_anyway(self, plan) -> None:
        """The mechanism, pinned rather than assumed.

        `_router_for` falls back to the first declared destination when the
        recorded decision names no wired branch. Here that is benign and even
        wanted — the person still sees the draft — but it is a *fallback doing
        semantic work*, and the same mechanism elsewhere silently ships an
        answer a grader rejected. Gallery ticket 31.
        """
        route = WorkflowCompiler._router_for("grader1", plan.conditional["grader1"])
        assert route({"decisions": {"grader1": "revise"}}) == "pass"

    def test_no_desk_agent_has_a_feedback_edge(self, doc: dict) -> None:
        """The reason there is no revise edge, stated as a fact about the file.

        If one is ever added, it lands on exactly one of three desks and this
        test is where the argument for that choice has to be made.
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
