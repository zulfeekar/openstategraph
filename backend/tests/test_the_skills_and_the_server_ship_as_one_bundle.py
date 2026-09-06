"""One descriptor, five renderings, and the bundle is the fifth.

`osg-agent-experience/28`. `init` writes four agent-config files from
`agent_config.ServerDescriptor` and installs the wheel's three skills into
two skill roots. A developer on an agent that installs *Agent Plugins* has
neither door: `plugin_interop.export_plugin` speaks that format, but it
speaks it about a **workflow package**, which has no server, so it emits no
`mcp.json` at all.

`export_toolkit` is the second road to the same place — this installation's
skills and its MCP server as one directory somebody can install. The whole
risk of a second road is that it becomes a second copy of the command line,
which is the defect `agent_config` exists to have fixed once. So the test
that matters is the byte-for-byte one below: the bundle's server entry and
the entry `init` writes into `.mcp.json` are rendered from one descriptor,
and disagreeing about a single character fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph.agent_config import (
    DEFAULT_ENV,
    AgentFileState,
    ServerDescriptor,
    render_all,
)
from openstategraph.bundled_skills import BUNDLED_SKILLS, bundled_skill_files
from openstategraph.plugin_interop import (
    MCP_SCHEMA_ID,
    PLUGIN_SCHEMA_ID,
    TOOLKIT_PLUGIN_NAME,
    export_toolkit,
    write_export,
)


@pytest.fixture
def bundle() -> dict[str, object]:
    export = export_toolkit()
    return json.loads(export.files["mcp.json"])


class TestOneCommandLineFiveRenderings:
    """The `Done when` clause: the bundle and the four `init` files agree."""

    def test_the_server_entry_is_the_one_init_writes(self, tmp_path: Path) -> None:
        render_all(tmp_path)
        written = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]

        export = export_toolkit()
        ours = json.loads(export.files["mcp.json"])["mcpServers"]

        assert set(ours) == set(written) == {"openstategraph"}
        theirs = written["openstategraph"]
        mine = ours["openstategraph"]
        for key in ("command", "args", "env"):
            assert json.dumps(mine[key]) == json.dumps(theirs[key]), key

    def test_a_changed_descriptor_moves_both(self, tmp_path: Path) -> None:
        """The agreement is a shared source, not two matching literals."""
        server = ServerDescriptor(command="osg", args=("mcp", "--quiet"))
        actions = render_all(tmp_path, server)
        assert {action.state for action in actions} == {AgentFileState.CREATED}
        written = json.loads((tmp_path / ".cursor/mcp.json").read_text())
        entry = json.loads(export_toolkit(server=server).files["mcp.json"])
        assert entry["mcpServers"]["openstategraph"]["command"] == "osg"
        assert (
            entry["mcpServers"]["openstategraph"]["args"]
            == written["mcpServers"]["openstategraph"]["args"]
        )

    def test_the_safe_environment_travels(self, bundle: dict[str, object]) -> None:
        """`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0` is the line a hand-copy drops."""
        entry = bundle["mcpServers"]["openstategraph"]  # type: ignore[index]
        assert entry["env"] == dict(DEFAULT_ENV)


class TestTheBundleIsAValidPluginDirectory:
    def test_the_manifest_is_the_closed_shape(self) -> None:
        manifest = export_toolkit().manifest
        assert manifest["$schema"] == PLUGIN_SCHEMA_ID
        assert manifest["name"] == TOOLKIT_PLUGIN_NAME
        assert len(manifest["description"]) <= 1024
        assert set(manifest) <= {
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

    def test_mcp_json_carries_only_the_two_permitted_keys(
        self, bundle: dict[str, object]
    ) -> None:
        assert set(bundle) == {"$schema", "mcpServers"}
        assert bundle["$schema"] == MCP_SCHEMA_ID

    def test_the_entry_names_its_transport(self, bundle: dict[str, object]) -> None:
        entry = bundle["mcpServers"]["openstategraph"]  # type: ignore[index]
        assert entry["type"] == "stdio"

    def test_no_secret_travels_in_env(self, bundle: dict[str, object]) -> None:
        """§7.2.3: `env` is package data, so a secret in it is published."""
        entry = bundle["mcpServers"]["openstategraph"]  # type: ignore[index]
        for name, value in entry["env"].items():
            assert "KEY" not in name and "TOKEN" not in name and "SECRET" not in name
            assert value == "0"

    def test_every_bundled_skill_is_a_directory_with_its_sheet(self) -> None:
        files = export_toolkit().files
        for name in BUNDLED_SKILLS:
            assert f"skills/{name}/SKILL.md" in files
            assert files[f"skills/{name}/SKILL.md"].startswith("---\n")

    def test_a_reference_page_beside_a_sheet_travels_with_it(self) -> None:
        """A skill is a tree, not a file — the lesson `25` slice 5 paid for."""
        files = export_toolkit().files
        carried = {
            Path(path).name
            for path in files
            if path.startswith("skills/openstategraph/references/")
        }
        on_disk = {p.name for p in (BUNDLED_SKILLS["openstategraph"] / "references").glob("*.md")}
        assert on_disk <= carried
        assert "engineering-rules.md" in carried, "the generated page `init` installs too"

    def test_the_bundle_carries_exactly_what_init_installs(self) -> None:
        """One inventory, so a fourth skill cannot reach one door and not the other."""
        files = export_toolkit().files
        assert {path for path in files if path.startswith("skills/")} == {
            f"skills/{relative}" for _name, relative in bundled_skill_files()
        }

    def test_it_carries_no_workflow_and_says_so(self) -> None:
        export = export_toolkit()
        assert not [path for path in export.files if path.startswith("org.openstategraph/")]
        assert any("workflow" in note for note in export.notes)

    def test_it_writes_where_it_is_told(self, tmp_path: Path) -> None:
        written = write_export(export_toolkit(), tmp_path / "bundle")
        assert (written / "plugin.json").is_file()
        assert (written / "mcp.json").is_file()
        assert (written / "skills/kanban-patrol/SKILL.md").is_file()


class TestTheCommandLineDoor:
    """`openstategraph export toolkit` — a wrapper, and these keep it one.

    Assertions are on disk and on the exit code only; the mapping itself is
    the classes above.
    """

    def test_it_writes_the_bundle_where_it_is_told(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from openstategraph import cli

        out = tmp_path / "bundle"
        assert cli.main(["export", "toolkit", "--out", str(out)]) == 0
        assert json.loads((out / "mcp.json").read_text())["mcpServers"]
        assert (out / "plugin.json").is_file()
        captured = capsys.readouterr()
        assert "plugin exported" in captured.out
        assert "note:" in captured.err, "the honest edges are printed, not only returned"

    def test_it_refuses_a_destination_that_holds_files(self, tmp_path: Path) -> None:
        out = tmp_path / "taken"
        out.mkdir()
        (out / "somebody-elses.txt").write_text("mine")
        from openstategraph import cli

        assert cli.main(["export", "toolkit", "--out", str(out)]) == 1
        assert (out / "somebody-elses.txt").read_text() == "mine"
        assert not (out / "plugin.json").exists()
