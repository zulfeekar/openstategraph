"""One worker archetype, run N times in parallel, joined deterministically.

Gallery example 2. The join is `function.format_report`, which reads
`state["worker_results"]` keyed by the subtask ids the supervisor planned — so
the smoke expectation ("a `# Report` with one `###` section per subtask, in
task-id order") is half a document fact and half a runtime fact. The document
half is asserted here; the runtime half is the recorded smoke answer.
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


def test_exactly_one_worker_archetype(document: dict) -> None:
    # The contrast with example 5 is the whole point: same role, run N times.
    workers = [n for n in document["nodes"] if n["type"] == "orchestrate.worker"]
    assert len(workers) == 1
    assert workers[0]["data"]["default"] is True


def test_the_fan_out_and_the_join(document: dict) -> None:
    assert edges_of(document) == {
        ("in1", "text", "lead1", "instruction"),
        ("lead1", "workers", "worker1", "dispatch"),
        ("worker1", "result", "join1", "candidate"),
        ("join1", "report", "out1", "result"),
    }


def test_there_is_no_grader_and_therefore_no_cycle(document: dict) -> None:
    assert not any(n["type"] == "route.grader" for n in document["nodes"])
    assert not any(e["target"]["portId"] == "feedback" for e in document["edges"])


def test_the_smoke_question_can_produce_two_subtasks(document: dict) -> None:
    # "two arguments for and against daily standups" → two sections. A cap
    # below 2 would make the recorded expectation unreachable by construction.
    assert node_of(document, "lead1")["data"]["maxSubtasks"] >= 2


def test_the_supervisor_carries_no_rules_because_they_would_be_inert(document: dict) -> None:
    # `Orchestrator.split` is a regex over numbered lists, semicolons and the
    # literal word "and" — the decomposition is deterministic and no prose can
    # steer it. `rules` shapes only the archetype-labelling call, and with one
    # archetype wired `label()` short-circuits before making it. So a rules
    # string here would read like a planning instruction and change nothing;
    # AGENTS.md says so, and this keeps a future edit honest (gallery ticket 15).
    assert not node_of(document, "lead1")["data"].get("rules")


def test_the_report_title_is_authored(document: dict) -> None:
    # `reportTitle`, not `title` — the key the runtime actually reads.
    assert node_of(document, "join1")["data"]["reportTitle"]
