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


class TestTemplates:
    """`--template` is the adoption surface (scale-and-adopt ticket 04): a
    stranger with an empty folder needs a starting point they did not have to
    invent. The catalogue itself is tested in `test_templates.py`; what belongs
    here is the *command line* over it, including the two exit codes."""

    def test_the_default_is_minimal_so_a_first_run_is_one_model_call(
        self, tmp_path: Path
    ) -> None:
        cli.main(["new", "my-flow", "--root", str(tmp_path)])
        document = json.loads((tmp_path / "my-flow" / "workflow.json").read_text())["document"]

        assert [n["type"] for n in document["nodes"]] == [
            "input.text",
            "agent.llm",
            "output.formatted",
        ]

    def test_a_named_template_is_what_gets_scaffolded(self, tmp_path: Path) -> None:
        code = cli.main(["new", "my-flow", "--template", "routed-qa", "--root", str(tmp_path)])
        document = json.loads((tmp_path / "my-flow" / "workflow.json").read_text())["document"]

        assert code == cli.EXIT_OK
        assert any(n["type"] == "route.classifier" for n in document["nodes"])

    def test_an_unknown_template_exits_two_and_names_the_valid_ones(self, capsys) -> None:
        """argparse's own `choices` error — exit 2, not 1: a typo in a flag is
        a usage error, and CI must be able to tell it from a failed run."""
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "my-flow", "--template", "wishful"])

        assert caught.value.code == cli.EXIT_USAGE
        message = capsys.readouterr().err
        assert "routed-qa" in message and "minimal" in message and "team" in message

    def test_list_templates_prints_a_name_and_a_line_for_each(self, capsys) -> None:
        code = cli.main(["new", "--list-templates"])

        assert code == cli.EXIT_OK
        printed = capsys.readouterr().out
        for name in ("minimal", "routed-qa", "team"):
            assert name in printed
        assert "(default)" in printed
        assert len(printed.strip().splitlines()) == 3

    def test_new_without_a_slug_is_a_usage_error(self, capsys) -> None:
        code = cli.main(["new"])

        assert code == cli.EXIT_USAGE
        assert "slug" in capsys.readouterr().err

    def test_team_still_works_and_says_what_replaced_it(self, tmp_path: Path, capsys) -> None:
        """Gentle deprecation: every script and README line that already says
        `--team` keeps working, and its user is told once where to go next."""
        code = cli.main(["new", "a-team", "--team", "--root", str(tmp_path)])
        document = json.loads((tmp_path / "a-team" / "workflow.json").read_text())["document"]

        assert code == cli.EXIT_OK
        assert any(n["type"] == "orchestrate.supervisor" for n in document["nodes"])
        assert "--template team" in capsys.readouterr().err

    def test_team_and_a_different_template_is_a_usage_error(self, tmp_path: Path) -> None:
        code = cli.main(
            ["new", "a-team", "--team", "--template", "routed-qa", "--root", str(tmp_path)]
        )

        assert code == cli.EXIT_USAGE
        assert not (tmp_path / "a-team").exists()

    def test_every_template_scaffolds_a_package_the_cli_can_validate(
        self, tmp_path: Path
    ) -> None:
        """The end-to-end claim, through the commands rather than the API: a
        template that does not survive `new` + `validate` is worse than none."""
        from openstategraph import templates

        for name in templates.names():
            cli.main(["new", name, "--template", name, "--root", str(tmp_path)])

            assert cli.main(["validate", str(tmp_path / name)]) == cli.EXIT_OK


class TestKnowledge:
    def test_list_prints_topics_with_their_hints(self, package: Path, capsys) -> None:
        (package / "knowledge").mkdir()
        (package / "knowledge" / "invoice.md").write_text("# One row per sale.\n\nbody")

        code = cli.main(["knowledge", "list", str(package)])

        assert code == cli.EXIT_OK
        assert "- invoice — One row per sale." in capsys.readouterr().out

    def test_list_names_the_owner_and_badges_a_moved_source(
        self, package: Path, capsys
    ) -> None:
        """Ownership and staleness are on disk; a terminal can now read them.

        Both facts were recorded from the first build and surfaced only by the
        editor's curation panel — which is the wrong place for the one
        question a developer checking their second brain asks: *is any of this
        out of date?*
        """
        from openstategraph.knowledge_builders import GENERATED_MARKER

        knowledge = package / "knowledge"
        knowledge.mkdir()
        (knowledge / "yours.md").write_text("Hand-written wisdom.\n")
        (knowledge / "moved.md").write_text(
            f"{GENERATED_MARKER} source=sql hash=000000000000 -->\n\nA table.\n"
        )

        # A doc whose source no longer hashes the same is badged, not rewritten.
        import openstategraph.api.knowledge_curation as curation

        original = curation.current_source_hashes
        curation.current_source_hashes = lambda *a, **k: {"moved": "ffffffffffff"}
        try:
            assert cli.main(["knowledge", "list", str(package)]) == cli.EXIT_OK
        finally:
            curation.current_source_hashes = original

        out = capsys.readouterr().out
        assert "- yours — Hand-written wisdom.  [yours]" in out
        assert "[generated: sql, STALE]" in out

    def test_list_says_so_when_there_are_none(self, package: Path, capsys) -> None:
        code = cli.main(["knowledge", "list", str(package)])

        assert code == cli.EXIT_OK
        assert "no knowledge topics" in capsys.readouterr().out

    def test_list_refuses_a_package_that_is_not_there(self, tmp_path: Path, capsys) -> None:
        """An absent thing must not be reported as an empty thing.

        The same defect class as the file watcher's: `knowledge list
        /typo/path` printed "no knowledge topics — build them with…" and
        exited 0, so the answer to "where did my knowledge go?" was a
        suggestion to rebuild it into a directory that does not exist.
        """
        missing = tmp_path / "not-here"

        code = cli.main(["knowledge", "list", str(missing)])

        captured = capsys.readouterr()
        assert code == cli.EXIT_FAILURE
        assert "no such package" in captured.err
        assert str(missing) in captured.err
        assert "no knowledge topics" not in captured.out

    def test_list_refuses_a_directory_that_is_no_workflow_package(
        self, tmp_path: Path, capsys
    ) -> None:
        """A real directory that is not a package is a third answer again — and
        the wording is `knowledge build`'s, because it is the same question."""
        plain = tmp_path / "just-a-folder"
        plain.mkdir()

        code = cli.main(["knowledge", "list", str(plain)])

        captured = capsys.readouterr()
        assert code == cli.EXIT_FAILURE
        assert "is that a workflow package?" in captured.err
        assert "no knowledge topics" not in captured.out

    def test_list_still_reads_a_bare_knowledge_directory(self, tmp_path: Path, capsys) -> None:
        """A store with docs but no `workflow.json` is a real store, and stays
        listable — being unable to compute staleness is not being absent."""
        store = tmp_path / "loose"
        (store / "knowledge").mkdir(parents=True)
        (store / "knowledge" / "invoice.md").write_text("# One row per sale.\n")

        code = cli.main(["knowledge", "list", str(store)])

        assert code == cli.EXIT_OK
        assert "- invoice — One row per sale." in capsys.readouterr().out

    def test_list_refuses_a_knowledge_dir_that_is_not_there(
        self, package: Path, tmp_path: Path, capsys
    ) -> None:
        missing = tmp_path / "elsewhere"

        code = cli.main(["knowledge", "list", str(package), "--knowledge-dir", str(missing)])

        captured = capsys.readouterr()
        assert code == cli.EXIT_FAILURE
        assert "no such knowledge directory" in captured.err
        assert "no knowledge topics" not in captured.out

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
