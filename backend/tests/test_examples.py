"""The gallery, as an adopter meets it — workflow-gallery ticket 07.

The shipped examples (plus `nested-mounts-mid`, which exists only to be the
middle of a three-deep chain) were staged in `workflows/` while they were being
built. They are not the adopter's workflows, so that is the wrong home for them
in a distribution: `workflows/` is *the user's* directory, resolved from their
project, and a `pip install` must never write into it.

They ship as **package data** instead, exactly as `openstategraph/templates/`
does, and the consequences that follow from the location are what this file
pins:

- they are inside the wheel, so a stranger has them;
- they are **not** under `workflows_root()`, so no customer surface, platform
  tool or `/chat` picker can see them until the user asks for one;
- an example is obtained by **copying**, which severs it — the copy is the
  user's package, in their root, and a later `pip install -U` does not reach
  back into it.

The copy is transitive, because three of the examples mount others. A copy of
`nested-mounts` that could not resolve `nested-mounts-mid` would be a broken
package delivered by the command whose whole job is to deliver a working one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from openstategraph import examples
from openstategraph.scaffold import ScaffoldError, copy_example
from openstategraph.workflows_root import workflows_root

#: The gallery is twenty-two examples plus one middle level (catalogue row 11).
GALLERY_SIZE = 23


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestTheCatalogueIsTheDirectory:
    """`index.json` orders and labels; it never re-states what the package
    already says. A second copy of a summary is a second thing to keep true."""

    def test_every_example_on_disk_is_in_the_catalogue(self) -> None:
        on_disk = {p.parent.name for p in examples.DATA.glob("*/workflow.json")}
        assert on_disk == set(examples.slugs())
        assert len(on_disk) == GALLERY_SIZE

    def test_the_catalogue_is_ordered_for_reading_not_alphabetically(self) -> None:
        """Teaching order — the straight line first, the flagship late."""
        assert examples.slugs()[0] == "chained-summarizer"
        assert list(examples.slugs()) != sorted(examples.slugs())

    def test_name_and_summary_come_from_the_package_itself(self) -> None:
        example = examples.get("sql-qa")
        envelope = json.loads((example.directory / "workflow.json").read_text())
        assert example.name == envelope["name"]
        assert example.summary == envelope["document"]["settings"]["purpose"]

    def test_every_example_declares_a_pattern_and_a_purpose(self) -> None:
        for example in examples.catalogue():
            assert example.pattern, example.slug
            assert example.summary, f"{example.slug} has no settings.purpose"

    def test_every_example_carries_the_file_a_developer_opens_first(self) -> None:
        for example in examples.catalogue():
            assert (example.directory / "AGENTS.md").is_file(), example.slug

    def test_an_unknown_slug_lists_the_ones_that_exist(self) -> None:
        with pytest.raises(examples.UnknownExampleError) as excinfo:
            examples.get("no-such-example")
        assert "chained-summarizer" in str(excinfo.value)


class TestTheyAreNotTheUsersWorkflows:
    """The location IS the visibility rule (gallery ticket 33). No flag hides
    the gallery from the platform tools; being outside the root does."""

    def test_the_examples_are_not_under_the_workflows_root(self) -> None:
        root = workflows_root().resolve()
        for example in examples.catalogue():
            assert not example.directory.resolve().is_relative_to(root), example.slug

    def test_they_are_shipped_beside_the_templates_not_beside_the_user(self) -> None:
        from openstategraph import templates

        assert examples.DATA.parent == templates.DATA.parent

    def test_an_example_is_a_draft_so_a_copy_of_it_is_one_too(self) -> None:
        """`published: false` is inherited by the copy and means what it says
        there: the user publishes their own package when they choose."""
        for example in examples.catalogue():
            envelope = json.loads((example.directory / "workflow.json").read_text())
            assert envelope.get("published") is False, example.slug


class TestMountsAreReadFromTheDocument:
    def test_a_mount_is_derived_never_declared_twice(self) -> None:
        assert examples.get("nested-mounts").mounts == ("nested-mounts-mid",)
        assert examples.get("chained-summarizer").mounts == ()

    def test_requires_is_the_transitive_closure_with_itself_first(self) -> None:
        assert examples.get("nested-mounts").requires() == (
            "nested-mounts",
            "nested-mounts-mid",
            "chained-summarizer",
        )

    def test_a_mount_of_two_packages_needs_both(self) -> None:
        assert set(examples.get("delegate-by-mount").requires()) == {
            "delegate-by-mount",
            "sql-qa",
            "web-research-digest",
        }

    def test_every_mount_in_the_gallery_names_an_example_that_exists(self) -> None:
        for example in examples.catalogue():
            for slug in example.requires():
                assert slug in examples.slugs(), f"{example.slug} mounts {slug}"


class TestCopyingSeversIt:
    def test_a_copy_is_byte_identical_to_what_shipped(self, tmp_path: Path) -> None:
        (created,) = copy_example(tmp_path, "chained-summarizer")

        assert created == tmp_path / "chained-summarizer"
        source = examples.get("chained-summarizer").directory
        shipped = [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        ]
        assert shipped
        for original in shipped:
            assert digest(created / original.relative_to(source)) == digest(original)

    def test_a_copy_brings_the_packages_it_mounts(self, tmp_path: Path) -> None:
        created = copy_example(tmp_path, "nested-mounts")

        assert [p.name for p in created] == [
            "nested-mounts",
            "nested-mounts-mid",
            "chained-summarizer",
        ]
        for path in created:
            assert (path / "workflow.json").is_file()

    def test_the_copy_resolves_its_own_mounts_in_the_new_root(self, tmp_path: Path) -> None:
        """The point of copying the dependencies: the mount is by *slug*, and
        after the copy every slug it names is in the user's own root."""
        copy_example(tmp_path, "nested-mounts")
        document = json.loads((tmp_path / "nested-mounts" / "workflow.json").read_text())

        mounted = [
            node["data"]["workflow"]
            for node in document["document"]["nodes"]
            if node["type"] in ("workflow.subgraph", "team.workflow")
        ]
        assert mounted
        for slug in mounted:
            assert (tmp_path / slug / "workflow.json").is_file()

    def test_the_slug_is_kept_because_a_mount_addresses_it(self, tmp_path: Path) -> None:
        """No `--as`: a package directory name is its frozen identity, and
        another document points at it by that name."""
        (created,) = copy_example(tmp_path, "sql-qa")
        assert created.name == "sql-qa"

    def test_an_existing_directory_is_refused_before_anything_is_written(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "nested-mounts-mid").mkdir()

        with pytest.raises(ScaffoldError) as excinfo:
            copy_example(tmp_path, "nested-mounts")

        assert "nested-mounts-mid" in str(excinfo.value)
        assert not (tmp_path / "nested-mounts").exists(), "a dependency was written anyway"

    def test_an_unknown_example_writes_nothing(self, tmp_path: Path) -> None:
        with pytest.raises(examples.UnknownExampleError):
            copy_example(tmp_path, "no-such-example")
        assert list(tmp_path.iterdir()) == []

    def test_the_copy_carries_no_python_cache(self, tmp_path: Path) -> None:
        (created,) = copy_example(tmp_path, "chained-summarizer")
        assert not list(created.rglob("__pycache__"))

    def test_the_original_is_never_touched(self, tmp_path: Path) -> None:
        source = examples.get("chained-summarizer").directory / "workflow.json"
        before = digest(source)
        copy_example(tmp_path, "chained-summarizer")
        assert digest(source) == before
