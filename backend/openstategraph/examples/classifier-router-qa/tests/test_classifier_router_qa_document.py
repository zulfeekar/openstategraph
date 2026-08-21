"""Three mutually exclusive terminal branches — and three outputs, not one.

Gallery example 3. The interesting assertion is the last one.
`output.formatted.result` is an input whose `maxConnections` is 1: a document
converging two exclusive branches onto one output loads and compiles, but the
capacity rule makes *drawing* the second edge replace the first, so nobody can
redraw it. Every gallery example therefore gives each exclusive branch its own
output — and this test is what stops that decision from quietly rotting.

The shipped `routed-qa` template used to be the counter-example; gallery
ticket 13 gave it a second output. The repository-wide sweep that keeps every
shipped document redrawable is
`src/core/validation/shippedDocumentsSurviveRedrawing.test.ts`.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from openstategraph.package_testing import (
    assert_document_shape,
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


def test_three_branches_each_with_a_stable_id(document: dict) -> None:
    branches = node_of(document, "router1")["data"]["branches"]
    assert len(branches) == 3
    assert all(b["id"] and b["name"] for b in branches)
    assert len({b["id"] for b in branches}) == 3


def test_the_fallback_names_a_declared_branch(document: dict) -> None:
    router = node_of(document, "router1")["data"]
    assert router["fallback"] in {b["name"] for b in router["branches"]}


def test_every_branch_port_reaches_its_own_agent(document: dict) -> None:
    branch_ids = [b["id"] for b in node_of(document, "router1")["data"]["branches"]]
    wired = {
        e["source"]["portId"]: e["target"]["nodeId"]
        for e in document["edges"]
        if e["source"]["nodeId"] == "router1"
    }
    assert set(wired) == {f"branch:{bid}" for bid in branch_ids}
    assert len(set(wired.values())) == 3, "each branch must have its own agent"


def test_no_output_takes_more_than_one_edge(document: dict) -> None:
    outputs = {n["id"] for n in document["nodes"] if n["type"] == "output.formatted"}
    assert len(outputs) == 3
    incoming = Counter(e["target"]["nodeId"] for e in document["edges"])
    assert all(incoming[node_id] == 1 for node_id in outputs)


def test_there_is_no_grader_and_no_loop(document: dict) -> None:
    assert not any(n["type"] == "route.grader" for n in document["nodes"])
    assert not any(e["target"]["portId"] == "feedback" for e in document["edges"])
