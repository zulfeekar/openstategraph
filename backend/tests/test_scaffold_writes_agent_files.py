"""`init` is the door that points a coding agent at this project's server.

`osg-agent-experience/25`, slice 2. `docs/mcp.md` used to hand a reader a JSON
block to paste, once per agent — so the command line existed in four copies in
every adopting repository and in the docs, and nothing could notice when they
disagreed. `init` writes them now, from the one `ServerDescriptor`.

The report is the other half. `init` already prints a line per thing it wrote
with a sentence saying which of created / merged / current / kept happened, and
these four join that block in the same voice. The last line is the sentence a
reader is supposed to type next, because "your agent now knows about this
project" is useless without "and here is how you address it".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph import cli
from openstategraph.agent_config import AgentFileState
from openstategraph.scaffold import NEXT_SENTENCE, init_project

FOUR = {
    ".mcp.json",
    ".vscode/mcp.json",
    ".cursor/mcp.json",
    ".codex/config.toml",
}


class TestInitWritesThem:
    def test_an_empty_directory_gets_all_four(self, tmp_path: Path) -> None:
        target = tmp_path / "demo"

        result = init_project(target, label="demo")

        assert {str(a.path.relative_to(target)) for a in result.agent_files} == {
            str(Path(p)) for p in FOUR
        }
        for action in result.agent_files:
            assert action.state is AgentFileState.CREATED
            assert action.path.is_file()

    def test_a_foreign_vscode_file_is_merged_rather_than_replaced(self, tmp_path: Path) -> None:
        target = tmp_path / "demo"
        (target / ".vscode").mkdir(parents=True)
        (target / ".vscode" / "mcp.json").write_text(
            json.dumps({"servers": {"theirs": {"command": "their-server"}}}, indent=2),
            encoding="utf-8",
        )

        result = init_project(target, label="demo")

        states = {str(a.path.relative_to(target)): a.state for a in result.agent_files}
        assert states[str(Path(".vscode/mcp.json"))] is AgentFileState.MERGED
        assert states[".mcp.json"] is AgentFileState.CREATED
        document = json.loads((target / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
        assert set(document["servers"]) == {"theirs", "openstategraph"}


class TestTheReport:
    def test_it_names_every_file_and_its_state_and_ends_with_the_next_sentence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cli.main(["init", str(tmp_path / "demo")])

        assert code == 0
        printed = capsys.readouterr().out
        for relative in FOUR:
            assert relative in printed, f"{relative} was written and never mentioned"
        assert printed.rstrip().endswith(NEXT_SENTENCE)

    def test_a_second_init_reports_current_four_times(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "demo"
        cli.main(["init", str(target)])
        capsys.readouterr()

        cli.main(["init", str(target), "--force"])

        printed = capsys.readouterr().out
        agent_lines = [line for line in printed.splitlines() if any(f in line for f in FOUR)]
        assert len(agent_lines) == 4, printed
        for line in agent_lines:
            assert "current" in line, line
