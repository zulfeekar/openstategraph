"""Two instances of one class, asserted where it is checkable.

Gallery example 12. The claim the example exists to make — *the package is
untouched* — has two halves, and only one of them is a model question:

- **The merge is in memory.** `apply_mount_overrides` runs on a copy handed to
  the compiler; nothing writes the child. What a test can pin is the
  consequence: the overriding text lives on THIS document, and
  `chained-summarizer`'s own `shorten1` prompt is still its own. If an override
  ever leaked into the package, this file goes red without a model call.
- **The two instances differ.** Same class, same child node id, same field key,
  two values — and the resolver hands back each one plus the inherited default,
  which is what an inspector shows and what a revert restores.

Whether the two answers *read* differently is the recorded smoke run's job.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.api.mount_resolution import resolve_mount_document
from openstategraph.api.workflow_store import WorkflowStore
from openstategraph.package_testing import assert_document_shape, load_document

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent

MOUNTED = "chained-summarizer"
#: The child node id and field key both instances override. One key, two
#: values, is the cleanest statement of class-versus-instance there is.
CHILD_NODE = "shorten1"
FIELD = "systemPrompt"


def document(slug: str) -> dict:
    """A sibling package's document, by slug. Composition examples read
    more than their own file, which is the point of them."""
    return load_document(ROOT / slug)


@pytest.fixture(scope="module")
def doc() -> dict:
    return document("same-package-twice")


@pytest.fixture(scope="module")
def store() -> WorkflowStore:
    return WorkflowStore(ROOT)


def mounts(doc: dict) -> dict[str, dict]:
    return {n["id"]: n for n in doc["nodes"] if n["type"] == "workflow.subgraph"}


def test_the_baseline_every_package_shares(doc: dict) -> None:
    """Model pin, unique ids, no dangling edge, and a warning-free
    plan — `openstategraph.package_testing` owns the reasons."""
    assert_document_shape(doc)


def test_both_mounts_name_one_package(doc: dict) -> None:
    assert {m["data"]["workflow"] for m in mounts(doc).values()} == {MOUNTED}
    assert sorted(mounts(doc)) == ["mount-analogy", "mount-terse"]


def test_the_two_instances_are_chained_not_joined(doc: dict) -> None:
    """There is no unlimited fan-in port to join two mounts with (gallery
    ticket 14), so B reads A. The chain is the shape, not a shortcut."""
    edges = {
        (e["source"]["nodeId"], e["source"]["portId"], e["target"]["nodeId"], e["target"]["portId"])
        for e in doc["edges"]
    }
    assert edges == {
        ("in1", "text", "mount-terse", "input"),
        ("mount-terse", "result", "mount-analogy", "input"),
        ("mount-analogy", "result", "out1", "result"),
    }


class TestTheOverridesAreTheInstanceState:
    def test_each_mount_overrides_the_same_key_with_a_different_value(self, doc: dict) -> None:
        by_id = mounts(doc)
        values = {}
        for node_id, node in by_id.items():
            overrides = node["data"]["overrides"]
            # The shape `docs/decisions/mount-overrides.md` fixes:
            # {"<childNodeId>": {"<fieldKey>": value}} — child node ids, never
            # titles, because titles are display text and are not unique.
            assert list(overrides) == [CHILD_NODE]
            assert list(overrides[CHILD_NODE]) == [FIELD]
            values[node_id] = overrides[CHILD_NODE][FIELD]
        assert values["mount-terse"] != values["mount-analogy"]

    def test_the_override_targets_a_node_the_package_really_has(self, doc: dict) -> None:
        """An unknown child node id warns and runs the package default — loud,
        not fatal. A shipped example must not be relying on that."""
        child_ids = {n["id"] for n in document(MOUNTED)["nodes"]}
        for node in mounts(doc).values():
            assert set(node["data"]["overrides"]) <= child_ids

    def test_the_package_is_not_where_the_instance_text_lives(self, doc: dict) -> None:
        """The byte-level claim, as a test can put it: neither instance's
        prompt appears in the package, and the package's own prompt is
        unchanged by either of them."""
        package_text = (ROOT / MOUNTED / "workflow.json").read_text()
        for node in mounts(doc).values():
            assert node["data"]["overrides"][CHILD_NODE][FIELD] not in package_text
        package_prompt = next(
            n for n in document(MOUNTED)["nodes"] if n["id"] == CHILD_NODE
        )["data"][FIELD]
        assert "keeps its central claim" in package_prompt


class TestTheResolverSeesTwoInstancesAndOneClass:
    """`GET /api/workflows/{root}/mounts/{path}`, through the function it calls."""

    def test_each_instance_resolves_to_its_own_overridden_document(
        self, doc: dict, store: WorkflowStore
    ) -> None:
        seen = {}
        for node_id, node in mounts(doc).items():
            resolved = resolve_mount_document(store, "same-package-twice", [node_id])
            assert resolved.slug == MOUNTED
            assert resolved.warnings == []
            seen[node_id] = next(
                n for n in resolved.document["nodes"] if n["id"] == CHILD_NODE
            )["data"][FIELD]
            assert seen[node_id] == node["data"]["overrides"][CHILD_NODE][FIELD]
        assert seen["mount-terse"] != seen["mount-analogy"]

    def test_inherited_gives_back_the_class(self, store: WorkflowStore) -> None:
        """What the instance would run if it overrode nothing — the value an
        inspector shows beside an overridden field, and what revert restores.
        The caller cannot compute it: the override has already replaced it."""
        package_prompt = next(
            n for n in document(MOUNTED)["nodes"] if n["id"] == CHILD_NODE
        )["data"][FIELD]
        for node_id in ("mount-terse", "mount-analogy"):
            resolved = resolve_mount_document(
                store, "same-package-twice", [node_id], inherited=True
            )
            assert (
                next(n for n in resolved.document["nodes"] if n["id"] == CHILD_NODE)["data"][FIELD]
                == package_prompt
            )
