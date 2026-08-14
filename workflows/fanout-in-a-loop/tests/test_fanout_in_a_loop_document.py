"""A `Send` inside a cycle, and the arithmetic that makes supersteps ≠ laps.

Gallery example 9. `orchestrate.supervisor.feedback` is one of only two
feedback inputs in the whole catalogue and this is the example that uses it.
The measured cost is four supersteps per lap (planner, fan-out, join, grader),
which is the number `recursion_limit` counts and "max iterations" does not.
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


def test_the_cycle_contains_the_fan_out(document: dict) -> None:
    assert _edges(document) == {
        ("in1", "text", "lead1", "instruction"),
        ("lead1", "workers", "worker1", "dispatch"),
        ("worker1", "result", "join1", "candidate"),
        ("join1", "report", "grader1", "candidate"),
        ("grader1", "revise", "lead1", "feedback"),
        ("grader1", "pass", "out1", "result"),
    }


def test_the_loop_closes_on_the_supervisor_not_on_an_agent(document: dict) -> None:
    """`orchestrate.supervisor.feedback` and `agent.feedback` are the only two
    feedback inputs that exist. This is the example for the first one."""
    closing = [e for e in document["edges"] if e["target"]["portId"] == "feedback"]
    assert len(closing) == 1
    assert closing[0]["target"]["nodeId"] == "lead1"
    assert _node(document, "lead1")["type"] == "orchestrate.supervisor"


def test_the_join_is_inside_the_cycle(document: dict) -> None:
    """A grader placed before the join would judge one worker's fragment. The
    thing being judged is the report."""
    graded = next(e for e in document["edges"] if e["target"]["nodeId"] == "grader1")
    assert graded["source"]["nodeId"] == "join1"
    assert _node(document, "join1")["type"] == "function.format_report"


def test_there_is_exactly_one_worker_and_it_is_the_default(document: dict) -> None:
    """Heterogeneous archetypes are example 5's job. One worker here keeps the
    lap cost a fixed four supersteps and the run about the cycle."""
    workers = [n for n in document["nodes"] if n["type"] == "orchestrate.worker"]
    assert len(workers) == 1
    assert workers[0]["data"]["default"] is True


def test_the_plan_is_bounded_below_the_step_budget(document: dict) -> None:
    """`maxSubtasks` × laps is what fills a superstep, and the default
    recursion limit is 50. Three subtasks over three laps is 14 supersteps."""
    assert int(_node(document, "lead1")["data"]["maxSubtasks"]) == 3
    assert int(_node(document, "grader1")["data"]["maxAttempts"]) == 3


def test_the_grader_names_the_section_it_rejects(document: dict) -> None:
    """The supervisor cannot re-plan (gallery ticket 23) — the split is
    deterministic on an unchanged instruction — so the only thing feedback can
    move is what a worker writes. Feedback that does not name a task id cannot
    even do that."""
    criteria = _node(document, "grader1")["data"]["criteria"].lower()
    assert "task id" in criteria
    assert "###" in _node(document, "grader1")["data"]["criteria"]
    assert _node(document, "grader1")["data"]["rulesMode"] == "extend"


def test_the_report_is_titled_so_the_join_is_recognisable(document: dict) -> None:
    """`reportTitle`, not `title` — the TS field schema's spelling, and a
    document that used the other one fell through to the default silently."""
    assert _node(document, "join1")["data"]["reportTitle"] == "Deployment comparison"
