"""Heterogeneous workers: the supervisor labels, `Send` dispatches, one worker
catches whatever went unlabelled.

Gallery example 5, and the contrast with example 2 is the reason both exist:
there the same role runs N times, here N *different* roles are wired and the
plan decides which one each subtask goes to. The dispatch key is the worker
node's **title**, slugified — not its id and not its `role` — so two workers
whose titles slugify the same are unreachable by construction. The compiler
refuses that document; this test refuses it earlier and says why.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.package_testing import (
    assert_document_shape,
    load_document,
    node_of,
)

from openstategraph.abc.orchestrator import archetype_key

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def document() -> dict:
    return load_document(PACKAGE)


def _workers(document: dict) -> list[dict]:
    return [n for n in document["nodes"] if n["type"] == "orchestrate.worker"]


def test_the_baseline_every_package_shares(document: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(document)


def test_two_worker_archetypes_with_distinct_dispatch_keys(document: dict) -> None:
    workers = _workers(document)
    assert len(workers) == 2
    keys = [archetype_key(w) for w in workers]
    assert all(keys), "an untitled worker falls back to its id — title them"
    assert len(set(keys)) == 2, "two archetypes sharing a key cannot both be reached"


def test_exactly_one_worker_is_the_default(document: dict) -> None:
    # The degradation is part of the demo: an unlabelled subtask must land
    # somewhere, and `default` is what names where.
    assert [bool(w["data"].get("default")) for w in _workers(document)].count(True) == 1


def test_every_worker_describes_its_role(document: dict) -> None:
    # `role` is what the planning prompt shows the model as the archetype's
    # description — and, since gallery ticket 16, context in that worker's own
    # system prompt. Without it the supervisor labels blind *and* the worker
    # has nothing telling it what kind of answer it owes.
    assert all(w["data"].get("role") for w in _workers(document))


def test_the_supervisor_writes_planning_rules_not_only_dispatch_rules(document: dict) -> None:
    """Gallery ticket 15: `rules` reached the archetype-labelling call alone,
    so the planning prose on this card changed nothing and the catalogue's
    brief — no numbered list, no semicolon, no "and" — planned one subtask.
    Rules now drive a planning call; emptying this field puts the regex back."""
    rules = node_of(document, "lead1")["data"].get("rules") or ""
    assert rules.strip()
    assert "subtask" in rules.lower()


def test_both_workers_are_dispatched_and_both_join(document: dict) -> None:
    worker_ids = {w["id"] for w in _workers(document)}
    dispatched = {
        e["target"]["nodeId"]
        for e in document["edges"]
        if e["source"]["nodeId"] == "lead1" and e["source"]["portId"] == "workers"
    }
    joined = {
        e["source"]["nodeId"]
        for e in document["edges"]
        if e["target"]["nodeId"] == "join1" and e["target"]["portId"] == "candidate"
    }
    assert dispatched == worker_ids
    assert joined == worker_ids


def test_the_join_fans_in_because_candidate_is_the_one_unlimited_input(document: dict) -> None:
    incoming = [e for e in document["edges"] if e["target"]["nodeId"] == "join1"]
    assert len(incoming) == 2
    assert {e["target"]["portId"] for e in incoming} == {"candidate"}


def test_the_supervisor_may_plan_more_than_two_subtasks(document: dict) -> None:
    assert node_of(document, "lead1")["data"]["maxSubtasks"] >= 2
