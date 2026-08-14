"""The straight line, asserted.

Gallery example 1. What a test can settle here without spending a token is the
*shape* the recorded smoke expectation rests on: two agents in series, the
second reading the first's `result` over the `prompt` port, and nothing else on
the canvas — no branch, no cycle, no tool, no mount. Whether the second agent
actually shortens the first's prose is a model question, and a stub answering
it would be theatre.
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


def _edges(document: dict) -> set[tuple[str, str, str, str]]:
    return {
        (e["source"]["nodeId"], e["source"]["portId"], e["target"]["nodeId"], e["target"]["portId"])
        for e in document["edges"]
    }


def test_the_model_is_pinned_to_ollama_cloud(document: dict) -> None:
    # Colon form at the workflow level (a node's own `data.model` is the
    # frontend's slash form — two spellings, one seam).
    #
    # The catalogue asked for the bare `ollama:` prefix, on the belief that it
    # resolves to OLLAMA_CLOUD_MODEL. It does not — `resolve_model` returns any
    # truthy request verbatim, and `init_chat_model("ollama:")` fails with an
    # empty model name (gallery ticket 12). Until that lands, the pin is what
    # the three packages that already shipped use, and it keeps the gallery on
    # Ollama cloud on a machine where ANTHROPIC_API_KEY would otherwise win the
    # no-request fallback.
    assert document["settings"]["model"] == "ollama:gpt-oss:120b-cloud"


def test_it_is_four_nodes_and_nothing_else(document: dict) -> None:
    assert [n["type"] for n in document["nodes"]] == [
        "input.text",
        "agent.llm",
        "agent.llm",
        "output.formatted",
    ]


def test_the_chain_is_a_straight_line(document: dict) -> None:
    assert _edges(document) == {
        ("in1", "text", "summarise1", "prompt"),
        ("summarise1", "result", "shorten1", "prompt"),
        ("shorten1", "result", "out1", "result"),
    }


def test_the_second_agent_reads_the_first_over_the_prompt_port(document: dict) -> None:
    # Port-level widening: `agent.prompt` is typed `text` and accepts `result`.
    # This is the one mechanism the example exists to exercise.
    chained = [
        e
        for e in document["edges"]
        if e["source"]["portId"] == "result" and e["target"]["portId"] == "prompt"
    ]
    assert len(chained) == 1


def test_no_cycle_no_tool_no_mount(document: dict) -> None:
    types = {n["type"] for n in document["nodes"]}
    assert not any(t.startswith(("tool.", "workflow.", "route.")) for t in types)
    assert not any(e["target"]["portId"] == "feedback" for e in document["edges"])
