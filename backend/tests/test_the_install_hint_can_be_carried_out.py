"""`osg-agent-experience/79` — the one remedy we print has to be runnable.

With `pyodbc` absent, every `mssql_query` call answered *"Install the extra:
pip install 'openstategraph[mssql]'"*. Measured 2026-09-06 against the try
project's install of `0.3.0rc15`, that line cannot be carried out twice over:
the distribution is a pre-release on TestPyPI, so a bare `pip install` resolves
nothing; and the interpreter was a `uv tool` install, which `pip` does not
manage at all. The orchestrator's own repair — `uv tool install --force
'openstategraph[mssql]'` — then **replaced** the install and dropped `[server]`,
so the next `openstategraph .` refused to start for want of uvicorn.

Three facts decide the sentence, and none of them can be guessed:

- **how this interpreter was installed** (a `uv` tool directory, a virtual
  environment, or neither),
- **which extras are already here**, because a `--force` reinstall carries
  only what the command names,
- **whether the version is a pre-release**, because that is what makes the
  TestPyPI index flags necessary — and what makes them wrong once it is not.

`install_hint` is the one place all three are read. Everything that used to
compose an install line — the warehouse leaves' missing-driver refusal, the
MSAL one beside it, and the CLI's "uvicorn is required" — asks it instead.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

from openstategraph.install_hint import (
    EXTRA_MARKERS,
    Installation,
    detect_installation,
    install_hint,
    installed_extras,
)

REPO = Path(__file__).resolve().parents[2]

UV_TOOL = Installation(shape="uv-tool", version="0.3.0rc15", extras=("ollama", "server"))
VENV = Installation(shape="venv", version="0.3.0rc15", extras=("server",))
PIP_USER = Installation(shape="pip-user", version="0.3.0rc15", extras=())
RELEASED = Installation(shape="uv-tool", version="1.0.0", extras=("server",))


class TestTheShapeOfTheCommand:
    def test_a_uv_tool_install_is_repaired_with_uv_not_pip(self) -> None:
        hint = install_hint("mssql", installation=UV_TOOL)
        assert hint.startswith("uv tool install --force ")
        assert "pip install" not in hint

    def test_a_virtual_environment_is_repaired_with_pip(self) -> None:
        hint = install_hint("mssql", installation=VENV)
        assert hint.startswith("pip install ")
        assert "--user" not in hint
        # `--index-strategy` is uv's flag and pip does not have it.
        assert "--index-strategy" not in hint

    def test_a_bare_interpreter_installs_for_the_user(self) -> None:
        assert install_hint("mssql", installation=PIP_USER).startswith(
            "pip install --user "
        )


class TestTheOtherExtrasSurvive:
    def test_the_union_is_named_not_only_the_missing_one(self) -> None:
        hint = install_hint("mssql", installation=UV_TOOL)
        assert "'openstategraph[mssql,ollama,server]==0.3.0rc15'" in hint

    def test_pip_names_only_the_missing_extra(self) -> None:
        """Because `pip install` uninstalls nothing — the union is uv's problem.

        A pip line naming every extra installed would read as nine
        requirements for one fault, which is a different lie from the one this
        ticket is fixing.
        """
        assert "'openstategraph[mssql]==0.3.0rc15'" in install_hint(
            "mssql", installation=VENV
        )
        assert "server" not in install_hint("mssql", installation=VENV)

    def test_an_extra_already_present_is_not_doubled(self) -> None:
        assert "'openstategraph[ollama,server]==0.3.0rc15'" in install_hint(
            "server", installation=UV_TOOL
        )

    def test_the_bracketed_spelling_is_accepted(self) -> None:
        assert install_hint("openstategraph[mssql]", installation=UV_TOOL) == install_hint(
            "mssql", installation=UV_TOOL
        )


class TestThePreReleaseFlags:
    def test_a_pre_release_carries_the_index_flags_and_an_exact_version(self) -> None:
        hint = install_hint("mssql", installation=UV_TOOL)
        assert "--index-url https://test.pypi.org/simple/" in hint
        assert "--extra-index-url https://pypi.org/simple/" in hint
        assert "--index-strategy unsafe-best-match" in hint
        assert "==0.3.0rc15" in hint

    def test_a_released_version_carries_none_of_them(self) -> None:
        hint = install_hint("mssql", installation=RELEASED)
        assert "test.pypi.org" not in hint
        assert "--index-strategy" not in hint
        assert "==" not in hint
        assert "'openstategraph[mssql,server]'" in hint

    def test_the_flags_are_the_ones_the_readme_documents(self) -> None:
        """Derived from the README's own install block, never copied beside it.

        The block is the fenced command a reader is told to run, not the prose
        around it — the prose names the same flags while explaining them, and a
        sentence ending in a backtick is not a flag.
        """
        blocks = re.findall(r"```[a-z]*\n(.*?)```", (REPO / "README.md").read_text("utf-8"), re.S)
        install = [b for b in blocks if "uv tool install" in b]
        assert install, "the README no longer documents an install block"
        documented = set(
            re.findall(r"--(?:extra-)?index-url \S+|--index-strategy \S+", install[0])
        )
        assert len(documented) == 3, documented
        hint = install_hint("mssql", installation=UV_TOOL)
        for flag in documented:
            assert flag in hint, flag


class TestEveryExtraNamedIsOneThatExists:
    """Done-when 2: derived from `pyproject.toml`, so the next invention is red."""

    def test_the_marker_table_names_only_declared_extras(self) -> None:
        declared = set(
            tomllib.loads(
                (REPO / "backend" / "pyproject.toml").read_text(encoding="utf-8")
            )["project"]["optional-dependencies"]
        )
        assert set(EXTRA_MARKERS) <= declared, set(EXTRA_MARKERS) - declared

    def test_the_leaves_driver_modules_come_from_that_table(self) -> None:
        from openstategraph import prebuilt_databricks, prebuilt_mssql

        assert prebuilt_mssql.DRIVER_MODULES == EXTRA_MARKERS["mssql"]
        assert prebuilt_databricks.DRIVER_MODULES == EXTRA_MARKERS["databricks"]

    def test_the_surfaces_this_ticket_names_compose_no_line_of_their_own(self) -> None:
        """One owner, for the surfaces `79` measured.

        Deliberately not the whole package. `injection.py`, `deployment.py` and
        `postgres.py` still write `pip install 'openstategraph[...]'` into their
        own sentences, and they have exactly the two defects this ticket is
        about; converting them is `osg-agent-experience/82` rather than an
        unreviewed sweep through four modules this session does not own. What
        is asserted is what shipped: the warehouse family, the MSSQL login and
        the CLI's own refusals ask the helper.
        """
        package = REPO / "backend" / "openstategraph"
        converted = (
            "prebuilt_warehouse.py",
            "prebuilt_mssql.py",
            "prebuilt_databricks.py",
            "mssql_connection.py",
            "_extras.py",
        )
        offenders = [
            name
            for name in converted
            if re.search(
                r"install '?openstategraph\[\{?[a-z]", (package / name).read_text("utf-8")
            )
        ]
        assert not offenders, offenders


class TestWhatThisInterpreterActuallyIs:
    def test_a_uv_tools_directory_is_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            sys, "prefix", "/Users/x/.local/share/uv/tools/openstategraph"
        )
        monkeypatch.setattr(sys, "base_prefix", "/opt/python")
        assert detect_installation().shape == "uv-tool"

    def test_a_virtual_environment_is_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "prefix", "/work/project/.venv")
        monkeypatch.setattr(sys, "base_prefix", "/opt/python")
        assert detect_installation().shape == "venv"

    def test_anything_else_is_a_user_install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "prefix", "/opt/python")
        monkeypatch.setattr(sys, "base_prefix", "/opt/python")
        assert detect_installation().shape == "pip-user"

    def test_the_extras_present_are_probed_not_assumed(self) -> None:
        present = installed_extras()
        assert set(present) <= set(EXTRA_MARKERS)
        # This checkout runs the API tests, so `[server]` is here by definition.
        assert "server" in present
