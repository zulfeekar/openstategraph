"""One worker archetype, run N times in parallel, joined deterministically.

Gallery example 2. The join is `function.format_report`, which reads
`state["worker_results"]` keyed by the subtask ids the supervisor planned — so
the smoke expectation ("a `# Report` with one `###` section per subtask, in
task-id order") is half a document fact and half a runtime fact. The document
half is asserted here; the runtime half is the recorded smoke answer.
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


def test_exactly_one_worker_archetype(document: dict) -> None:
    # The contrast with example 5 is the whole point: same role, run N times.
    workers = [n for n in document["nodes"] if n["type"] == "orchestrate.worker"]
    assert len(workers) == 1
    assert workers[0]["data"]["default"] is True


def test_the_fan_out_and_the_join(document: dict) -> None:
    assert _edges(document) == {
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
    assert _node(document, "lead1")["data"]["maxSubtasks"] >= 2


def test_the_supervisor_carries_no_rules_because_they_would_be_inert(document: dict) -> None:
    # `Orchestrator.split` is a regex over numbered lists, semicolons and the
    # literal word "and" — the decomposition is deterministic and no prose can
    # steer it. `rules` shapes only the archetype-labelling call, and with one
    # archetype wired `label()` short-circuits before making it. So a rules
    # string here would read like a planning instruction and change nothing;
    # AGENTS.md says so, and this keeps a future edit honest (gallery ticket 15).
    assert not _node(document, "lead1")["data"].get("rules")


def test_the_report_title_is_authored(document: dict) -> None:
    # `reportTitle`, not `title` — the key the runtime actually reads.
    assert _node(document, "join1")["data"]["reportTitle"]
