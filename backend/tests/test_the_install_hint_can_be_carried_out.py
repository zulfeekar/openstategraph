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
- **whether the version is a pre-release**, because pip and `uv` exclude a
  pre-release from an unpinned requirement, so the version has to be named in
  full or the command resolves nothing.

The third fact used to carry a second job — it also decided whether TestPyPI
index flags were rendered — and `stable-beta-public/37` took that job away.
`0.3.0rc18` is a pre-release published to **PyPI**, so "pre-release" and "not
on the default index" stopped naming the same builds; see
`TestThePinIsAboutTheVersion` below.

`install_hint` is the one place all three are read. Everything that used to
compose an install line — the warehouse leaves' missing-driver refusal, the
MSAL one beside it, and the CLI's "uvicorn is required" — asks it instead.
"""

from __future__ import annotations

import ast
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


def _non_docstring_string_literals(path: Path) -> list[str]:
    """Every string literal in `path`, except a module's/class's/function's
    own docstring.

    A docstring is, by Python's own definition, the first statement of a
    module/class/function body when that statement is a bare string
    expression — so it is found the same way the interpreter finds it,
    walking the AST rather than guessing from indentation or quote style. A
    comment needs no such carve-out: `ast.parse` throws every comment away
    before this function ever sees the tree.
    """
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

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


class TestTheCommandCannotWrapItself:
    """`osg-agent-experience/83`: `install_hint` composes a command, never a
    paragraph — `textwrap` never touches it, so nothing it returns can arrive
    pre-broken at a caller that (correctly) wraps everything else.

    Pinned against the widest case this module can produce: every known
    extra already present, on a `uv tool` install, pre-release — the one
    shape that must carry the union (`TestTheOtherExtrasSurvive` above) and
    therefore composes the longest possible `'openstategraph[...]'` spec.
    """

    def test_the_rendered_command_has_no_newline_for_the_longest_extras_union(
        self,
    ) -> None:
        widest = Installation(
            shape="uv-tool", version="0.3.0rc15", extras=tuple(sorted(EXTRA_MARKERS))
        )
        hint = install_hint("mssql", installation=widest)
        assert "\n" not in hint


class TestThePinIsAboutTheVersion:
    """`stable-beta-public/37`: the flags belonged to the rehearsal, not to the
    version, and the module said otherwise for as long as both were true at once.

    Until `0.3.0rc18` every published build lived on TestPyPI only, so "this is
    a pre-release" and "this comes from a non-default index" named the same
    builds and one condition served both. Publishing a release candidate to
    PyPI separated them: `0.3.0rc18` is a pre-release **on the default index**,
    and a hint carrying `--index-url https://test.pypi.org/simple/` now sends a
    reader to an index that does not have the build they are running.

    So one of the three facts the module reads changed meaning. The version
    still decides whether the requirement must be named exactly — pip and `uv`
    exclude pre-releases from an unpinned requirement, which is unchanged and
    is why `==` survives below. It no longer decides anything about indexes,
    because nothing about a version does: an index is where a build was
    uploaded, and this project uploads to PyPI.
    """

    def test_a_pre_release_is_named_exactly_and_reaches_the_default_index(self) -> None:
        hint = install_hint("mssql", installation=UV_TOOL)
        assert "==0.3.0rc15" in hint
        assert "index-url" not in hint
        assert "--index-strategy" not in hint
        assert "test.pypi.org" not in hint

    def test_a_released_version_needs_no_pin_either(self) -> None:
        hint = install_hint("mssql", installation=RELEASED)
        assert "test.pypi.org" not in hint
        assert "--index-strategy" not in hint
        assert "==" not in hint
        assert "'openstategraph[mssql,server]'" in hint

    def test_the_hint_is_the_shape_the_readme_documents(self) -> None:
        """Derived from the README's own install block, never copied beside it.

        The claim held here is the one that changed: the block a reader is told
        to paste names **no index at all**, and neither does the line the
        product prints. Two spellings of one install command drifting apart is
        the defect this module exists to prevent, and a flag is the half that
        drifted.
        """
        blocks = re.findall(r"```[a-z]*\n(.*?)```", (REPO / "README.md").read_text("utf-8"), re.S)
        install = [b for b in blocks if "uv tool install" in b]
        assert install, "the README no longer documents an install block"
        documented = set(
            re.findall(r"--(?:extra-)?index-url \S+|--index-strategy \S+", install[0])
        )
        assert documented == set(), (
            "the README's install block has regained index flags; the published "
            f"form takes none: {documented}"
        )
        hint = install_hint("mssql", installation=UV_TOOL)
        assert "index-url" not in hint and "--index-strategy" not in hint


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
        """One owner, for every module — not a named tuple (`osg-agent-experience/82`).

        `79` converted the surfaces it measured; `injection.py`, `deployment.py`
        and `postgres.py` still composed their own `pip install
        'openstategraph[...]'` / `uv tool install` line, with both of 79's
        defects (a `pip` line a `uv tool` install cannot use, a single named
        extra a `--force` reinstall would drop every sibling of). `82` routed
        all five call sites through `install_hint`, so this scans the whole
        package rather than the tuple of files `79` happened to touch — the
        next hand-written install line is red wherever it lands.

        Docstrings are not call sites — they *explain* the shape of a command,
        they do not compose one a reader will paste — so this walks each
        module's AST and skips exactly the string literals that are a module's,
        class's or function's own docstring. A comment is skipped for a
        cheaper reason: `ast.parse` never sees one at all. `install_hint.py`
        is the one recorded exception — it is the only module allowed to
        contain the sentence, because it is the only one that composes it.
        """
        package = REPO / "backend" / "openstategraph"
        pattern = re.compile(r"pip install 'openstategraph\[|uv tool install")
        exceptions = {"install_hint.py"}
        offenders: dict[str, list[str]] = {}
        for path in sorted(package.rglob("*.py")):
            relative = path.relative_to(package).as_posix()
            if path.name in exceptions:
                continue
            hits = [
                literal
                for literal in _non_docstring_string_literals(path)
                if pattern.search(literal)
            ]
            if hits:
                offenders[relative] = hits
        assert not offenders, offenders


class TestWhatThisInterpreterActuallyIs:
    def test_a_uv_tools_directory_is_recognised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # `/home/...`, not `/Users/...`: the sibling gate
        # `test_no_tracked_file_names_a_machine.py` refuses any tracked file
        # carrying this platform's home prefix, and a fabricated path is
        # indistinguishable from a real one to a census that reads text. What
        # the assertion needs is a `uv/tools` segment, which this still has.
        monkeypatch.setattr(
            sys, "prefix", "/home/someone/.local/share/uv/tools/openstategraph"
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
