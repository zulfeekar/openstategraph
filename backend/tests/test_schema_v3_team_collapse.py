"""Team collapses into Workflow — production-ready ticket 16, schema v2 → v3.

Research established `workflow.subgraph` and `team.workflow` **compile
identically**: one builder, no branch, identical ports. Tickets 02 and 03 then
reduced the remaining difference to three declared things — a glyph, an
`outcome` field that turned out to be *documentation*, and a census note the
child earns. None of those is a second kind of node.

So Team is not an organism. It is a Workflow node whose mounted document
happens to contain a revision loop — a property of the document.

**This is the migration chain's first real use.** `MIGRATIONS[1]` is the
identity, registered so the mechanism would exist before it was needed; this is
the change it was waiting for. The schema policy names this case exactly:

    Bump: … changing a port id or a node type's id …

and requires the migration and a fixture document at the old version in the
same commit. Both are here.

**Why now.** Nothing has been published — two local tags, zero remotes, the
PyPI upload never exercised — and no document in the tree mounts a Team. The
only `team.workflow` in `workflow-architect` is inside prompt text teaching the
grammar. That makes this the cheapest this change will ever be; after v0.3.0
ships it is a migration across other people's repositories.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openstategraph.errors import SchemaVersionError
from openstategraph.schema import (
    MIGRATIONS,
    MIN_SUPPORTED_VERSION,
    SCHEMA_VERSION,
    migrate_document,
    normalize_document,
)

FIXTURE = Path(__file__).parent / "data" / "schema_v2_team_mount.json"


def v2_document() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


class TestThePolicyIsFollowed:
    def test_the_version_was_bumped(self) -> None:
        assert SCHEMA_VERSION == 3

    def test_a_migration_ships_for_the_step(self) -> None:
        """"Every bump ships its `MIGRATIONS[n]` function in the same commit."""
        assert 2 in MIGRATIONS

    def test_the_chain_is_unbroken_from_the_oldest_supported_version(self) -> None:
        for step in range(MIN_SUPPORTED_VERSION, SCHEMA_VERSION):
            assert step in MIGRATIONS, f"no migration from v{step} to v{step + 1}"

    def test_a_v2_fixture_exists_and_is_really_v2(self) -> None:
        """"…plus a fixture document at version n that the suite loads."""
        assert FIXTURE.is_file()
        assert v2_document()["version"] == 2

    def test_a_document_from_the_future_is_still_refused(self) -> None:
        with pytest.raises(SchemaVersionError) as caught:
            migrate_document({"version": SCHEMA_VERSION + 1, "nodes": [], "edges": []})
        assert str(SCHEMA_VERSION) in str(caught.value)


class TestTheMountSurvivesTheRename:
    def test_a_team_mount_becomes_a_workflow_mount(self) -> None:
        migrated = migrate_document(v2_document())
        types = {node["type"] for node in migrated["nodes"]}

        assert "team.workflow" not in types
        assert "workflow.subgraph" in types

    def test_the_slug_it_mounts_is_untouched(self) -> None:
        """The whole point of the node — losing it would orphan the mount."""
        node = self._mount(migrate_document(v2_document()))
        assert node["data"]["workflow"] == "sourcing-team"

    def test_per_mount_overrides_survive(self) -> None:
        node = self._mount(migrate_document(v2_document()))
        assert node["data"]["overrides"] == {"grader1": {"maxAttempts": 4}}

    def test_the_authored_outcome_is_not_silently_dropped(self) -> None:
        """User-authored prose, destroyed by an automatic upgrade, is the
        failure this codebase treats as the worst kind: no error, no warning,
        and nothing in the result that looks wrong."""
        node = self._mount(migrate_document(v2_document()))
        assert node["data"]["outcome"] == "Every claim carries a source."

    def test_the_node_id_is_stable_so_edges_still_resolve(self) -> None:
        migrated = migrate_document(v2_document())
        ids = {node["id"] for node in migrated["nodes"]}
        for edge in migrated["edges"]:
            assert edge["source"]["nodeId"] in ids
            assert edge["target"]["nodeId"] in ids

    def test_everything_else_in_the_document_is_left_alone(self) -> None:
        before = v2_document()
        after = migrate_document(before)
        assert [n["type"] for n in after["nodes"] if n["type"] != "workflow.subgraph"] == [
            n["type"] for n in before["nodes"] if n["type"] != "team.workflow"
        ]
        assert after["name"] == before["name"]

    def test_it_does_not_mutate_the_document_it_was_given(self) -> None:
        """A caller holding the on-disk payload keeps it."""
        original = v2_document()
        migrate_document(original)
        assert {n["type"] for n in original["nodes"]} >= {"team.workflow"}

    def test_the_result_is_stamped_at_the_current_version(self) -> None:
        assert migrate_document(v2_document())["version"] == SCHEMA_VERSION

    @staticmethod
    def _mount(document: dict[str, Any]) -> dict[str, Any]:
        return next(n for n in document["nodes"] if n["type"] == "workflow.subgraph")


class TestTheMigratedDocumentIsUsable:
    def test_it_compiles_with_no_findings(self) -> None:
        """A migration that produces a document nothing can run is not one."""
        from openstategraph.validation import validate_document

        valid, findings = validate_document(migrate_document(v2_document()))
        assert valid, findings

    def test_normalize_document_migrates_on_the_ordinary_read_path(self) -> None:
        """Nobody calls `migrate_document` directly — this is the real seam."""
        normalized = normalize_document(v2_document())
        assert normalized["version"] == SCHEMA_VERSION
        assert all(node["type"] != "team.workflow" for node in normalized["nodes"])

    def test_a_saved_envelope_migrates_too(self) -> None:
        """The store wraps documents; the version inside is the schema one."""
        normalized = normalize_document({"version": 1, "document": v2_document()})
        assert all(node["type"] != "team.workflow" for node in normalized["nodes"])


class TestNothingStillSpeaksTheOldName:
    def test_the_runtime_has_no_team_builder_left(self) -> None:
        from openstategraph.compile.node_runtime import NodeRuntime

        assert "team.workflow" not in NodeRuntime(model=None)._builders

    def test_the_architect_no_longer_offers_it(self) -> None:
        """It would teach a model to emit a type id that no longer exists."""
        from openstategraph.prebuilt_architect import KNOWN_NODE_TYPES

        assert "team.workflow" not in KNOWN_NODE_TYPES
        assert "workflow.subgraph" in KNOWN_NODE_TYPES


class TestBothSidesOfTheContractAgree:
    """The schema is written by one side and read by the other.

    This is not theoretical: stamping the shipped documents v3 while the
    editor's own `WORKFLOW_SCHEMA_VERSION` was still 2 made every one of them
    refuse to load — "saved by a newer version" — and nine frontend tests went
    red at once. The two numbers and the two chains move together.
    """

    ROOT = Path(__file__).resolve().parents[2]

    def _typescript(self, path: str) -> str:
        return (self.ROOT / path).read_text(encoding="utf-8")

    def test_the_editor_declares_the_same_version(self) -> None:
        source = self._typescript("src/core/model/WorkflowModel.ts")
        assert f"WORKFLOW_SCHEMA_VERSION = {SCHEMA_VERSION};" in source

    def test_the_editor_ships_the_matching_migration(self) -> None:
        source = self._typescript("src/app/Workbench.ts")
        assert "from: 2," in source
        assert "to: 3," in source
        assert "team.workflow" in source

    def test_every_shipped_document_is_stamped_current(self) -> None:
        """A document one version behind migrates on every single read.

        Harmless and wasteful, and it hides the case where a migration is
        wrong: the on-disk form never exercises the current schema.
        """
        for path in sorted((self.ROOT / "workflows").glob("*/workflow.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            document = payload.get("document", payload)
            assert document["version"] == SCHEMA_VERSION, path.name

    def test_no_shipped_document_still_mounts_the_old_type(self) -> None:
        for path in sorted((self.ROOT / "workflows").glob("*/workflow.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            document = payload.get("document", payload)
            types = {node.get("type") for node in document.get("nodes", [])}
            assert "team.workflow" not in types, path.name
