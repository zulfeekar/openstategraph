"""The exported bundle carries a README that names its own dependencies.

`export-and-eject/06`. Three genuinely different packages, and the assertions
are about what each README *does not* say as much as what it does: a package
with no provider must not be handed an install line for one, and a package with
no wiring directories must not be warned about discovery conventions it never
used. A sentence that always prints has no way to be wrong.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from openstategraph.plugin_interop import export_plugin


def _write(directory: Path, document: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": directory.name, "document": document})
    )
    return directory


def _tooled(tmp_path: Path) -> Path:
    """Per-node model (slash spelling), tools/ and knowledge/ on disk."""
    directory = _write(
        tmp_path / "warehouse-desk",
        {
            "nodes": [
                {"id": "a1", "type": "agent.llm", "data": {"model": "anthropic/claude-haiku-4-5"}},
                {"id": "t1", "type": "tool.python", "data": {}},
            ],
            "edges": [],
        },
    )
    (directory / "tools").mkdir()
    (directory / "tools" / "warehouse.py").write_text("TOOLS = []\n")
    (directory / "knowledge").mkdir()
    (directory / "knowledge" / "schema.md").write_text("One row per invoice.\n")
    return directory


def _bare(tmp_path: Path) -> Path:
    """No tools, no functions, no skills, no model string anywhere."""
    return _write(
        tmp_path / "plain-note",
        {"nodes": [{"id": "in1", "type": "input.text", "data": {}}], "edges": []},
    )


def _deep(tmp_path: Path) -> Path:
    """A `tier: deep` agent, sqlite checkpointer, colon-spelled default model."""
    return _write(
        tmp_path / "deep-desk",
        {
            "settings": {"model": "ollama:gpt-oss:120b-cloud", "checkpointer": "sqlite"},
            "nodes": [{"id": "a1", "type": "agent.llm", "data": {"tier": "deep"}}],
            "edges": [],
        },
    )


def _readme(directory: Path) -> str:
    export = export_plugin(directory)
    assert "README.md" in export.files, "the bundle must carry a README"
    return export.files["README.md"]


# ------------------------------------------------------- what to install


def test_a_node_model_names_its_provider_extra_and_no_other(tmp_path: Path) -> None:
    readme = _readme(_tooled(tmp_path))
    assert "pip install 'openstategraph[anthropic]'" in readme
    # Strict in trusting: nothing this document does not ask for.
    assert "openai" not in readme
    assert "[deep]" not in readme
    assert "[sqlite]" not in readme
    # And the line says which node asked for it, so a reader can check.
    assert "a1" in readme and "anthropic/claude-haiku-4-5" in readme


def test_a_document_with_no_model_gets_the_bare_install_line(tmp_path: Path) -> None:
    readme = _readme(_bare(tmp_path))
    assert "pip install openstategraph\n" in readme
    assert "openstategraph[" not in readme
    assert "anthropic" not in readme


def test_a_deep_tier_and_a_sqlite_checkpointer_are_both_named(tmp_path: Path) -> None:
    readme = _readme(_deep(tmp_path))
    assert "pip install 'openstategraph[deep,ollama,sqlite]'" in readme
    assert "anthropic" not in readme


def test_the_settings_model_uses_the_colon_spelling_and_a_node_the_slash(
    tmp_path: Path,
) -> None:
    """The two spellings are not interchangeable — `youtube-trend-digest`'s trap.

    A node value with no `/` falls back to the document default at run time
    (`NodeRuntime._base_model`), so it must not be read as a provider prefix.
    """
    directory = _write(
        tmp_path / "spelling-desk",
        {
            "settings": {"model": "openai:gpt-5"},
            "nodes": [
                {"id": "a1", "type": "agent.llm", "data": {"model": "anthropic:claude-haiku-4-5"}},
                {"id": "a2", "type": "agent.llm", "data": {"model": "mock/whatever"}},
            ],
            "edges": [],
        },
    )
    readme = _readme(directory)
    assert "pip install 'openstategraph[openai]'" in readme
    assert "anthropic" not in readme
    assert "mock" not in readme


def test_an_unrecognised_provider_prefix_is_reported_not_guessed(tmp_path: Path) -> None:
    directory = _write(
        tmp_path / "vendor-desk",
        {"settings": {"model": "acme:mega-1"}, "nodes": [], "edges": []},
    )
    readme = _readme(directory)
    assert "pip install openstategraph\n" in readme
    assert "acme" in readme


# ------------------------------------------------- what did not come with it


def test_the_notes_are_the_did_not_cross_section(tmp_path: Path) -> None:
    export = export_plugin(_tooled(tmp_path))
    readme = export.files["README.md"]
    for note in export.notes:
        assert f"- {note}" in readme, note


def test_a_package_with_wiring_is_told_how_it_fails_silently(tmp_path: Path) -> None:
    readme = _readme(_tooled(tmp_path))
    assert "load_workflow" in readme
    assert "drawn with three tools, bound to none" in readme
    assert "tools/" in readme


def test_a_package_with_no_wiring_is_not_told_about_discovery(tmp_path: Path) -> None:
    """The load-bearing inverse: a package without a thing is not warned of it."""
    readme = _readme(_bare(tmp_path))
    assert "drawn with three tools" not in readme
    assert "discovery convention" not in readme


def test_the_readme_never_claims_a_directory_the_package_lacks(tmp_path: Path) -> None:
    readme = _readme(_bare(tmp_path))
    # `tools/` is deliberately not in this list: the unconditional "No mcp.json"
    # note names it, and that sentence is about this runtime rather than about
    # this package (see `8e2fba8`'s enumeration).
    for absent in ("functions/", "middlewares/", "knowledge/", "skills/"):
        assert absent not in readme, absent


# --------------------------------------------------------- the recipe runs


def test_the_run_recipe_is_the_one_that_actually_loads(tmp_path: Path) -> None:
    """The payload directory is not loadable under its own name — verified.

    `org.openstategraph` has a period in it (§8 wants a reverse domain) and
    `load_workflow` refuses any directory whose name is not a slug, because the
    slug scopes tool/function/skill/knowledge discovery. So the README must
    never print `load_workflow("org.openstategraph")`; it prints the copy first.
    """
    from openstategraph import load_workflow
    from openstategraph.errors import InvalidPackageName
    from openstategraph.plugin_interop import EXTENSION_NAMESPACE, write_export

    directory = _tooled(tmp_path)
    bundle = write_export(export_plugin(directory), tmp_path / "bundle")
    readme = (bundle / "README.md").read_text()
    assert f'load_workflow("{EXTENSION_NAMESPACE}")' not in readme
    assert f"cp -R {EXTENSION_NAMESPACE} warehouse-desk" in readme
    assert 'load_workflow("warehouse-desk")' in readme

    with pytest.raises(InvalidPackageName):
        load_workflow(bundle / EXTENSION_NAMESPACE)
    shutil.copytree(bundle / EXTENSION_NAMESPACE, bundle / "warehouse-desk")
    assert load_workflow(bundle / "warehouse-desk") is not None


def test_every_extra_the_readme_can_print_is_one_pip_can_install() -> None:
    """An install line naming an extra that does not exist is worse than none.

    The names come from the live provider catalogue plus `deep`/`sqlite`, and
    `backend/pyproject.toml` is the only place they are actually declared — so
    they are checked against it rather than against a list retyped here.
    """
    import tomllib

    from openstategraph._extras import provider_extras

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as handle:
        declared = set(tomllib.load(handle)["project"]["optional-dependencies"])
    printable = set(provider_extras().values()) | {"deep", "sqlite"}
    assert printable <= declared, sorted(printable - declared)
