"""The document version stops being decorative (ticket 04).

Before this, `"version": 2` sat in every document and `"version": 1` in every
envelope, and *no code read either*. The failure that buys is specific and
nasty: a document written by a future OpenStateGraph loads silently into an
older one, any field whose meaning changed compiles differently, and the graph
runs and answers — wrongly, with nothing in the output that looks wrong.

The second half of this file is the adjacent silent degradation the same audit
found: `settings.checkpointer: "sqlite"` fell back to an in-process saver in
every install that existed, because `langgraph-checkpoint-sqlite` was imported
but never declared. A user asked for durability, got a log line, and would
discover it when a restart ate a conversation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from openstategraph.errors import DocumentError, SchemaVersionError
from openstategraph.schema import (
    MIN_SUPPORTED_VERSION,
    SCHEMA_VERSION,
    document_version,
    migrate_document,
    normalize_document,
)

DOCUMENT: dict[str, Any] = {"version": SCHEMA_VERSION, "name": "demo", "nodes": [], "edges": []}


class TestTheShapesThatArriveToday:
    def test_a_bare_document_passes_through(self) -> None:
        assert normalize_document(DOCUMENT) == DOCUMENT

    def test_the_store_envelope_is_peeled(self) -> None:
        envelope = {"version": 1, "name": "demo", "savedAt": "", "document": DOCUMENT}

        assert normalize_document(envelope) == DOCUMENT

    def test_the_envelopes_own_version_is_not_the_schema_version(self) -> None:
        """The envelope's `version: 1` is the store's file format. Reading it
        as the schema version would refuse or migrate every document in the
        tree — two numbers, and only one of them is ours."""
        envelope = {"version": 1, "document": {**DOCUMENT, "version": SCHEMA_VERSION}}

        assert normalize_document(envelope)["version"] == SCHEMA_VERSION

    def test_a_json_string_is_accepted(self) -> None:
        """MCP clients serialize inconsistently; this was `mcp_server`'s own
        normalizer before the two collapsed into one."""
        assert normalize_document(json.dumps(DOCUMENT)) == DOCUMENT

    def test_something_that_is_not_a_document_says_so(self) -> None:
        with pytest.raises(DocumentError):
            normalize_document([1, 2, 3])

    def test_unparseable_json_says_so(self) -> None:
        with pytest.raises(DocumentError):
            normalize_document("{not json")

    def test_every_workflow_in_this_repo_still_loads(self) -> None:
        """The guard is worthless if it refuses our own committed documents."""
        root = Path(__file__).resolve().parents[2] / "workflows"
        manifests = sorted(root.glob("*/workflow.json"))
        assert manifests, "no workflow packages found — this test would pass vacuously"

        for manifest in manifests:
            document = normalize_document(json.loads(manifest.read_text()))

            assert isinstance(document.get("nodes"), list), manifest


class TestTheGuard:
    def test_a_document_from_the_future_is_refused_naming_both_versions(self) -> None:
        future = {**DOCUMENT, "version": SCHEMA_VERSION + 2}

        with pytest.raises(SchemaVersionError) as excinfo:
            normalize_document(future)

        message = str(excinfo.value)
        assert f"v{SCHEMA_VERSION + 2}" in message
        assert f"v{SCHEMA_VERSION}" in message
        assert "pip install -U openstategraph" in message

    def test_refused_means_refused_not_best_effort(self) -> None:
        """Recorded decision. Everywhere else this codebase degrades loudly
        rather than failing — an unresolved tool is a warning — because those
        failures are visible in the result. A silently-different compile is
        not, so it is the exception."""
        with pytest.raises(SchemaVersionError):
            migrate_document({**DOCUMENT, "version": 99})

    def test_a_document_too_old_to_migrate_is_refused(self) -> None:
        ancient = {**DOCUMENT, "version": MIN_SUPPORTED_VERSION - 1}

        with pytest.raises(SchemaVersionError) as excinfo:
            normalize_document(ancient)

        assert f"v{MIN_SUPPORTED_VERSION}" in str(excinfo.value)

    def test_a_non_integer_version_is_refused(self) -> None:
        with pytest.raises(SchemaVersionError):
            document_version({"version": "two"})

    def test_a_version_at_the_floor_migrates_forward(self) -> None:
        old = {"version": MIN_SUPPORTED_VERSION, "nodes": [], "edges": []}

        migrated = normalize_document(old)

        assert migrated["version"] == SCHEMA_VERSION
        assert migrated["nodes"] == []

    def test_migration_never_mutates_the_caller_s_document(self) -> None:
        """A caller holding the on-disk payload keeps it."""
        old = {"version": MIN_SUPPORTED_VERSION, "nodes": [], "edges": []}

        migrate_document(old)

        assert old["version"] == MIN_SUPPORTED_VERSION

    def test_an_absent_version_is_read_as_this_build_s_and_stamped(self, caplog) -> None:
        """Hand-written and exported documents omit it constantly; refusing
        those would punish the case the format exists to make easy."""
        with caplog.at_level("INFO", logger="openstategraph.schema"):
            normalized = normalize_document({"nodes": [], "edges": []})

        assert normalized["version"] == SCHEMA_VERSION
        assert any("no schema version" in r.getMessage() for r in caplog.records)

    def test_the_migration_chain_covers_every_supported_version(self) -> None:
        """A gap in the chain is only discoverable when someone's document
        hits it. `MIGRATIONS` must have a step for every version we claim."""
        for version in range(MIN_SUPPORTED_VERSION, SCHEMA_VERSION):
            assert migrate_document({"version": version, "nodes": []})["version"] == (
                SCHEMA_VERSION
            )


class TestOneSeam:
    """A guard with two entrances is not a guard."""

    def test_the_old_private_name_is_the_same_object(self) -> None:
        from openstategraph.api.registries import _document_of

        assert _document_of is normalize_document

    def test_the_loader_refuses_a_future_document(self, tmp_path: Path) -> None:
        package = tmp_path / "demo-pkg"
        package.mkdir()
        (package / "workflow.json").write_text(
            json.dumps({"version": 1, "document": {**DOCUMENT, "version": 99}})
        )

        with pytest.raises(SchemaVersionError):
            from openstategraph import load_workflow

            load_workflow(package)


class TestSqliteDegradesLoudly:
    """The dependency is declared now (`[sqlite]`), so the message can name the
    fix instead of describing the symptom."""

    @pytest.fixture
    def sqlite_missing(self, monkeypatch) -> None:
        """`None` in `sys.modules` makes `import x` raise ImportError — the
        exact failure an install without the extra produces."""
        for name in ("langgraph.checkpoint.sqlite", "langgraph.store.sqlite"):
            monkeypatch.setitem(sys.modules, name, None)

    def test_the_checkpointer_names_the_extra(self, sqlite_missing, caplog) -> None:
        from openstategraph.memory import checkpointer_for

        sentinel = object()
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            result = checkpointer_for({"checkpointer": "sqlite"}, "demo", sentinel)

        message = " ".join(r.getMessage() for r in caplog.records)
        assert result is sentinel
        assert "pip install 'openstategraph[sqlite]'" in message
        assert "NOT survive a restart" in message

    def test_the_memory_store_names_the_extra(
        self, sqlite_missing, caplog, monkeypatch, tmp_path
    ) -> None:
        from openstategraph.memory import build_store

        monkeypatch.setenv("OPENSTATEGRAPH_MEMORY_PATH", str(tmp_path / "memory.sqlite"))
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            build_store()

        message = " ".join(r.getMessage() for r in caplog.records)
        assert "pip install 'openstategraph[sqlite]'" in message
        assert "NOT survive a restart" in message

    def test_a_workflow_that_never_asked_for_sqlite_says_nothing(self, caplog) -> None:
        """The warning must stay attributable. A message on every load is a
        message nobody reads."""
        from openstategraph.memory import checkpointer_for

        sentinel = object()
        with caplog.at_level("WARNING", logger="openstategraph.memory"):
            assert checkpointer_for({}, "demo", sentinel) is sentinel

        assert caplog.records == []
