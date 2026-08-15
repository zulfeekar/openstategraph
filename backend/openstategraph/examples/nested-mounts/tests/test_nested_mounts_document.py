"""Depth, asserted — and the three addresses that name it.

Gallery example 11. Two things are checkable here without spending a token,
and they are the two the recorded smoke expectation rests on:

- **The chain of documents.** Outer mounts middle mounts `chained-summarizer`,
  by slug, with all three on disk. A mount is by *reference*, so the chain is
  a fact about three files rather than about one.
- **The drill-in addresses.** `?w=nested-mounts/mount-mid/mount-inner` is
  exercised against `resolve_mount_document` — the same function the HTTP
  route calls — so the table in `AGENTS.md` is checked rather than asserted.
  Addressing by *mount node id* is the whole point: a slug names the class and
  could not tell two instances apart.

Whether three levels produce a good sentence is `chained-summarizer`'s
question, already recorded there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.api.mount_resolution import resolve_mount_document
from openstategraph.api.workflow_store import WorkflowStore
from openstategraph.package_testing import assert_document_shape, load_document

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent

#: The chain this example exists to be, outermost first.
CHAIN = ("nested-mounts", "nested-mounts-mid", "chained-summarizer")

#: The mount node ids that address it, outermost first. This tuple *is* the
#: drill-in address: `?w=nested-mounts/mount-mid/mount-inner`.
MOUNT_PATH = ("mount-mid", "mount-inner")


def document(slug: str) -> dict:
    """A sibling package's document, by slug. Composition examples read
    more than their own file, which is the point of them."""
    return load_document(ROOT / slug)


@pytest.fixture(scope="module")
def store() -> WorkflowStore:
    return WorkflowStore(ROOT)


def mount_slugs(doc: dict) -> dict[str, str]:
    return {
        n["id"]: n["data"]["workflow"]
        for n in doc["nodes"]
        if n["type"] == "workflow.subgraph"
    }


def test_the_baseline_every_package_shares() -> None:
    """Both levels this package ships, since a chain is only as pinned as its
    weakest link. The third is `chained-summarizer`, which asserts its own.
    `openstategraph.package_testing` owns the reasons for each check."""
    for slug in CHAIN[:2]:
        assert_document_shape(document(slug))


def test_each_level_is_input_mount_output_and_nothing_else() -> None:
    for slug in CHAIN[:2]:
        assert [n["type"] for n in document(slug)["nodes"]] == [
            "input.text",
            "workflow.subgraph",
            "output.formatted",
        ]


def test_the_chain_is_three_documents_deep() -> None:
    assert mount_slugs(document("nested-mounts")) == {"mount-mid": "nested-mounts-mid"}
    assert mount_slugs(document("nested-mounts-mid")) == {"mount-inner": "chained-summarizer"}
    # The floor: the third level is not a mount, or this would not terminate.
    assert mount_slugs(document("chained-summarizer")) == {}


def test_every_level_exists_on_disk() -> None:
    """A mount is by reference. The reference has to point somewhere."""
    for slug in CHAIN:
        assert (ROOT / slug / "workflow.json").is_file(), slug


def test_no_document_in_the_chain_mounts_itself() -> None:
    """The self-mount is a build-time refusal, not a validate-time one
    (gallery ticket 27), so it cannot be left lying on disk to be discovered
    by a run. `NodeRuntime._subgraph` would raise:

        Workflow 'nested-mounts' includes itself through its subgraphs
        (nested-mounts -> nested-mounts); a subgraph cycle can never terminate
    """
    for slug in CHAIN:
        assert slug not in set(mount_slugs(document(slug)).values()), slug


class TestTheThreeAddresses:
    """`AGENTS.md`'s address table, run against the real resolver.

    `resolve_mount_document` is what `GET /api/workflows/{root}/mounts/{path}`
    calls, so this is the addressing contract itself and not a re-derivation
    of it.
    """

    def test_one_segment_names_the_middle_instance(self, store: WorkflowStore) -> None:
        resolved = resolve_mount_document(store, "nested-mounts", ["mount-mid"])
        assert resolved.slug == "nested-mounts-mid"
        assert resolved.mount_path == ["mount-mid"]
        assert resolved.warnings == []

    def test_two_segments_walk_on_to_the_grandchild(self, store: WorkflowStore) -> None:
        resolved = resolve_mount_document(store, "nested-mounts", list(MOUNT_PATH))
        assert resolved.slug == "chained-summarizer"
        assert resolved.mount_path == list(MOUNT_PATH)
        assert [n["id"] for n in resolved.document["nodes"]] == [
            "in1",
            "summarise1",
            "shorten1",
            "out1",
        ]

    def test_the_address_is_the_node_id_not_the_slug(self, store: WorkflowStore) -> None:
        """Addressing by slug is what could not tell two instances apart —
        which is exactly the distinction example 12 depends on."""
        with pytest.raises(Exception):
            resolve_mount_document(store, "nested-mounts", ["nested-mounts-mid"])
