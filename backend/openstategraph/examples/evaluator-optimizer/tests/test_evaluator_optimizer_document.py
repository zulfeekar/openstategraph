"""A loop is two edges. This is the gallery's reference for that sentence.

Gallery example 4. `grader.pass` → the output and `grader.revise` →
`agent.feedback`: the second edge is the cycle, and it is legal only because
`revise` is typed `feedback` — the `acyclic` rule returns early for exactly
that port type and for nothing else. A cycle also needs a conditional edge to
be able to stop, and the grader is it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.package_testing import (
    assert_document_shape,
    edges_of,
    load_document,
    node_of,
)

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def document() -> dict:
    return load_document(PACKAGE)


def test_the_baseline_every_package_shares(document: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(document)


def test_the_cycle_is_exactly_two_nodes(document: dict) -> None:
    assert edges_of(document) == {
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
    assert node_of(document, "grader1")["data"]["maxAttempts"] >= 2


def test_the_grader_extends_rather_than_replaces_its_machinery(document: dict) -> None:
    # The output contract is the base's, not the author's — `rulesMode:
    # replace` on a grader is how a rubric silently loses its verdict shape.
    assert node_of(document, "grader1")["data"]["rulesMode"] == "extend"


def test_the_criteria_are_checkable_in_two_sentences(document: dict) -> None:
    criteria = node_of(document, "grader1")["data"]["criteria"]
    assert "two sentences" in criteria.lower()
