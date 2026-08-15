"""Two cycles in series, and the reason they cannot be two cycles in parallel.

Gallery example 6. `agent.feedback` is `maxConnections: 1`, so two rubrics over
one drafter is not a drawable shape — two graders means two drafters. What is
mechanical about that claim is checkable here; what is not (the second rubric
actually holding) is recorded in `AGENTS.md` against a real run.
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


def test_there_are_two_cycles_and_they_are_in_series(document: dict) -> None:
    assert edges_of(document) == {
        ("in1", "text", "draft1", "prompt"),
        ("draft1", "result", "grader1", "candidate"),
        ("grader1", "revise", "draft1", "feedback"),
        ("grader1", "pass", "polish1", "prompt"),
        ("polish1", "result", "grader2", "candidate"),
        ("grader2", "revise", "polish1", "feedback"),
        ("grader2", "pass", "out1", "result"),
    }


def test_each_grader_closes_onto_its_own_drafter(document: dict) -> None:
    """The shape the `maxConnections: 1` feedback port forces. Two revise edges
    onto one agent would not stack — the capacity rule swaps them — so a second
    rubric buys a second drafter or nothing."""
    closing = {
        (e["source"]["nodeId"], e["target"]["nodeId"])
        for e in document["edges"]
        if e["target"]["portId"] == "feedback"
    }
    assert closing == {("grader1", "draft1"), ("grader2", "polish1")}


def test_no_agent_receives_more_than_one_feedback_edge(document: dict) -> None:
    targets = [e["target"]["nodeId"] for e in document["edges"] if e["target"]["portId"] == "feedback"]
    assert len(targets) == len(set(targets))


def test_the_second_ceiling_clears_what_the_first_stage_spends(document: dict) -> None:
    """`attempts` is ONE counter for the whole graph (`RunState.attempts`,
    reducer MAX), incremented by every model-driven node. So these two numbers
    are two ceilings on one count, not two budgets — and the second must exceed
    the first, or `grader2` force-passes the first draft it ever sees. Gallery
    ticket 21; delete this test when that lands, not before."""
    first = int(node_of(document, "grader1")["data"]["maxAttempts"])
    second = int(node_of(document, "grader2")["data"]["maxAttempts"])
    assert second > first


def test_both_graders_extend_rather_than_replace_their_machinery(document: dict) -> None:
    for grader in ("grader1", "grader2"):
        assert node_of(document, grader)["data"]["rulesMode"] == "extend"


def test_the_two_rubrics_judge_different_things(document: dict) -> None:
    """Two cycles with one rubric between them would be one cycle drawn twice."""
    first = node_of(document, "grader1")["data"]["criteria"].lower()
    second = node_of(document, "grader2")["data"]["criteria"].lower()
    assert "one line" in first and "past-tense" in first
    assert "two sentences" in second and "bug" in second
    assert first != second
