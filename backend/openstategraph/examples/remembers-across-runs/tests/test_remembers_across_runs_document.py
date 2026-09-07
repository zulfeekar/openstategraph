"""One ledger, many runs — checked without calling a model.

Gallery example 23, and the one that demonstrates `memory.segment`
(install-experience ticket 17). What a document can assert about a tollbooth is
narrow and worth pinning exactly:

- **the wire.** The segment sits *between* the input and the agent, on the
  straight line, because that position is the whole mechanism — a memory node
  wired off to one side would record nothing that flows.
- **the ledger's identity.** A segment name, written in the document, because
  the name is what makes several positions one ledger and what makes run 2 read
  run 1.
- **the retention.** A number, not a blank, so a copied example does not grow
  without bound in somebody's Store months later.

Whether the model *uses* what it was handed is what the two-run smoke and its
recording are for. Nothing here calls a model or opens a Store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.memory_segment import parse_retention
from openstategraph.package_testing import assert_document_shape, load_document

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def doc() -> dict:
    return load_document(PACKAGE)


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free plan —
    `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_it_is_the_straight_line_with_one_tollbooth_on_it(doc: dict) -> None:
    assert [node["type"] for node in doc["nodes"]] == [
        "input.text",
        "memory.segment",
        "agent.llm",
        "output.formatted",
    ]


def test_the_segment_is_wired_between_the_question_and_the_agent(doc: dict) -> None:
    """Position is the mechanism. A tollbooth nothing crosses records nothing,
    and it would still compile, still run, and still look right on the canvas."""
    wires = {
        (edge["source"]["nodeId"], edge["target"]["nodeId"]): (
            edge["source"]["portId"],
            edge["target"]["portId"],
        )
        for edge in doc["edges"]
    }
    assert wires[("in1", "mem1")] == ("text", "crossing")
    assert wires[("mem1", "answer1")] == ("onward", "prompt")


def test_the_ledger_is_named_in_the_document(doc: dict) -> None:
    """The name is the ledger. An unnamed segment records nothing and says so
    at run time, which is a worse place to find out than here."""
    segment = next(node for node in doc["nodes"] if node["type"] == "memory.segment")
    assert segment["data"]["segment"].strip() == "what-you-told-me"


def test_the_shipped_retention_is_bounded(doc: dict) -> None:
    """Blank is legal on the card and means unbounded. A *shipped* example
    copied into somebody's own root is the wrong place to demonstrate that:
    the Store it grows in is theirs, and nothing would tell them."""
    segment = next(node for node in doc["nodes"] if node["type"] == "memory.segment")
    assert parse_retention(segment["data"]["retention"]) == 20


def test_the_agent_is_told_what_to_do_with_an_empty_segment(doc: dict) -> None:
    """The first run of a copied example has an empty ledger. An agent that
    guesses instead of saying it has not been told turns the one run that
    proves nothing into a run that looks like it proved something."""
    agent = next(node for node in doc["nodes"] if node["type"] == "agent.llm")
    prompt = agent["data"]["systemPrompt"].lower()
    assert "nothing has crossed yet" in prompt
    assert "guess" in prompt


def test_it_names_no_provider(doc: dict) -> None:
    """A copied example inherits the instance default, which is what makes
    `pip install 'openstategraph[anthropic]'` mean Anthropic here."""
    assert "model" not in doc.get("settings", {})
    assert not any("model" in (node.get("data") or {}) for node in doc["nodes"])


def test_the_envelope_is_a_draft_like_every_other_example() -> None:
    envelope = json.loads((PACKAGE / "workflow.json").read_text())
    assert envelope["published"] is False
