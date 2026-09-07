"""`openstategraph export plugin` — the command line for a seam that had none.

`export-and-eject` 07. `plugin_interop.export_plugin` shipped reachable from
HTTP (`GET /api/workflows/{slug}/plugin-export`) and from the MCP tool of the
same name, and from no command at all — so the one audience that would use an
export in anger, a script in CI, could not reach it.

The command is a **wrapper**, and these tests are written so that it stays one:
they assert on what lands on disk and on the exit code, never on the shape of
`PluginExport`. `test_plugin_interop.py` owns the crossing itself; if a
mapping question can be answered there, it does not belong here.

Mostly in-process, for the reason this module's sibling `test_cli.py` states in
its own docstring. The single subprocess test is doing a different job: it runs
the **installed** console script from a directory outside the checkout, which
is the CLI's standing promise ("every command works from any working
directory") and the one thing an in-process call cannot show.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from openstategraph import cli


def _package(root: Path, slug: str = "exportable") -> Path:
    directory = root / slug
    (directory / "skills").mkdir(parents=True)
    (directory / "workflow.json").write_text(
        json.dumps({"name": "Exportable", "nodes": [], "edges": []})
    )
    (directory / "AGENTS.md").write_text("# Exportable\n\nA package that exports.\n")
    (directory / "skills" / "house-style.md").write_text("Write plainly.\n")
    return directory


class TestItWritesThePluginTheHttpDoorOnlyPreviews:
    def test_the_manifest_and_the_carried_files_land_on_disk(
        self, tmp_path: Path, capsys
    ) -> None:
        package = _package(tmp_path)
        out = tmp_path / "bundle"

        code = cli.main(["export", "plugin", str(package), "--out", str(out)])

        assert code == cli.EXIT_OK
        manifest = json.loads((out / "plugin.json").read_text())
        assert manifest["name"] == "exportable"
        assert manifest["$schema"].endswith("plugin.schema.json")
        assert (out / "skills" / "house-style" / "SKILL.md").is_file()
        assert (out / "org.openstategraph" / "workflow.json").is_file()
        assert str(out) in capsys.readouterr().out

    def test_the_lossy_notes_are_said_out_loud_on_stderr(self, tmp_path: Path, capsys) -> None:
        """The notes are the honest half — both other doors return them, and a
        bundle written without them is a silent lossy conversion."""
        package = _package(tmp_path)

        cli.main(["export", "plugin", str(package), "--out", str(tmp_path / "bundle")])

        err = capsys.readouterr().err
        assert "org.openstategraph" in err
        assert "mcp.json" in err

    def test_without_out_it_writes_beside_the_caller(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        package = _package(tmp_path)
        here = tmp_path / "cwd"
        here.mkdir()
        monkeypatch.chdir(here)

        code = cli.main(["export", "plugin", str(package)])

        assert code == cli.EXIT_OK
        assert (here / "exportable" / "plugin.json").is_file()


class TestTheExitCodesCIConsumes:
    def test_a_directory_that_is_not_a_package_exits_one(self, tmp_path: Path, capsys) -> None:
        """Never a bundle full of nothing: `export_plugin` is happy to render a
        directory with no `workflow.json`, which would write a plausible plugin
        for something that is not a package."""
        (tmp_path / "notapackage").mkdir()

        code = cli.main(["export", "plugin", str(tmp_path / "notapackage")])

        assert code == cli.EXIT_FAILURE
        assert "workflow.json" in capsys.readouterr().err

    def test_a_missing_directory_exits_one(self, tmp_path: Path, capsys) -> None:
        code = cli.main(["export", "plugin", str(tmp_path / "nope")])

        assert code == cli.EXIT_FAILURE
        assert "nope" in capsys.readouterr().err

    def test_a_slug_no_plugin_can_be_named_exits_one_with_the_rule(
        self, tmp_path: Path, capsys
    ) -> None:
        """`InvalidPluginError`, reported as its own sentence rather than as an
        uncaught traceback naming a Python class."""
        package = _package(tmp_path, slug="Not_A_Plugin_Name")

        code = cli.main(["export", "plugin", str(package), "--out", str(tmp_path / "b")])

        assert code == cli.EXIT_FAILURE
        err = capsys.readouterr().err
        assert "Agent Plugins name" in err
        assert "Traceback" not in err

    def test_an_occupied_destination_is_refused_and_left_alone(
        self, tmp_path: Path, capsys
    ) -> None:
        """`write_export` merges into whatever it finds — right for a library
        call at a destination the caller named, wrong for a command that would
        otherwise interleave a new bundle with somebody's directory."""
        package = _package(tmp_path)
        out = tmp_path / "bundle"
        out.mkdir()
        (out / "keep.txt").write_text("mine\n")

        code = cli.main(["export", "plugin", str(package), "--out", str(out)])

        assert code == cli.EXIT_FAILURE
        assert str(out) in capsys.readouterr().err
        assert (out / "keep.txt").read_text() == "mine\n"
        assert not (out / "plugin.json").exists()

    def test_an_empty_destination_is_not_refused(self, tmp_path: Path) -> None:
        package = _package(tmp_path)
        out = tmp_path / "bundle"
        out.mkdir()

        assert cli.main(["export", "plugin", str(package), "--out", str(out)]) == cli.EXIT_OK

    def test_no_package_argument_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["export", "plugin"])
        assert excinfo.value.code == cli.EXIT_USAGE

    def test_the_bare_verb_is_a_usage_error_naming_what_can_be_exported(self, capsys) -> None:
        """Unlike `examples`, there is no safe thing to assume: every leaf of
        `export` writes a directory."""
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["export"])
        assert excinfo.value.code == cli.EXIT_USAGE
        assert "plugin" in capsys.readouterr().err

    def test_an_unknown_format_is_a_usage_error(self) -> None:
        """The room `export python` would join: an unknown leaf is argparse's
        own 2, with the real ones listed."""
        with pytest.raises(SystemExit) as excinfo:
            cli.main(["export", "elixir", "."])
        assert excinfo.value.code == cli.EXIT_USAGE

    def test_it_needs_no_extra_so_it_has_no_three(self, tmp_path: Path) -> None:
        """`3` means "a required extra is not installed, here is the install
        line". This command has no such line to name, because the seam it wraps
        imports nothing optional — `plugin_interop` is stdlib plus
        `openstategraph.skills`. Pinned rather than left as prose: an export
        that grew a dependency has to come back here and give `3` its message.
        """
        import ast

        import openstategraph.plugin_interop as interop

        imported = set()
        for node in ast.walk(ast.parse(Path(interop.__file__).read_text())):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {"__future__", "json", "re", "dataclasses", "pathlib", "typing",
                            "openstategraph"}, imported

        code = cli.main(
            ["export", "plugin", str(_package(tmp_path)), "--out", str(tmp_path / "b")]
        )
        assert code == cli.EXIT_OK


class TestFromAnywhereOnTheMachine:
    """"Every command works from any working directory; nothing is relative to
    a checkout" — `cli.py`'s own docstring. An in-process call inherits
    pytest's cwd, so this one shells out and stands somewhere else. It proves
    the *cwd* promise only: whether the command survives being installed as a
    wheel is `scripts/clean_install_proof.sh`'s question, not this file's.
    """

    def test_it_exports_while_standing_outside_the_checkout(self, tmp_path: Path) -> None:
        package = _package(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from openstategraph.cli import main; sys.exit(main(sys.argv[1:]))",
                "export",
                "plugin",
                str(package),
            ],
            cwd=elsewhere,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1])},
        )

        assert result.returncode == 0, result.stderr
        assert (elsewhere / "exportable" / "plugin.json").is_file()
        assert str(elsewhere / "exportable") in result.stdout
