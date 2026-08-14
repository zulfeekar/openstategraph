"""A loop is two edges. This is the gallery's reference for that sentence.

Gallery example 4. `grader.pass` → the output and `grader.revise` →
`agent.feedback`: the second edge is the cycle, and it is legal only because
`revise` is typed `feedback` — the `acyclic` rule returns early for exactly
that port type and for nothing else. A cycle also needs a conditional edge to
be able to stop, and the grader is it.
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
    # The catalogue asked for the bare `ollama:` prefix, on the belief that it
    # resolves to OLLAMA_CLOUD_MODEL. It does not — `resolve_model` returns any
    # truthy request verbatim, and `init_chat_model("ollama:")` fails with an
    # empty model name (gallery ticket 12). Until that lands, the pin is what
    # the three packages that already shipped use, and it keeps the gallery on
    # Ollama cloud on a machine where ANTHROPIC_API_KEY would otherwise win the
    # no-request fallback.
    assert document["settings"]["model"] == "ollama:gpt-oss:120b-cloud"


def test_the_cycle_is_exactly_two_nodes(document: dict) -> None:
    assert _edges(document) == {
        ("in1", "text", "draft1", "prompt"),
        ("draft1", "result", "grader1", "candidate"),
        ("grader1", "pass", "out1", "result"),
        ("grader1", "revise", "draft1", "feedback"),
    }


def test_the_loop_closes_on_the_only_ports_that_can_close_it(document: dict) -> None:
    closing = [e for e in document["edges"] if e["target"]["portId"] == "feedback"]
    assert len(closing) == 1
    assert closing[0]["source"]["portId"] == "revise"


def test_the_grader_can_ask_for_at_least_one_revision(document: dict) -> None:
    # `attempts` >= 1 in the recorded expectation needs a budget above zero.
    assert _node(document, "grader1")["data"]["maxAttempts"] >= 2


def test_the_grader_extends_rather_than_replaces_its_machinery(document: dict) -> None:
    # The output contract is the base's, not the author's — `rulesMode:
    # replace` on a grader is how a rubric silently loses its verdict shape.
    assert _node(document, "grader1")["data"]["rulesMode"] == "extend"


def test_the_criteria_are_checkable_in_two_sentences(document: dict) -> None:
    criteria = _node(document, "grader1")["data"]["criteria"]
    assert "two sentences" in criteria.lower()
