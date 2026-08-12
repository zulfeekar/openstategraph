"""Agent Plugins v1.0.0 interop — the seam, tested against the normative spec.

Every fixture is a throwaway tmp directory with an invented slug: `workflows/`
is real content owned by humans and must never be the substrate of a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.plugin_interop import (
    EXTENSION_NAMESPACE,
    MCP_SCHEMA_ID,
    PLUGIN_SCHEMA_ID,
    InvalidPluginError,
    export_plugin,
    import_plugin,
    write_export,
    write_import,
)


def _package(tmp_path: Path, slug: str = "sales-copilot") -> Path:
    directory = tmp_path / "workflows" / slug
    (directory / "skills").mkdir(parents=True)
    (directory / "knowledge").mkdir()
    (directory / "tools").mkdir()
    (directory / "data").mkdir()
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": "Sales Copilot", "document": {"nodes": [], "edges": []}})
    )
    (directory / "AGENTS.md").write_text(
        "# Sales Copilot\n\nAnswers revenue questions over the sales warehouse.\n\nMore prose.\n"
    )
    (directory / "skills" / "refunds.md").write_text(
        "Refunds are never issued past 90 days.\n\nEscalate exceptions to finance.\n"
    )
    (directory / "knowledge" / "invoice.md").write_text("One row per customer purchase.\n")
    (directory / "tools" / "warehouse.py").write_text("TOOLS = []\n")
    (directory / "data" / "big.sqlite").write_bytes(b"\x00binary")
    return directory


# ---------------------------------------------------------------- export


def test_export_manifest_is_spec_conformant(tmp_path: Path) -> None:
    export = export_plugin(_package(tmp_path))
    manifest = export.manifest
    assert manifest["$schema"] == PLUGIN_SCHEMA_ID
    assert manifest["name"] == "sales-copilot"
    assert manifest["description"].startswith("Answers revenue questions")
    # Closed schema: only permitted top-level fields (§5.2).
    permitted = {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "extensions",
    }
    assert set(manifest) <= permitted


def test_export_puts_each_skill_in_its_own_directory_with_frontmatter(tmp_path: Path) -> None:
    export = export_plugin(_package(tmp_path))
    skill = export.files["skills/refunds/SKILL.md"]
    assert skill.startswith("---\n")
    assert "name: refunds\n" in skill
    # Description is synthesized from the first meaningful line — a lossy edge.
    assert "description: Refunds are never issued past 90 days." in skill
    assert skill.rstrip().endswith("Escalate exceptions to finance.")


def test_export_keeps_a_description_the_skill_file_already_declares(tmp_path: Path) -> None:
    """Ticket 28: one writer for the format, and it reads before it writes.

    The header used to be pasted together here, so a `skills/*.md` that already
    carried frontmatter was exported with a second header stacked on the first
    and a description synthesized from the line `---`.
    """
    root = _package(tmp_path)
    (root / "skills" / "refunds.md").write_text(
        "---\nname: refunds\ndescription: The refund policy.\n---\n\nEscalate to finance.\n"
    )
    export = export_plugin(root)
    skill = export.files["skills/refunds/SKILL.md"]
    assert skill.count("---") == 2
    assert "description: The refund policy." in skill
    assert skill.rstrip().endswith("Escalate to finance.")


def test_export_carries_non_portable_parts_into_the_extension_directory(tmp_path: Path) -> None:
    export = export_plugin(_package(tmp_path))
    assert f"{EXTENSION_NAMESPACE}/knowledge/invoice.md" in export.files
    assert f"{EXTENSION_NAMESPACE}/workflow.json" in export.files
    assert f"{EXTENSION_NAMESPACE}/tools/warehouse.py" in export.files
    assert f"{EXTENSION_NAMESPACE}/AGENTS.md" in export.files
    # knowledge lives nowhere portable, and the caller is told so.
    assert any("knowledge" in note for note in export.notes)


def test_export_never_emits_mcp_json(tmp_path: Path) -> None:
    export = export_plugin(_package(tmp_path))
    assert "mcp.json" not in export.files
    assert any("MCP" in note for note in export.notes)


def test_export_excludes_data_and_pycache(tmp_path: Path) -> None:
    directory = _package(tmp_path)
    (directory / "tools" / "__pycache__").mkdir()
    (directory / "tools" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    export = export_plugin(directory)
    assert not any("data/" in path or "__pycache__" in path for path in export.files)


def test_export_rejects_a_slug_that_cannot_be_a_plugin_name(tmp_path: Path) -> None:
    directory = _package(tmp_path, slug="Bad--Name")
    with pytest.raises(InvalidPluginError):
        export_plugin(directory)


def test_export_skips_a_skill_whose_name_breaks_the_agent_skills_rule(tmp_path: Path) -> None:
    directory = _package(tmp_path)
    (directory / "skills" / "Not_Valid.md").write_text("body\n")
    export = export_plugin(directory)
    assert not any(path.startswith("skills/Not_Valid") for path in export.files)
    assert any("Not_Valid" in note for note in export.notes)


def test_write_export_materializes_the_layout(tmp_path: Path) -> None:
    export = export_plugin(_package(tmp_path))
    dest = tmp_path / "out" / "sales-copilot"
    write_export(export, dest)
    manifest = json.loads((dest / "plugin.json").read_text())
    assert manifest["name"] == "sales-copilot"
    assert (dest / "skills" / "refunds" / "SKILL.md").is_file()
    assert (dest / EXTENSION_NAMESPACE / "knowledge" / "invoice.md").is_file()


# ---------------------------------------------------------------- import


def _plugin(tmp_path: Path, *, manifest: dict | None = None) -> Path:
    root = tmp_path / "plugin"
    (root / "skills" / "deploy" / "references").mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            manifest
            if manifest is not None
            else {"$schema": PLUGIN_SCHEMA_ID, "name": "deploy-kit", "description": "Ship things."}
        )
    )
    (root / "skills" / "deploy" / "SKILL.md").write_text(
        "---\nname: deploy\ndescription: Roll out a release.\nallowed-tools: Bash\n---\n\nStep one.\n"
    )
    (root / "skills" / "deploy" / "references" / "runbook.md").write_text("details\n")
    return root


def test_import_maps_skills_to_our_flat_loader_and_strips_frontmatter(tmp_path: Path) -> None:
    plan = import_plugin(_plugin(tmp_path))
    assert plan.files["skills/deploy.md"].strip() == "Step one."
    assert any("allowed-tools" in note or "frontmatter" in note for note in plan.notes)


def test_import_carries_skill_resources_but_says_they_are_inert(tmp_path: Path) -> None:
    plan = import_plugin(_plugin(tmp_path))
    assert "skills/deploy/references/runbook.md" in plan.files
    assert any("inert" in note for note in plan.notes)


def test_import_synthesizes_a_workflow_skeleton_never_a_runnable_graph(tmp_path: Path) -> None:
    plan = import_plugin(_plugin(tmp_path))
    envelope = json.loads(plan.files["workflow.json"])
    assert envelope["document"] == {"nodes": [], "edges": []}
    assert envelope["name"] == "deploy-kit"
    # The portability rule: none of their vocabulary leaks into workflow.json.
    for token in ("plugin.json", "$schema", "mcpServers", "PLUGIN_ROOT", "SKILL.md"):
        assert token not in plan.files["workflow.json"]


def test_import_reports_every_mcp_server_as_unsupported(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    (root / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "db": {"type": "stdio", "command": "./bin/db"},
                    "api": {"type": "streamable-http", "url": "https://x.example.com/mcp"},
                },
            }
        )
    )
    plan = import_plugin(root)
    notes = "\n".join(plan.notes)
    assert "db" in notes and "api" in notes
    assert not any(path.startswith("mcp") for path in plan.files)


def test_import_rejects_a_manifest_missing_required_fields(tmp_path: Path) -> None:
    with pytest.raises(InvalidPluginError):
        import_plugin(_plugin(tmp_path, manifest={"name": "no-schema"}))
    with pytest.raises(InvalidPluginError):
        import_plugin(_plugin(tmp_path, manifest={"$schema": PLUGIN_SCHEMA_ID, "name": "Bad Name"}))


def test_import_reports_and_ignores_unknown_top_level_fields(tmp_path: Path) -> None:
    plan = import_plugin(
        _plugin(
            tmp_path,
            manifest={"$schema": PLUGIN_SCHEMA_ID, "name": "deploy-kit", "commands": ["nope"]},
        )
    )
    assert any("commands" in note for note in plan.notes)


def test_import_ignores_foreign_extension_directories(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    (root / "com.example.client" / "hooks").mkdir(parents=True)
    (root / "com.example.client" / "hooks" / "hooks.json").write_text("{}")
    plan = import_plugin(root)
    assert not any("com.example.client" in path for path in plan.files)


def test_import_refuses_a_path_escaping_the_plugin_root(tmp_path: Path) -> None:
    root = _plugin(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n")
    (root / "skills" / "escape").mkdir()
    (root / "skills" / "escape" / "SKILL.md").symlink_to(outside)
    plan = import_plugin(root)
    assert "skills/escape.md" not in plan.files
    assert any("escape" in note for note in plan.notes)


def test_round_trip_restores_our_package(tmp_path: Path) -> None:
    directory = _package(tmp_path)
    export = export_plugin(directory)
    plugin_dir = tmp_path / "plugin-out"
    write_export(export, plugin_dir)

    plan = import_plugin(plugin_dir)
    restored = tmp_path / "restored"
    write_import(plan, restored)

    assert json.loads((restored / "workflow.json").read_text())["name"] == "Sales Copilot"
    assert (restored / "knowledge" / "invoice.md").read_text() == "One row per customer purchase.\n"
    assert (restored / "tools" / "warehouse.py").read_text() == "TOOLS = []\n"
    assert "Refunds are never issued past 90 days." in (restored / "skills" / "refunds.md").read_text()


def test_the_endpoint_reports_the_layout_and_writes_nothing(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from openstategraph.api.main import create_app

    directory = _package(tmp_path)
    client = TestClient(create_app(workflows_root=directory.parent))
    before = sorted(p.name for p in directory.iterdir())

    response = client.get("/api/workflows/sales-copilot/plugin-export")
    assert response.status_code == 200
    payload = response.json()
    assert payload["manifest"]["name"] == "sales-copilot"
    assert "skills/refunds/SKILL.md" in payload["paths"]
    assert payload["notes"]
    assert sorted(p.name for p in directory.iterdir()) == before

    assert client.get("/api/workflows/nope/plugin-export").status_code == 404


def test_write_import_will_not_clobber_an_existing_package(tmp_path: Path) -> None:
    plan = import_plugin(_plugin(tmp_path))
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "workflow.json").write_text("{}")
    with pytest.raises(InvalidPluginError):
        write_import(plan, dest)
