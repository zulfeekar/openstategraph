"""The `openstategraph` console script.

Every test invokes `cli.main(argv)` **directly** rather than shelling out. A
subprocess test proves the packaging and nothing about the behaviour, costs a
second each, and is the reason CLIs end up with three tested commands and four
untested ones. Packaging is pinned once, cheaply, in
`test_distribution_metadata.py`'s entry-point assertion.

Two things this module is really guarding:

- **The exit codes**, because they are the API that CI consumes. A validation
  failure that exits 0 is a broken gate that looks green.
- **`new` not being a second scaffold.** The CLI and `scripts/new_workflow.py`
  must produce the identical package, and the only way to guarantee that is for
  them to call the same function — so one test compares the two outputs
  byte-for-byte (modulo the timestamp).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from openstategraph import cli

REPO = Path(__file__).resolve().parents[2]


def node(node_id: str, type_: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": type_, "data": data, "position": {"x": 0, "y": 0}}


def edge(src: str, src_port: str, dst: str, dst_port: str) -> dict[str, Any]:
    return {
        "source": {"nodeId": src, "portId": src_port},
        "target": {"nodeId": dst, "portId": dst_port},
    }


LINEAR = {
    "version": 2,
    "name": "linear",
    "nodes": [node("in1", "input.text"), node("out1", "output.formatted")],
    "edges": [edge("in1", "text", "out1", "result")],
}

#: A node type the runtime does not implement. `tool.*` would NOT do here:
#: an unknown *tool* is a legal document with a loud warning, while an unknown
#: node type is the thing validation exists to refuse.
ORPHANED = {
    "version": 2,
    "name": "broken",
    "nodes": [node("in1", "input.text"), node("x1", "sorcery.divination")],
    "edges": [],
}


@pytest.fixture
def package(tmp_path: Path) -> Path:
    directory = tmp_path / "linear-pkg"
    directory.mkdir()
    (directory / "workflow.json").write_text(
        json.dumps({"version": 1, "name": "linear", "savedAt": "", "document": LINEAR})
    )
    return directory


class TestRun:
    def test_it_prints_the_answer(self, package: Path, capsys) -> None:
        code = cli.main(["run", str(package), "hello there"])

        assert code == cli.EXIT_OK
        assert capsys.readouterr().out.strip() == "hello there"

    def test_json_prints_the_whole_result(self, package: Path, capsys) -> None:
        code = cli.main(["run", str(package), "hello there", "--json"])

        payload = json.loads(capsys.readouterr().out)
        assert code == cli.EXIT_OK
        assert payload["answer"] == "hello there"
        assert payload["slug"] == "linear-pkg"
        assert payload["decisions"] == {} and payload["attempts"] == 0
        # The thread id is reported so a follow-up turn is actually possible.
        assert payload["thread_id"]

    def test_a_missing_package_fails_with_one(self, tmp_path: Path, capsys) -> None:
        code = cli.main(["run", str(tmp_path / "nope"), "q"])

        assert code == cli.EXIT_FAILURE
        assert "workflow.json" in capsys.readouterr().err

    def test_the_trace_file_flag_reaches_the_loader(self, package: Path, tmp_path: Path) -> None:
        trace = tmp_path / "traces" / "runs.jsonl"

        cli.main(["run", str(package), "hello there", "--trace-file", str(trace)])

        assert json.loads(trace.read_text().splitlines()[0])["slug"] == "linear-pkg"


class TestValidate:
    def test_a_good_package_exits_zero(self, package: Path, capsys) -> None:
        code = cli.main(["validate", str(package)])

        assert code == cli.EXIT_OK
        assert "VALID" in capsys.readouterr().out

    def test_it_accepts_the_json_file_directly(self, package: Path) -> None:
        assert cli.main(["validate", str(package / "workflow.json")]) == cli.EXIT_OK

    def test_findings_exit_one(self, tmp_path: Path, capsys) -> None:
        directory = tmp_path / "broken-pkg"
        directory.mkdir()
        (directory / "workflow.json").write_text(json.dumps({"document": ORPHANED}))

        code = cli.main(["validate", str(directory)])

        assert code == cli.EXIT_FAILURE
        assert "PROBLEMS FOUND" in capsys.readouterr().out

    def test_a_non_package_exits_one(self, tmp_path: Path) -> None:
        assert cli.main(["validate", str(tmp_path)]) == cli.EXIT_FAILURE


class TestGraph:
    def test_it_prints_mermaid_text(self, package: Path, capsys) -> None:
        code = cli.main(["graph", str(package)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_OK
        assert "graph" in out or "flowchart" in out

    def test_no_network_call_is_available_to_it(self, package: Path, capsys) -> None:
        """Mermaid *text* only. `draw_mermaid_png()` posts the user's graph to
        the Mermaid.Ink API, which is the one thing this command must not do."""
        cli.main(["graph", str(package), "--no-xray"])

        assert "mermaid.ink" not in capsys.readouterr().out


class TestNewIsNotASecondScaffold:
    """The duplication this ticket had to avoid: `scripts/new_workflow.py` and
    `openstategraph new` producing packages that agree today and drift later."""

    def _tree(self, root: Path) -> list[str]:
        return sorted(str(p.relative_to(root)) for p in root.rglob("*"))

    def test_it_creates_a_loadable_package(self, tmp_path: Path) -> None:
        code = cli.main(["new", "my-flow", "--root", str(tmp_path)])

        assert code == cli.EXIT_OK
        assert (tmp_path / "my-flow" / "workflow.json").is_file()

    def test_the_cli_and_the_script_produce_the_same_package(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_script_new_workflow", REPO / "scripts" / "new_workflow.py"
        )
        script = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(script)

        by_script = tmp_path / "script"
        by_cli = tmp_path / "cli"
        monkeypatch.setattr(script, "ROOT", by_script)
        monkeypatch.setattr(script.sys, "argv", ["new_workflow.py", "my-flow", "My Flow"])
        script.main()
        cli.main(["new", "my-flow", "My Flow", "--root", str(by_cli)])

        assert self._tree(by_script) == self._tree(by_cli)
        script_doc = json.loads((by_script / "my-flow" / "workflow.json").read_text())
        cli_doc = json.loads((by_cli / "my-flow" / "workflow.json").read_text())
        script_doc.pop("savedAt"), cli_doc.pop("savedAt")
        assert script_doc == cli_doc
        assert (by_script / "my-flow" / "AGENTS.md").read_text() == (
            by_cli / "my-flow" / "AGENTS.md"
        ).read_text()

    def test_team_and_the_team_script_agree_too(self, tmp_path: Path, monkeypatch) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_script_new_team", REPO / "scripts" / "new_team.py"
        )
        script = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(script)

        by_script = tmp_path / "script"
        by_cli = tmp_path / "cli"
        monkeypatch.setattr(script, "ROOT", by_script)
        monkeypatch.setattr(script.sys, "argv", ["new_team.py", "a-team"])
        script.main()
        cli.main(["new", "a-team", "--team", "--root", str(by_cli)])

        script_doc = json.loads((by_script / "a-team" / "workflow.json").read_text())
        cli_doc = json.loads((by_cli / "a-team" / "workflow.json").read_text())
        script_doc.pop("savedAt"), cli_doc.pop("savedAt")
        assert script_doc == cli_doc

    def test_a_bad_slug_exits_one(self, tmp_path: Path, capsys) -> None:
        code = cli.main(["new", "My Flow", "--root", str(tmp_path)])

        assert code == cli.EXIT_FAILURE
        assert "lowercase" in capsys.readouterr().err

    def test_an_existing_directory_is_never_overwritten(self, tmp_path: Path) -> None:
        cli.main(["new", "my-flow", "--root", str(tmp_path)])

        assert cli.main(["new", "my-flow", "--root", str(tmp_path)]) == cli.EXIT_FAILURE


class TestKnowledge:
    def test_list_prints_topics_with_their_hints(self, package: Path, capsys) -> None:
        (package / "knowledge").mkdir()
        (package / "knowledge" / "invoice.md").write_text("# One row per sale.\n\nbody")

        code = cli.main(["knowledge", "list", str(package)])

        assert code == cli.EXIT_OK
        assert "- invoice — One row per sale." in capsys.readouterr().out

    def test_list_says_so_when_there_are_none(self, package: Path, capsys) -> None:
        code = cli.main(["knowledge", "list", str(package)])

        assert code == cli.EXIT_OK
        assert "no knowledge topics" in capsys.readouterr().out

    def test_build_reports_the_four_counts(self, package: Path, capsys, monkeypatch) -> None:
        from openstategraph.api import knowledge_build

        monkeypatch.setattr(knowledge_build, "resolve_build_model", lambda *a, **k: object())
        monkeypatch.setattr(
            knowledge_build,
            "run_build",
            lambda *a, **k: {"written": ["invoice"], "skipped": [], "collisions": [], "warnings": []},
        )

        code = cli.main(["knowledge", "build", str(package)])

        out = capsys.readouterr().out
        assert code == cli.EXIT_OK
        assert "written: invoice" in out and "skipped: none" in out

    def test_an_unknown_source_exits_one(self, package: Path, capsys, monkeypatch) -> None:
        from openstategraph.api import knowledge_build

        monkeypatch.setattr(knowledge_build, "resolve_build_model", lambda *a, **k: object())

        code = cli.main(["knowledge", "build", str(package), "--source", "nowhere"])

        assert code == cli.EXIT_FAILURE
        assert "nowhere" in capsys.readouterr().err


class TestTheExtrasAnnounceThemselves:
    """A missing extra must name its own `pip install` line and exit 3 — not
    surface a bare `ModuleNotFoundError` the adopter has to map to an extra."""

    def test_serve_without_uvicorn(self, capsys, monkeypatch) -> None:
        import builtins

        real = builtins.__import__

        def refuse(name: str, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)

        code = cli.main(["serve"])

        assert code == cli.EXIT_MISSING_EXTRA
        assert "openstategraph[server]" in capsys.readouterr().err

    def test_mcp_without_the_sdk(self, capsys, monkeypatch) -> None:
        import builtins

        real = builtins.__import__

        def refuse(name: str, *args, **kwargs):
            if name == "mcp":
                raise ImportError("No module named 'mcp'")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)

        code = cli.main(["mcp"])

        assert code == cli.EXIT_MISSING_EXTRA
        assert "openstategraph[mcp]" in capsys.readouterr().err


class TestUsage:
    def test_no_command_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli.main([])

        assert excinfo.value.code == cli.EXIT_USAGE

    def test_an_unknown_command_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["teleport"])

        assert excinfo.value.code == cli.EXIT_USAGE

    def test_version_prints_the_package_version(self, capsys) -> None:
        import openstategraph

        with pytest.raises(SystemExit) as excinfo:
            cli.main(["--version"])

        assert excinfo.value.code == cli.EXIT_OK
        assert capsys.readouterr().out.strip() == openstategraph.__version__


class TestCwdIndependence:
    def test_every_path_comes_from_the_arguments(self, package: Path, tmp_path, monkeypatch) -> None:
        """A command that only works inside the checkout is a command an
        adopter cannot use."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        assert cli.main(["validate", str(package)]) == cli.EXIT_OK
        assert cli.main(["graph", str(package)]) == cli.EXIT_OK


class TestServe:
    """`openstategraph serve` — the command that opens the product.

    Scale-and-adopt ticket 01. uvicorn's own loop is stubbed out: what is being
    tested is the contract *around* it — which port, which URLs, and that the
    editor mount is switched on — not that uvicorn can serve HTTP.
    """

    @pytest.fixture
    def served(self, monkeypatch):
        """Captures the socket and config uvicorn would have run."""
        import uvicorn

        captured: dict[str, Any] = {}

        def fake_run(self, sockets=None) -> None:
            captured["config"] = self.config
            captured["sockets"] = sockets or []

        monkeypatch.setattr(uvicorn.Server, "run", fake_run)
        return captured

    def test_it_prints_the_editor_the_chat_and_the_api_urls_it_landed_on(
        self, served, capsys, monkeypatch
    ) -> None:
        monkeypatch.delenv("OPENSTATEGRAPH_SERVE_STATIC", raising=False)

        assert cli.main(["serve", "--port", "0"]) == cli.EXIT_OK

        port = served["sockets"][0].getsockname()[1]
        printed = capsys.readouterr().out
        assert f"http://127.0.0.1:{port}/\n" in printed
        assert f"http://127.0.0.1:{port}/chat" in printed
        assert f"http://127.0.0.1:{port}/api/health" in printed
        # The bound socket is handed to uvicorn, not a number re-bound later —
        # otherwise the port just printed could be gone by the time it starts.
        assert served["config"].port == port

    def test_serving_the_editor_is_what_serve_means(self, served, monkeypatch) -> None:
        monkeypatch.delenv("OPENSTATEGRAPH_SERVE_STATIC", raising=False)

        cli.main(["serve", "--port", "0"])

        assert os.environ["OPENSTATEGRAPH_SERVE_STATIC"] == "1"

    def test_an_explicit_opt_out_is_respected(self, served, monkeypatch) -> None:
        """API-only is a legitimate thing to ask for; `serve` must not overrule
        an environment that asked for it."""
        monkeypatch.setenv("OPENSTATEGRAPH_SERVE_STATIC", "0")

        cli.main(["serve", "--port", "0"])

        assert os.environ["OPENSTATEGRAPH_SERVE_STATIC"] == "0"

    def test_an_explicit_port_that_is_taken_fails_with_the_way_out(
        self, served, capsys
    ) -> None:
        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        try:
            code = cli.main(["serve", "--port", str(taken)])
        finally:
            held.close()

        assert code == cli.EXIT_FAILURE
        error = capsys.readouterr().err
        assert f"port {taken} is in use" in error
        assert "--port 0" in error
        assert "sockets" not in served  # nothing was started

    def test_no_port_flag_never_fails_because_8000_is_busy(
        self, served, monkeypatch
    ) -> None:
        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        monkeypatch.setattr("openstategraph.api.listening.DEFAULT_PORT", taken)
        try:
            code = cli.main(["serve"])
        finally:
            held.close()

        assert code == cli.EXIT_OK
        assert served["sockets"][0].getsockname()[1] != taken

    def test_the_browser_stays_shut_unless_asked(self, served, monkeypatch) -> None:
        opened: list[str] = []
        import webbrowser

        monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

        cli.main(["serve", "--port", "0"])
        assert opened == []

        cli.main(["serve", "--port", "0", "--open"])
        assert opened and opened[0].endswith("/")

    def test_the_default_bind_is_loopback_and_the_help_says_why(self) -> None:
        """0.0.0.0 by default would publish a process that holds provider API
        keys and has no authentication."""
        parser = cli.build_parser()
        serve = parser.parse_args(["serve"])

        assert serve.host == "127.0.0.1"
        assert serve.port is None
        help_text = _subcommand_help(parser, "serve")
        assert "127.0.0.1" in help_text
        assert "authentication" in help_text


def _subcommand_help(parser: "argparse.ArgumentParser", name: str) -> str:
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action.choices[name].format_help()
