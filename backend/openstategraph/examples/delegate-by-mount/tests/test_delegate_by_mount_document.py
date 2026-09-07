"""Two packages behind one classifier, asserted.

Gallery example 13. What a test settles here is the wiring the recorded smoke
run depends on: two exclusive branches reaching two *different* packages, each
with its own terminal output, and exactly one mount claiming an outcome —
the one whose child can enforce it.

That last one is the interesting assertion. `Finding.UNENFORCED_OUTCOME` fires
when a mount states an outcome and the child does not route a `revise` edge, so
"this mount loops until its grader passes" is a claim checked against the child
document rather than against the node type. A mount with no outcome claims
nothing and is not warned about — which is why `mount-sql` states none.

Whether the classifier routes this particular question correctly is a model
question; the smoke run records it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.package_testing import assert_document_shape, load_document

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent


def document(slug: str) -> dict:
    """A sibling package's document, by slug. Composition examples read
    more than their own file, which is the point of them."""
    return load_document(ROOT / slug)


@pytest.fixture(scope="module")
def doc() -> dict:
    return document("delegate-by-mount")


def mounts(doc: dict) -> dict[str, dict]:
    return {n["id"]: n for n in doc["nodes"] if n["type"] == "workflow.subgraph"}


def closes_a_loop(doc: dict) -> bool:
    plan = WorkflowCompiler().plan(doc)
    return any("revise" in branches for branches in plan.conditional.values())


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_the_two_branches_reach_two_different_packages(doc: dict) -> None:
    slugs = {node_id: m["data"]["workflow"] for node_id, m in mounts(doc).items()}
    assert slugs == {
        "mount-sql": "sql-qa",
        "mount-web": "web-research-digest",
    }
    # Heterogeneous is the point: one class of answer per branch. Two mounts of
    # ONE package with different overrides is example 12, a different question.
    assert len(set(slugs.values())) == 2


def test_both_delegates_exist_on_disk(doc: dict) -> None:
    for slug in {m["data"]["workflow"] for m in mounts(doc).values()}:
        assert (ROOT / slug / "workflow.json").is_file(), slug


def test_the_router_reaches_each_mount_and_nothing_else(doc: dict) -> None:
    plan = WorkflowCompiler().plan(doc)
    assert plan.conditional["router1"] == {
        "b-database": "mount-sql",
        "b-web": "mount-web",
    }


def test_each_branch_owns_its_output(doc: dict) -> None:
    """Two edges into one `output.formatted` compile, but the capacity rule
    makes drawing the second *replace* the first, so the graph would not be
    redrawable (gallery ticket 13). Every example in the twenty avoids it."""
    plan = WorkflowCompiler().plan(doc)
    assert sorted(plan.exits) == ["out-database", "out-web"]
    targets = [
        (e["target"]["nodeId"], e["target"]["portId"])
        for e in doc["edges"]
        if e["target"]["portId"] == "result"
    ]
    assert len(targets) == len(set(targets))


def test_only_the_looping_mount_claims_an_outcome(doc: dict) -> None:
    by_id = mounts(doc)
    assert by_id["mount-web"]["data"]["outcome"].strip()
    assert not by_id["mount-sql"]["data"].get("outcome", "").strip()
    # …and the claim is true of the child, which is what the compiler checks.
    assert closes_a_loop(document("web-research-digest"))
    assert not closes_a_loop(document("sql-qa"))


def test_it_compiles_without_a_warning(doc: dict) -> None:
    """Including `UNENFORCED_OUTCOME`: an example that ships a warning teaches
    it."""
    assert WorkflowCompiler().plan(doc).warnings == []


def test_delegation_is_call_and_return_not_a_tool(doc: dict) -> None:
    """The substitution recorded in the catalogue: a mount cannot be a tool.
    `workflow.subgraph` has two ports, `input` and `result`, and neither is a
    `tool` — so no mount reaches an agent's `tools` bus
    (organisms-first-class 31). This asserts the example stays honest about
    which mechanism it is showing."""
    ports = {
        (e["source"]["portId"], e["target"]["portId"])
        for e in doc["edges"]
        if e["source"]["nodeId"] in mounts(doc) or e["target"]["nodeId"] in mounts(doc)
    }
    assert all(target != "tools" for _, target in ports)
    assert "agent.llm" not in {n["type"] for n in doc["nodes"]}
