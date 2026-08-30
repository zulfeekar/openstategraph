"""A directory of workflows that already exists is a project to adopt.

`init` had one answer for `workflows/` already being there and not being
ours: a refusal, whose two remedies were *pick a different root* and *move
theirs out of the way*. Both are wrong for the shape that motivated this —
a service that already ships a `workflows/` directory and now wants the
canvas over the top of it, in its own process. Its `workflows/` is not an
obstacle; it is the thing being adopted.

**The original argument is kept, and only its outcome changes.** That
refusal's reasoning (`launch-readiness`) was never "sharing a root is wrong",
it was *"nothing is destroyed; the defect is that the user was never told"*.
So the user is told — in detail, package by package — and the decision stays
theirs, expressed as a flag rather than a prompt, because exit codes are this
CLI's API and a command that blocks on stdin hangs a CI job.

Three exits, all named in the output: adopt it, use another root, move theirs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.scaffold import ScaffoldError, init_project, review_workflows_root


def package(root: Path, slug: str, name: str, nodes: int = 2) -> Path:
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": name,
                "nodes": [{"id": f"n{i}", "type": "input.text"} for i in range(nodes)],
                "edges": [],
            }
        )
    )
    return directory


class TestTheReview:
    def test_every_package_is_named_with_what_it_holds(self, tmp_path: Path) -> None:
        root = tmp_path / "workflows"
        package(root, "their-flow", "Their Flow", nodes=7)
        package(root, "second", "Second", nodes=1)

        found = review_workflows_root(root)

        assert [(row.slug, row.name, row.node_count) for row in found] == [
            ("second", "Second", 1),
            ("their-flow", "Their Flow", 7),
        ]

    def test_a_package_that_will_not_parse_is_a_row_carrying_the_reason(
        self, tmp_path: Path
    ) -> None:
        """The same rule the catalogue follows: rubble is reported, never
        omitted. A review that silently drops the one broken package is a
        review that hides exactly what a reader most needs to see before
        adopting."""
        root = tmp_path / "workflows"
        package(root, "fine", "Fine")
        (root / "half-built").mkdir()
        (root / "half-built" / "workflow.json").write_text("{ broken")

        found = {row.slug: row for row in review_workflows_root(root)}

        assert found["half-built"].error is not None
        assert found["fine"].error is None

    def test_a_directory_with_no_document_is_not_a_package_and_is_not_listed(
        self, tmp_path: Path
    ) -> None:
        """`.git`, `__pycache__`, a `shared/` folder of prompts. Listing them
        as broken packages would make a clean adoption look alarming."""
        root = tmp_path / "workflows"
        package(root, "fine", "Fine")
        (root / "notes").mkdir()
        (root / ".hidden").mkdir()

        assert [row.slug for row in review_workflows_root(root)] == ["fine"]


class TestTheRefusalBecameAReview:
    def test_it_still_refuses_without_consent(self, tmp_path: Path) -> None:
        package(tmp_path / "workflows", "their-flow", "Their Flow")

        with pytest.raises(ScaffoldError) as refusal:
            init_project(tmp_path, label=".", force=True)

        assert "Nothing was written" in str(refusal.value)

    def test_the_refusal_now_says_what_is_in_there(self, tmp_path: Path) -> None:
        """The whole change. A reader deciding whether to adopt a directory
        needs to see the directory."""
        root = tmp_path / "workflows"
        package(root, "their-flow", "Their Flow", nodes=7)
        (root / "half-built").mkdir()
        (root / "half-built" / "workflow.json").write_text("{ broken")

        with pytest.raises(ScaffoldError) as refusal:
            init_project(tmp_path, label=".", force=True)
        message = str(refusal.value)

        assert "their-flow" in message
        assert "Their Flow" in message
        assert "half-built" in message
        assert "--adopt" in message

    def test_adopting_writes_the_config_and_leaves_their_packages_alone(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "workflows"
        their = package(root, "their-flow", "Their Flow")
        before = (their / "workflow.json").read_text()

        result = init_project(tmp_path, label=".", force=True, adopt=True)

        assert result.config.is_file()
        assert (their / "workflow.json").read_text() == before

    def test_adopting_writes_no_starter_into_somebody_elses_root(
        self, tmp_path: Path
    ) -> None:
        """A starter is a teaching aid for an empty root. Dropped into a root
        that already holds a team's packages it is litter — and it is litter
        under a slug (`starter`) they may already be using."""
        root = tmp_path / "workflows"
        package(root, "their-flow", "Their Flow")

        result = init_project(tmp_path, label=".", force=True, adopt=True)

        assert result.starter is None
        assert sorted(p.name for p in root.iterdir()) == ["their-flow"]

    def test_adopting_records_what_it_adopted(self, tmp_path: Path) -> None:
        """So `init` can print the review as a report of what the project now
        reads, rather than as the reason it stopped."""
        root = tmp_path / "workflows"
        package(root, "their-flow", "Their Flow", nodes=7)

        result = init_project(tmp_path, label=".", force=True, adopt=True)

        assert [row.slug for row in result.adopted] == ["their-flow"]

    def test_adopt_is_inert_where_there_was_nothing_to_adopt(self, tmp_path: Path) -> None:
        """`--adopt` in a fresh directory must not become a second, quieter
        `init` that skips the starter. Consent to share a root nobody else
        owns is consent to nothing."""
        result = init_project(tmp_path / "fresh", label="fresh", adopt=True)

        assert result.adopted == ()
        assert result.starter is not None
