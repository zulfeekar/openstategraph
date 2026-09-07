"""Guarded Lookup — the policy is the document, so the document is the test.

Asserts the shape and the *asymmetry*, which is the thing this example
exists to teach: the same entity, `email`, is `pass` on one card and `redact`
on the other, and nothing but the position of the two cards says which is
which. If a future edit made both cards agree, this example would still run
and would have stopped demonstrating anything — so that is what these pin.

What they do not assert is the model's prose. Whether the agent phrases the
answer well is a model question; the guarantee this example makes is that no
address survives to the reader, and `test_guardrail_node.py` proves that
mechanism against a stub. The recorded live run is in AGENTS.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.package_testing import assert_document_shape, load_document, node_of, types_of

PACKAGE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def document() -> dict:
    return load_document(PACKAGE)


def test_the_baseline_every_package_shares(document: dict) -> None:
    assert_document_shape(document)


def test_it_guards_both_ends(document: dict) -> None:
    assert types_of(document).count("guard.policy") == 2


def test_the_same_entity_gets_opposite_answers_at_the_two_ends(document: dict) -> None:
    """The owner's requirement, as a property of the shipped document."""
    inbound = _strategies(node_of(document, "guard-in"))
    outbound = _strategies(node_of(document, "guard-out"))

    assert inbound["email"] == "pass"
    assert outbound["email"] == "redact"


def test_the_inbound_pass_is_what_makes_the_lookup_possible(document: dict) -> None:
    # `customer_lookup` matches on the exact address. Redact it inbound and
    # the tool finds nothing — which is why `pass` is a row somebody wrote
    # rather than a row nobody wrote.
    assert "tool.customer-lookup" in types_of(document)


def test_a_card_number_never_reaches_the_agent(document: dict) -> None:
    assert _strategies(node_of(document, "guard-in"))["credit_card"] == "block"


def test_the_refusal_has_somewhere_to_go(document: dict) -> None:
    """A blocked message takes a wire, which is the map's whole 'done when'."""
    blocked = [
        edge
        for edge in document["edges"]
        if edge["source"] == {"nodeId": "guard-in", "portId": "blocked"}
    ]
    assert [edge["target"]["nodeId"] for edge in blocked] == ["refused"]


def test_a_custom_pattern_is_stored_as_a_pattern_not_as_code(document: dict) -> None:
    # Phone numbers have no built-in detector, so this row carries a regex —
    # data with a published grammar, which is what keeps `workflow.json`
    # vendor-neutral. A stored callable would not survive its own file.
    phone = next(
        row
        for row in node_of(document, "guard-out")["data"]["policy"]
        if row["entity"] == "phone"
    )
    assert isinstance(phone["detector"], str) and phone["detector"]


def test_the_agent_is_told_to_use_the_tool_rather_than_its_memory(document: dict) -> None:
    prompt = node_of(document, "agent1")["data"]["systemPrompt"].lower()
    assert "never answer from memory" in prompt or "never invent" in prompt


def test_the_directory_is_fixture_data_and_says_so() -> None:
    # Six records with names, phone numbers and support links. They are the
    # Chinook sample database's invented customers, and the file has to say
    # so — an example that reads as a leak is a bad example even when it is
    # not one.
    source = (PACKAGE / "tools" / "directory.py").read_text(encoding="utf-8")
    assert "fictional" in source


def _strategies(node: dict) -> dict[str, str]:
    return {row["entity"]: row["strategy"] for row in node["data"]["policy"]}
