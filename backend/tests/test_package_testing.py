"""The shared package-test helper, tested before anything imports it.

`openstategraph.package_testing` is the one piece of machinery twenty-two
package `tests/` files share. It is itself a test helper, so its failure mode
is the worst kind — an assertion that silently stops asserting takes every
package that trusts it down with it, quietly. Hence this file: every helper is
exercised on a document that satisfies it *and* on one that does not.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.package_testing import (
    assert_document_shape,
    edges_of,
    load_document,
    node_of,
    types_of,
)


def _document() -> dict:
    return {
        "version": 3,
        "settings": {"purpose": "the smallest document this helper is asked about"},
        "nodes": [
            {"id": "in1", "type": "input.text", "data": {}},
            {"id": "draft1", "type": "agent.llm", "data": {"systemPrompt": "draft it"}},
            {"id": "out1", "type": "output.formatted", "data": {}},
        ],
        "edges": [
            {
                "source": {"nodeId": "in1", "portId": "text"},
                "target": {"nodeId": "draft1", "portId": "prompt"},
            },
            {
                "source": {"nodeId": "draft1", "portId": "result"},
                "target": {"nodeId": "out1", "portId": "result"},
            },
        ],
    }


def _write_package(root: Path, document: dict | None = None, *, version: int = 1) -> Path:
    package = root / "a-package"
    package.mkdir()
    payload = {
        "version": version,
        "name": "a-package",
        "savedAt": "2026-08-15T00:00:00Z",
        "document": _document() if document is None else document,
    }
    (package / "workflow.json").write_text(json.dumps(payload))
    return package


class TestLoadDocument:
    def test_it_unwraps_the_envelope_and_returns_the_document(self, tmp_path: Path) -> None:
        package = _write_package(tmp_path)
        assert load_document(package)["version"] == 3

    def test_it_accepts_a_string_path(self, tmp_path: Path) -> None:
        package = _write_package(tmp_path)
        assert load_document(str(package))["version"] == 3

    def test_it_refuses_an_envelope_of_the_wrong_version(self, tmp_path: Path) -> None:
        """The envelope check is why twenty files wrote this by hand. It has to
        survive being moved, or the move quietly deletes it."""
        package = _write_package(tmp_path, version=2)
        with pytest.raises(AssertionError, match="envelope version"):
            load_document(package)

    def test_it_refuses_a_document_of_the_wrong_version(self, tmp_path: Path) -> None:
        stale = _document() | {"version": 2}
        package = _write_package(tmp_path, stale)
        with pytest.raises(AssertionError, match="document version"):
            load_document(package)

    def test_the_failure_names_the_package(self, tmp_path: Path) -> None:
        """Twenty-two files share this helper; `assert envelope["version"] == 1`
        with no package in the message would name none of them."""
        package = _write_package(tmp_path, version=2)
        with pytest.raises(AssertionError, match="a-package"):
            load_document(package)


class TestAccessors:
    def test_node_of_finds_a_node_by_id(self) -> None:
        assert node_of(_document(), "draft1")["type"] == "agent.llm"

    def test_node_of_raises_a_readable_error_for_an_unknown_id(self) -> None:
        with pytest.raises(AssertionError, match="no node 'nope'"):
            node_of(_document(), "nope")

    def test_types_of_is_the_node_types_in_document_order(self) -> None:
        assert types_of(_document()) == ["input.text", "agent.llm", "output.formatted"]

    def test_edges_of_is_a_set_of_source_port_target_port_tuples(self) -> None:
        assert edges_of(_document()) == {
            ("in1", "text", "draft1", "prompt"),
            ("draft1", "result", "out1", "result"),
        }


class TestAssertDocumentShape:
    def test_a_conforming_document_passes(self) -> None:
        assert_document_shape(_document(), compiles=False)

    def test_an_unpinned_document_is_the_ordinary_case_now(self) -> None:
        """Inverted by install-experience T10, with the default it followed.

        It used to assert that a document *without* `settings.model` failed the
        baseline, because omitting the field let a machine that happened to
        have `ANTHROPIC_API_KEY` win the fallback and silently move the gallery
        off Ollama cloud. That reasoning moved rather than died: the 22 examples
        are unpinned on purpose now — a copied example runs on whatever the
        adopter installed — and this repository's own runs are pinned in its
        committed `openstategraph.yaml`, which is the level that choice belongs
        at.
        """
        assert_document_shape(_document() | {"settings": {}}, compiles=False)

    def test_a_package_may_still_pin_a_model_deliberately(self) -> None:
        """A document that genuinely needs one vendor says so, and is checked."""
        other = _document() | {"settings": {"model": "anthropic:claude-haiku-4-5"}}
        assert_document_shape(other, model="anthropic:claude-haiku-4-5", compiles=False)

        with pytest.raises(AssertionError, match="model"):
            assert_document_shape(other, model="openai:gpt-4.1-mini", compiles=False)

    def test_it_checks_the_node_type_list_when_given_one(self) -> None:
        assert_document_shape(
            _document(),
            node_types=["input.text", "agent.llm", "output.formatted"],
            compiles=False,
        )
        with pytest.raises(AssertionError):
            assert_document_shape(_document(), node_types=["input.text"], compiles=False)

    def test_it_checks_the_edge_set_when_given_one(self) -> None:
        assert_document_shape(
            _document(),
            edges={
                ("in1", "text", "draft1", "prompt"),
                ("draft1", "result", "out1", "result"),
            },
            compiles=False,
        )
        with pytest.raises(AssertionError):
            assert_document_shape(_document(), edges={("in1", "text", "out1", "result")}, compiles=False)

    def test_it_catches_an_edge_pointing_at_a_node_that_does_not_exist(self) -> None:
        """Nothing in the twenty asserted this, and a dangling edge is exactly
        the defect a hand-edited `workflow.json` acquires."""
        dangling = _document()
        dangling["edges"].append(
            {
                "source": {"nodeId": "draft1", "portId": "result"},
                "target": {"nodeId": "ghost1", "portId": "prompt"},
            }
        )
        with pytest.raises(AssertionError, match="ghost1"):
            assert_document_shape(dangling, compiles=False)

    def test_it_catches_a_duplicate_node_id(self) -> None:
        twinned = _document()
        twinned["nodes"].append({"id": "draft1", "type": "agent.llm", "data": {}})
        with pytest.raises(AssertionError, match="draft1"):
            assert_document_shape(twinned, compiles=False)

    def test_it_compiles_the_document_by_default(self) -> None:
        """The default is the expensive check, because the cheap one passing
        while the graph does not assemble is the failure worth catching."""
        assert_document_shape(_document())

    def test_a_document_the_compiler_warns_about_fails_the_default(self) -> None:
        """A graph every one of whose nodes has an incoming edge has no entry,
        which `plan()` reports as a warning rather than an exception — so a
        shape check that only caught exceptions would pass it."""
        entryless = _document()
        entryless["edges"].append(
            {
                "source": {"nodeId": "out1", "portId": "result"},
                "target": {"nodeId": "in1", "portId": "text"},
            }
        )
        with pytest.raises(AssertionError, match="entry"):
            assert_document_shape(entryless)


# `GALLERY_MODEL` was asserted here — an Ollama **cloud** model, per CLAUDE.md's
# standing instruction. The constant went with the 22 pins (install-experience
# T10) and the instruction did not: it is asserted against this repository's
# committed `openstategraph.yaml` by
# `test_documented_install.py::test_this_repository_pins_its_own_runs`, which is
# where the pin now lives.
