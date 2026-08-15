"""A loop that cannot succeed must still finish.

Gallery example 7. The exit is the attempt counter, never the verdict:
`_grader` computes `exhausted = attempts >= cap` *before* it routes and forces
`pass` at the ceiling. `GraphRecursionError` belongs to the superstep budget,
which this graph never approaches — two laps cost four supersteps.
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


def test_it_is_the_canonical_two_edge_cycle(document: dict) -> None:
    assert edges_of(document) == {
        ("in1", "text", "draft1", "prompt"),
        ("draft1", "result", "grader1", "candidate"),
        ("grader1", "revise", "draft1", "feedback"),
        ("grader1", "pass", "out1", "result"),
    }


def test_the_budget_lets_the_revise_edge_be_taken_exactly_once(document: dict) -> None:
    """The catalogue row says `maxAttempts: 1`. At 1 the grader force-passes the
    first draft and the cycle is drawn but never traversed — an example of a
    loop that never loops. At 2 the edge is taken once and the run still ends
    with `attempts == maxAttempts`, which is the property being asserted.
    Deliberate deviation; see AGENTS.md."""
    assert int(node_of(document, "grader1")["data"]["maxAttempts"]) == 2


def test_the_rubric_is_self_contradictory_on_purpose(document: dict) -> None:
    """If a candidate could satisfy it, the run would exit on a verdict and
    this example would be example 4 with a different question."""
    criteria = node_of(document, "grader1")["data"]["criteria"].lower()
    assert "exactly seven words" in criteria
    assert "forty words" in criteria
    assert "neither may be relaxed" in criteria


def test_the_drafter_is_told_to_keep_answering_anyway(document: dict) -> None:
    """A drafter that gives up on an impossible rubric produces an empty
    candidate, and `_grader` then replaces the answer with its own "I could not
    produce an answer" text — which would make this an example about the empty
    floor rather than about the counter."""
    prompt = node_of(document, "draft1")["data"]["systemPrompt"].lower()
    assert "cannot be true at the same time" in prompt


def test_the_grader_extends_rather_than_replaces_its_machinery(document: dict) -> None:
    assert node_of(document, "grader1")["data"]["rulesMode"] == "extend"
