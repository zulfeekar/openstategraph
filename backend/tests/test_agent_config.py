"""One command line, four agents, and never a clobbered file.

`osg-agent-experience/25`, slice 2 (the shapes and the merge rule are
`osg-agent-experience/27`'s research note). Four coding agents read four
different files for a project-local stdio MCP server, with two different
top-level keys and one of them in TOML. Hand-pasting the block into each is
four copies of one command line waiting to drift, so a single
`ServerDescriptor` is the source of truth and the renderers are thin.

The half that matters more is what happens when a file is already there. An
agent config is a machine registry with a natural merge key, so the rule is
*merge, never refuse* — insert our one entry, preserve every other server and
every unknown key. The exception is an `openstategraph` entry that already
exists and **differs**: that is somebody's deliberate customisation (usually
`OPENSTATEGRAPH_MCP_ALLOW_RUNS=1`) and overwriting it would silently disarm
their choice, so it is `KEPT` with a note. A file we cannot parse is `KEPT`
too — a writer that repairs somebody's broken JSON by replacing it is a
writer that eats their work.
"""

from __future__ import annotations

import json
from pathlib import Path

from openstategraph.agent_config import (
    AgentFileState,
    ServerDescriptor,
    merge_codex_toml,
    merge_json_servers,
    render_all,
)

SERVER = ServerDescriptor()

#: Where each agent looks, and under which key. The research note's table,
#: as data — a renderer that moves a file fails here rather than in a user's
#: editor six weeks later.
EXPECTED = {
    "claude-code": (".mcp.json", "mcpServers"),
    "vscode": (".vscode/mcp.json", "servers"),
    "cursor": (".cursor/mcp.json", "mcpServers"),
    "codex": (".codex/config.toml", None),
}


def _by_agent(project: Path) -> dict[str, object]:
    return {action.agent: action for action in render_all(project)}


class TestCreated:
    def test_all_four_files_are_written_into_an_empty_project(self, tmp_path: Path) -> None:
        actions = _by_agent(tmp_path)

        assert set(actions) == set(EXPECTED)
        for agent, (relative, _key) in EXPECTED.items():
            action = actions[agent]
            assert action.state is AgentFileState.CREATED
            assert action.path == tmp_path / relative
            assert action.path.is_file(), f"{relative} was reported and not written"

    def test_each_json_file_carries_our_entry_under_the_key_that_agent_reads(
        self, tmp_path: Path
    ) -> None:
        render_all(tmp_path)

        for _agent, (relative, servers_key) in EXPECTED.items():
            if servers_key is None:
                continue
            document = json.loads((tmp_path / relative).read_text(encoding="utf-8"))
            entry = document[servers_key]["openstategraph"]
            assert entry["command"] == "openstategraph"
            assert entry["args"] == ["mcp"]
            assert entry["env"]["OPENSTATEGRAPH_MCP_ALLOW_RUNS"] == "0"

    def test_the_codex_file_is_a_toml_table_under_mcp_servers(self, tmp_path: Path) -> None:
        import tomllib

        render_all(tmp_path)

        text = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "[mcp_servers.openstategraph]" in text
        table = tomllib.loads(text)["mcp_servers"]["openstategraph"]
        assert table == {
            "command": "openstategraph",
            "args": ["mcp"],
            "env": {"OPENSTATEGRAPH_MCP_ALLOW_RUNS": "0"},
        }


class TestMerged:
    """A file that is already there keeps everything it had."""

    def test_a_foreign_server_survives_in_every_json_file(self, tmp_path: Path) -> None:
        for _agent, (relative, servers_key) in EXPECTED.items():
            if servers_key is None:
                continue
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "inputs": [{"id": "token"}],
                        servers_key: {"theirs": {"command": "their-server"}},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        actions = _by_agent(tmp_path)

        for agent, (relative, servers_key) in EXPECTED.items():
            if servers_key is None:
                continue
            assert actions[agent].state is AgentFileState.MERGED
            document = json.loads((tmp_path / relative).read_text(encoding="utf-8"))
            assert document["inputs"] == [{"id": "token"}], "an unknown top-level key was dropped"
            assert document[servers_key]["theirs"] == {"command": "their-server"}
            assert document[servers_key]["openstategraph"]["args"] == ["mcp"]

    def test_a_foreign_codex_table_and_its_comments_survive(self, tmp_path: Path) -> None:
        import tomllib

        path = tmp_path / ".codex" / "config.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            '# my own notes, which a TOML rewriter would eat\nmodel = "gpt-5"\n\n'
            '[mcp_servers.theirs]\ncommand = "their-server"\n',
            encoding="utf-8",
        )

        actions = _by_agent(tmp_path)

        text = path.read_text(encoding="utf-8")
        assert actions["codex"].state is AgentFileState.MERGED
        assert "# my own notes, which a TOML rewriter would eat" in text
        data = tomllib.loads(text)
        assert data["model"] == "gpt-5"
        assert data["mcp_servers"]["theirs"] == {"command": "their-server"}
        assert data["mcp_servers"]["openstategraph"]["command"] == "openstategraph"

    def test_the_appended_table_is_valid_toml_when_the_file_has_no_trailing_newline(
        self, tmp_path: Path
    ) -> None:
        text, state = merge_codex_toml('model = "gpt-5"', SERVER)

        import tomllib

        assert state is AgentFileState.MERGED
        assert tomllib.loads(text)["mcp_servers"]["openstategraph"]["args"] == ["mcp"]


class TestCurrent:
    def test_a_second_render_changes_nothing_and_says_so(self, tmp_path: Path) -> None:
        render_all(tmp_path)
        before = {
            relative: (tmp_path / relative).read_text(encoding="utf-8")
            for relative, _key in EXPECTED.values()
        }

        actions = _by_agent(tmp_path)

        for agent in EXPECTED:
            assert actions[agent].state is AgentFileState.CURRENT, agent
        for relative, text in before.items():
            assert (tmp_path / relative).read_text(encoding="utf-8") == text


class TestKept:
    def test_an_openstategraph_entry_that_differs_is_left_alone_with_a_note(
        self, tmp_path: Path
    ) -> None:
        """`ALLOW_RUNS=1` is the case this protects: a deliberate choice that
        a silent overwrite would disarm."""
        theirs = {
            "command": "openstategraph",
            "args": ["mcp"],
            "env": {"OPENSTATEGRAPH_MCP_ALLOW_RUNS": "1"},
        }
        for _agent, (relative, servers_key) in EXPECTED.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if servers_key is None:
                path.write_text(
                    "[mcp_servers.openstategraph]\n"
                    'command = "openstategraph"\nargs = ["mcp"]\n'
                    'env = { OPENSTATEGRAPH_MCP_ALLOW_RUNS = "1" }\n',
                    encoding="utf-8",
                )
            else:
                path.write_text(
                    json.dumps({servers_key: {"openstategraph": theirs}}, indent=2),
                    encoding="utf-8",
                )
        before = {
            relative: (tmp_path / relative).read_text(encoding="utf-8")
            for relative, _key in EXPECTED.values()
        }

        actions = _by_agent(tmp_path)

        for agent in EXPECTED:
            assert actions[agent].state is AgentFileState.KEPT, agent
            assert actions[agent].note, f"{agent} was kept and said nothing about why"
        for relative, text in before.items():
            assert (tmp_path / relative).read_text(encoding="utf-8") == text

    def test_a_malformed_file_is_never_overwritten_and_the_note_carries_the_error(
        self, tmp_path: Path
    ) -> None:
        for _agent, (relative, servers_key) in EXPECTED.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{ this is not", encoding="utf-8")

        actions = _by_agent(tmp_path)

        for agent in EXPECTED:
            assert actions[agent].state is AgentFileState.KEPT, agent
            assert actions[agent].note, agent
            assert (tmp_path / EXPECTED[agent][0]).read_text(encoding="utf-8") == "{ this is not"


class TestTheMergeRuleItself:
    """The two merge functions, without a filesystem."""

    def test_an_absent_servers_key_is_created_rather_than_refused(self) -> None:
        merged, state = merge_json_servers(
            {"inputs": []}, "openstategraph", {"command": "x"}, servers_key="servers"
        )

        assert state is AgentFileState.MERGED
        assert merged == {"inputs": [], "servers": {"openstategraph": {"command": "x"}}}

    def test_an_identical_entry_is_current(self) -> None:
        entry = {"command": "x"}

        _merged, state = merge_json_servers(
            {"mcpServers": {"openstategraph": entry}},
            "openstategraph",
            dict(entry),
            servers_key="mcpServers",
        )

        assert state is AgentFileState.CURRENT

    def test_a_servers_key_that_is_not_an_object_is_kept(self) -> None:
        """Somebody's file, shaped in a way we do not understand. Read it
        tolerantly, trust it strictly: report, never repair."""
        _merged, state = merge_json_servers(
            {"mcpServers": ["theirs"]}, "openstategraph", {}, servers_key="mcpServers"
        )

        assert state is AgentFileState.KEPT
