"""`init`'s four agent configs name a command that actually starts.

`docs-onramp/10`. Every rendered entry carried the bare name:

    { "mcpServers": { "openstategraph": { "command": "openstategraph", ... } } }

resolved against the *agent's* `PATH`. That is right for the `uv tool install`
route README leads with, where the shim lands in `~/.local/bin`. It is wrong for
every other install this project documents — a project venv, `pip install -e
"backend[…]"` from a checkout, `pipx` in a shell nobody re-sourced — where the
name is not on that `PATH` and the server never starts.

The failure mode is the bad one: the agent shows no tools and says nothing,
which reads as *OpenStateGraph's MCP layer does not work* rather than *this path
is wrong*. README calls that door "the whole interface".

## Which half of the ticket's "either" was taken, and why both are here

Both. The command is **resolved at init time** — the bare name when the
environment `init` runs in can resolve it, and this interpreter's own console
script otherwise — and `init` **says which**, in the block where it already
tells you to restart your agent. The resolution alone is silent about a real
consequence (an absolute path pins the config to this checkout's venv); the
sentence alone leaves the server not starting.

## The case nobody runs by accident

The not-on-`PATH` case is built rather than waited for: `shutil.which` is made
to answer `None` and a console script is planted under a `sys.prefix` this test
owns. A test that only runs on a machine where the name happens to be missing
is a test that runs nowhere.

`test_agent_config.py` covers the rendering itself and passes an explicit
descriptor for exactly this reason — it asserts what the files *look like*, and
after this ticket that is no longer a fact about the machine running it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from openstategraph.agent_config import (
    AGENT_FILES,
    ServerDescriptor,
    command_note,
    render_all,
    resolve_server_command,
)


@pytest.fixture
def not_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A venv install whose `bin/` the agent's `PATH` does not carry."""
    prefix = tmp_path / "venv"
    (prefix / "bin").mkdir(parents=True)
    script = prefix / "bin" / "openstategraph"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "argv", ["openstategraph", "init", "."])
    monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)
    return script


@pytest.fixture
def on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name, *_a, **_k: f"/somewhere/bin/{name}")


class TestResolution:
    def test_a_name_the_environment_resolves_is_left_alone(self, on_path: None) -> None:
        """The bare name is the *better* answer when it works: it survives the
        venv being rebuilt, and it is what the documented `uv tool` route
        produces."""
        assert resolve_server_command() == "openstategraph"

    def test_a_venv_install_gets_its_own_console_script(self, not_on_path: Path) -> None:
        resolved = resolve_server_command()

        assert resolved == str(not_on_path)
        assert Path(resolved).is_absolute()

    def test_an_installation_with_no_script_at_all_keeps_the_bare_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Nothing to point at is not a licence to invent a path. An entry
        naming the bare name is at least the one `missing_server_note` already
        has a sentence about."""
        monkeypatch.setattr(sys, "prefix", str(tmp_path / "empty"))
        monkeypatch.setattr(sys, "argv", ["-c"])
        monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)

        assert resolve_server_command() == "openstategraph"


class TestTheFilesInitWrites:
    def test_all_four_carry_the_absolute_path_when_the_name_is_not_resolvable(
        self, not_on_path: Path, tmp_path: Path
    ) -> None:
        """One descriptor still drives four files — asserted as *one* value
        across all of them, so a future fix that resolves per renderer is red."""
        project = tmp_path / "project"
        project.mkdir()

        render_all(project)

        commands = set()
        for _agent, relative, servers_key in AGENT_FILES:
            text = (project / relative).read_text(encoding="utf-8")
            if servers_key is None:
                import tomllib

                commands.add(tomllib.loads(text)["mcp_servers"]["openstategraph"]["command"])
            else:
                commands.add(json.loads(text)[servers_key]["openstategraph"]["command"])

        assert commands == {str(not_on_path)}

    def test_all_four_carry_the_bare_name_when_it_resolves(
        self, on_path: None, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()

        render_all(project)

        document = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
        assert document["mcpServers"]["openstategraph"]["command"] == "openstategraph"


class TestWhatInitSays:
    def test_the_bare_name_is_reported_as_a_path_lookup(self, on_path: None) -> None:
        note = command_note(ServerDescriptor())
        assert "PATH" in note

    def test_a_bare_name_nothing_can_resolve_is_not_reported_as_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Found live, walking the fix as a user: with `~/.local/bin` off the
        `PATH` and no console script beside the interpreter, the resolver
        correctly kept the bare name and the note said *found on PATH*, which
        was false. Two outcomes were being described by one test — whether the
        command is absolute — and there are three.
        """
        monkeypatch.setattr(sys, "prefix", str(tmp_path / "empty"))
        monkeypatch.setattr(sys, "argv", ["-c"])
        monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)

        note = command_note(ServerDescriptor())

        assert "found on PATH" not in note
        assert "not on" in note

    def test_an_absolute_path_is_reported_as_one_and_says_what_it_costs(
        self, not_on_path: Path
    ) -> None:
        note = command_note(ServerDescriptor(command=str(not_on_path)))
        assert str(not_on_path) in note
        assert "PATH" in note

    def test_init_prints_it(
        self, not_on_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The whole point is the reader seeing it, so the assertion is on
        `init`'s own stdout rather than on the function that composes it."""
        from openstategraph import cli

        project = tmp_path / "project"
        project.mkdir()

        code = cli.main(["init", str(project)])

        assert code == 0
        assert str(not_on_path) in capsys.readouterr().out
