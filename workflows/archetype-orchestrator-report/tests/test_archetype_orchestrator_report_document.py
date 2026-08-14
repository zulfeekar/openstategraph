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

import json
from pathlib import Path

import pytest

from openstategraph.abc.orchestrator import archetype_key

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


def _workers(document: dict) -> list[dict]:
    return [n for n in document["nodes"] if n["type"] == "orchestrate.worker"]


def test_the_model_is_pinned_to_ollama_cloud(document: dict) -> None:
    # The catalogue asked for the bare `ollama:` prefix, on the belief that it
    # resolves to OLLAMA_CLOUD_MODEL. It does not — `resolve_model` returns any
    # truthy request verbatim, and `init_chat_model("ollama:")` fails with an
    # empty model name (gallery ticket 12). Until that lands, the pin is what
    # the three packages that already shipped use, and it keeps the gallery on
    # Ollama cloud on a machine where ANTHROPIC_API_KEY would otherwise win the
    # no-request fallback.
    assert document["settings"]["model"] == "ollama:gpt-oss:120b-cloud"


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
    # description. Without it the supervisor is labelling blind.
    assert all(w["data"].get("role") for w in _workers(document))


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
    assert _node(document, "lead1")["data"]["maxSubtasks"] >= 2
