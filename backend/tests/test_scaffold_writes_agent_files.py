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

from openstategraph import agent_config, cli
from openstategraph._extras import install_hint
from openstategraph.agent_config import AgentFileState
from openstategraph.scaffold import NEXT_SENTENCE, RESTART_SENTENCE, init_project

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


class TestTheReportSaysWhatIsStillLeftToDo:
    """`osg-agent-experience/24`. The report is the requirement's last sentence
    and a stranger's first screen, and it had two silences.

    **The files are read at startup.** `init` writes four MCP configs, two
    skill roots and `AGENTS.md` into a directory a coding agent is very often
    already running in — that is the whole shape of the command, typed inside
    the session that will use it. Every one of those is read when the agent
    starts, so the agent that just ran `init` has seen none of them, and the
    report finished by telling the developer to say *"use OpenStateGraph"* to
    an agent that would answer as if nothing had been installed. One sentence
    is the whole fix.

    **The server those four files name may not be installed.** Each entry runs
    `openstategraph mcp`, which needs the `[mcp]` extra (`19`). Without it the
    files are written, the report says the agent "can reach this project's MCP
    server", and the failure lands later, inside the agent's own start-up log,
    as a command that exits non-zero. `init` can see it now, which is the
    friendliest possible moment, and it names the install line rather than the
    symptom.

    Both are printed **conditionally and truthfully**: nothing to re-scan means
    no restart line, and an installed extra says nothing at all. A report that
    always prints its advice is one a reader learns to skip.
    """

    def test_it_says_to_restart_the_agent_when_it_wrote_something(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.main(["init", str(tmp_path / "demo")])

        # Collapsed: the line is wrapped to the report's own column, like the
        # model line beside it, so the newline is a layout fact rather than a
        # copy one.
        printed = " ".join(capsys.readouterr().out.split())
        assert " ".join(RESTART_SENTENCE.split()) in printed, printed

    def test_a_second_init_that_changed_nothing_stays_quiet(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The other direction, and the reason the line is worth reading when
        it does appear: the agent has already scanned what is there."""
        target = tmp_path / "demo"
        cli.main(["init", str(target)])
        capsys.readouterr()

        cli.main(["init", str(target), "--force"])

        assert " ".join(RESTART_SENTENCE.split()) not in " ".join(capsys.readouterr().out.split())

    def test_it_names_the_extra_when_the_server_those_files_name_is_absent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(agent_config, "find_spec", lambda name: None)

        cli.main(["init", str(tmp_path / "demo")])

        printed = capsys.readouterr().out
        assert install_hint("mcp") in printed, printed
        assert "openstategraph mcp" in printed, printed

    def test_an_installed_extra_is_not_announced(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(agent_config, "find_spec", lambda name: object())

        cli.main(["init", str(tmp_path / "demo")])

        assert install_hint("mcp") not in capsys.readouterr().out

    def test_the_cli_page_says_the_same_two_things(self) -> None:
        """`24`'s second done-when. The printed report and the page that
        describes it are two descriptions of one behaviour, and the install
        line is the half a reader might copy — so it is asserted against
        `install_hint`, not transcribed."""
        page = (
            Path(__file__).resolve().parents[2] / "docs" / "cli.md"
        ).read_text(encoding="utf-8")
        section = page.split("It also points your coding agent", 1)[1]

        assert install_hint("mcp") in section, "the page never names the install line the report prints"
        assert "restart" in section, "the page never says the files are read at start-up"
