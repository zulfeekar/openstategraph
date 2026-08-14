"""The only cycle a person closes.

Gallery example 10. `human.approval.rejected` is a `feedback` output, so it
reaches `agent.feedback` exactly as a grader's `revise` does — the ports do not
know or care that the decision came from a person. It is also the only example
that interrupts mid-run, which is why it cannot be smoke-run from the CLI:
`openstategraph run` calls `workflow.ask(...)` and has no resume flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def document() -> dict:
    envelope = json.loads((PACKAGE / "workflow.json").read_text())
    assert envelope["version"] == 1
    document = envelope["document"]
    assert document["version"] == 3
    return document


def _node(document: dict, node_id: str) -> dict:
    return next(n for n in document["nodes"] if n["id"] == node_id)


def _edges(document: dict) -> set[tuple[str, str, str, str]]:
    return {
        (e["source"]["nodeId"], e["source"]["portId"], e["target"]["nodeId"], e["target"]["portId"])
        for e in document["edges"]
    }


def test_the_model_is_pinned_to_ollama_cloud(document: dict) -> None:
    assert document["settings"]["model"] == "ollama:gpt-oss:120b-cloud"


def test_the_person_closes_the_cycle(document: dict) -> None:
    assert _edges(document) == {
        ("in1", "text", "draft1", "prompt"),
        ("draft1", "result", "gate1", "candidate"),
        ("gate1", "rejected", "draft1", "feedback"),
        ("gate1", "approved", "out1", "result"),
    }


def test_a_rejection_is_the_same_port_type_a_grader_would_have_used(
    document: dict,
) -> None:
    """`route.grader.revise` and `human.approval.rejected` are the only two
    feedback outputs there are. Swapping the gate for a grader here would be an
    edit of one node and no edges — which is the claim the example makes."""
    closing = [e for e in document["edges"] if e["target"]["portId"] == "feedback"]
    assert len(closing) == 1
    assert closing[0]["source"] == {"nodeId": "gate1", "portId": "rejected"}
    assert _node(document, "gate1")["type"] == "human.approval"


def test_nothing_reaches_the_output_except_an_approval(document: dict) -> None:
    """The gate is a gate: there is no second path to `out1`."""
    into_out = [e for e in document["edges"] if e["target"]["nodeId"] == "out1"]
    assert len(into_out) == 1
    assert into_out[0]["source"]["portId"] == "approved"


def test_the_gate_asks_a_question_a_person_can_answer(document: dict) -> None:
    """`message` is the whole interrupt payload besides the candidate — it is
    the only place to say what approving *means*."""
    message = _node(document, "gate1")["data"]["message"]
    assert "Approve" in message and "reject" in message


def test_the_drafter_treats_a_rejection_as_a_specification(document: dict) -> None:
    """A rejection carries optional feedback, and `_agent` only reads it when
    the rejecting node's decision says so. A drafter that ignores it turns the
    loop into an infinite one bounded only by the superstep budget."""
    prompt = _node(document, "draft1")["data"]["systemPrompt"].lower()
    assert "feedback" in prompt
    assert "treat it as the specification" in prompt


def test_there_is_no_grader_anywhere(document: dict) -> None:
    """Example 19 is where the gate and the grader appear together. Here the
    person is the only judge, so the pause is unambiguous."""
    assert "route.grader" not in {n["type"] for n in document["nodes"]}
