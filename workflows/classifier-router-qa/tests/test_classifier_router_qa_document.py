"""Three mutually exclusive terminal branches — and three outputs, not one.

Gallery example 3. The interesting assertion is the last one. The shipped
`routed-qa` template converges two branches onto a single
`output.formatted.result`, an input whose `maxConnections` is 1: the document
loads and compiles, but the capacity rule makes *drawing* the second edge
replace the first, so nobody can redraw the template the scaffolder ships.
Every gallery example therefore gives each exclusive branch its own output —
and this test is what stops that decision from quietly rotting.
"""

from __future__ import annotations

import json
from collections import Counter
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


def test_the_model_is_pinned_to_ollama_cloud(document: dict) -> None:
    # The catalogue asked for the bare `ollama:` prefix, on the belief that it
    # resolves to OLLAMA_CLOUD_MODEL. It does not — `resolve_model` returns any
    # truthy request verbatim, and `init_chat_model("ollama:")` fails with an
    # empty model name (gallery ticket 12). Until that lands, the pin is what
    # the three packages that already shipped use, and it keeps the gallery on
    # Ollama cloud on a machine where ANTHROPIC_API_KEY would otherwise win the
    # no-request fallback.
    assert document["settings"]["model"] == "ollama:gpt-oss:120b-cloud"


def test_three_branches_each_with_a_stable_id(document: dict) -> None:
    branches = _node(document, "router1")["data"]["branches"]
    assert len(branches) == 3
    assert all(b["id"] and b["name"] for b in branches)
    assert len({b["id"] for b in branches}) == 3


def test_the_fallback_names_a_declared_branch(document: dict) -> None:
    router = _node(document, "router1")["data"]
    assert router["fallback"] in {b["name"] for b in router["branches"]}


def test_every_branch_port_reaches_its_own_agent(document: dict) -> None:
    branch_ids = [b["id"] for b in _node(document, "router1")["data"]["branches"]]
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
