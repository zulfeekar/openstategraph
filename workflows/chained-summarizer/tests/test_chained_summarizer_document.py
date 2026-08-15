"""The straight line, asserted.

Gallery example 1. What a test can settle here without spending a token is the
*shape* the recorded smoke expectation rests on: two agents in series, the
second reading the first's `result` over the `prompt` port, and nothing else on
the canvas — no branch, no cycle, no tool, no mount. Whether the second agent
actually shortens the first's prose is a model question, and a stub answering
it would be theatre.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.package_testing import (
    assert_document_shape,
    edges_of,
    load_document,
)

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def document() -> dict:
    return load_document(PACKAGE)


def test_the_baseline_every_package_shares(document: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(document)


def test_it_is_four_nodes_and_nothing_else(document: dict) -> None:
    assert [n["type"] for n in document["nodes"]] == [
        "input.text",
        "agent.llm",
        "agent.llm",
        "output.formatted",
    ]


def test_the_chain_is_a_straight_line(document: dict) -> None:
    assert edges_of(document) == {
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
