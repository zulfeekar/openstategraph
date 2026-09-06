"""A third-party stub written for a newer Python must not fail our gate.

`osg-agent-experience/56`. CI run `33973261110` went red in `backend (3.13)`
on a file this repository never imports:

    site-packages/numpy/__init__.pyi:737: error: Type statement is only
    supported in Python 3.12 and greater  [syntax]

Two facts had to meet. `[tool.mypy] python_version = "3.11"` is correct and
stays — `requires-python` is `>=3.11` and the matrix runs it — and mypy parses
every file in its graph under that grammar, third-party stubs included. And
numpy became installed: `osg-agent-experience/40` put
`databricks-sql-connector` behind the `[databricks]` extra, `[all]` includes
it, and it depends on pandas, which depends on numpy.

The obvious cause is the wrong one. The driver is never statically imported —
`prebuilt_databricks` reaches it through `importlib.import_module`, as every
SQL leaf reaches its own — and mypy does not follow a string, so `databricks.*`
is not in the graph and an override for it would suppress nothing. numpy
arrives through a *hard* dependency instead:

    openstategraph.mcp_server -> langchain_core.messages.utils
      -> langchain_text_splitters.base -> tiktoken.core -> numpy.typing

The extra supplied the package; the core supplied the import.

`test_mypy_is_clean` next door is the gate, and it cannot see this on a
checkout whose numpy predates the PEP 695 rewrite — which is every checkout
this was diagnosed on. So the first test below synthesises the offending stub
instead of waiting for the environment to supply one: a package named `numpy`
on `MYPYPATH`, carrying one `type` statement, checked with the repository's own
config. It is red without the fix and it does not depend on which numpy the
machine happens to have.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
PYPROJECT = BACKEND / "pyproject.toml"
PACKAGE = BACKEND / "openstategraph"


def _config() -> dict[str, object]:
    return tomllib.loads(PYPROJECT.read_text())["tool"]["mypy"]


def _overrides() -> list[dict[str, object]]:
    raw = _config().get("overrides", [])
    assert isinstance(raw, list)
    return raw


def _modules(override: dict[str, object]) -> tuple[str, ...]:
    module = override["module"]
    return (module,) if isinstance(module, str) else tuple(module)


def _require_mypy() -> None:
    probe = subprocess.run(
        [sys.executable, "-m", "mypy", "--version"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip("mypy is not installed; it is a [dev] extra")


class TestANewerStubDoesNotFailTheGate:
    def test_a_pep695_stub_in_a_package_we_never_import_is_not_parsed(
        self, tmp_path: Path
    ) -> None:
        """The 3.13 CI failure, reproduced without needing numpy 2.4 installed.

        `MYPYPATH` outranks site-packages in mypy's search order, so the stub
        written here is the `numpy` the gate sees, whatever the machine has.
        """
        _require_mypy()
        stubs = tmp_path / "stubs" / "numpy"
        stubs.mkdir(parents=True)
        # numpy 2.4's `__init__.pyi` in one line: PEP 695, 3.12 grammar.
        (stubs / "__init__.pyi").write_text("type _Alias = int\ndef zeros() -> _Alias: ...\n")
        source = tmp_path / "probe.py"
        # The probe uses the module without returning its value: once skipped,
        # numpy is `Any`, and `warn_return_any` would fire on the fixture rather
        # than on the grammar this test is about.
        source.write_text("import numpy\n\n\ndef call() -> None:\n    numpy.zeros()\n")

        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--config-file", str(PYPROJECT), str(source)],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "MYPYPATH": str(tmp_path / "stubs")},
        )

        assert result.returncode == 0, (
            "a third-party stub using grammar newer than `python_version` fails "
            "the gate; this is CI 33973261110's numpy failure:\n"
            f"{result.stdout}{result.stderr}"
        )

    def test_python_version_stays_at_the_floor_we_support(self) -> None:
        """The fix must not be a version bump. `requires-python` is the reason."""
        project = tomllib.loads(PYPROJECT.read_text())["project"]
        floor = project["requires-python"].removeprefix(">=").strip()
        assert _config()["python_version"] == floor, (
            "mypy must check against the oldest Python this package claims to "
            f"support ({floor}); raising it to silence a stub would make the "
            "gate stop seeing what a 3.11 adopter sees"
        )


class TestWhatTheGateSkipsIsArguedAndNarrow:
    def test_a_skip_also_skips_stubs_or_it_skips_nothing(self) -> None:
        """`follow_imports = "skip"` alone is a no-op for a stub-only package.

        Measured, not assumed: mypy parses `.pyi` files regardless of
        `follow_imports` unless `follow_imports_for_stubs` sits beside it — so
        the option silences nothing for exactly the packages worth silencing,
        and does it while looking like it worked.
        """
        for override in _overrides():
            if override.get("follow_imports") != "skip":
                continue
            assert override.get("follow_imports_for_stubs") is True, (
                f"{_modules(override)} is skipped without "
                "`follow_imports_for_stubs = true`, which for a stub-shipping "
                "package means it is not skipped at all"
            )

    def test_nothing_our_own_code_imports_is_skipped(self) -> None:
        """A skip turns a real dependency into `Any` — silently, gate still green.

        Derived from the source rather than from a list, so the day somebody
        writes `import numpy` in `openstategraph/` the skip becomes a red test
        instead of a hole in the type gate.
        """
        skipped = {
            module.removesuffix(".*")
            for override in _overrides()
            if override.get("follow_imports") == "skip"
            for module in _modules(override)
        }
        assert skipped, "the whole point of these two tests is that something is skipped"

        for path in sorted(PACKAGE.rglob("*.py")):
            for root in _imported_roots(path):
                assert root not in skipped, (
                    f"{path.relative_to(REPO_ROOT)} statically imports `{root}`, "
                    "which the mypy config tells the gate not to follow — every "
                    "annotation involving it is silently `Any`"
                )


def _imported_roots(path: Path, *, module_scope_only: bool = False) -> set[str]:
    """Top-level package names this file imports.

    `module_scope_only` is the difference between the two questions asked of
    this function. mypy follows an import wherever it is written, so the skip
    test wants every one of them; an extra stays optional only if nothing
    imports its driver *at import time*, so the laziness test walks the module
    body and the `if`/`try`/`with` blocks in it, and stops at a `def`.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    nodes = _module_scope_nodes(tree) if module_scope_only else list(ast.walk(tree))
    roots: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _module_scope_nodes(tree: ast.Module) -> list[ast.AST]:
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            stack.extend(ast.iter_child_nodes(node))
    return out


class TestTheOptionalDriversStayLazy:
    """Why `databricks.*` needs no override, stated as an assertion.

    An extra is optional because nothing imports its driver at module scope;
    that same property is why the driver never enters mypy's graph. Derived
    from every `DRIVER_MODULES` the package declares plus the `import_module`
    strings the warehouse leaves write, so a new warehouse leaf is covered the
    day it lands.

    **That last sentence was not true until `osg-agent-experience/73`.** The
    derivation read `knowledge_engines` and *one named leaf*, so `msal` — the
    T-SQL leaf's second optional import, added with the Azure AD login — was
    outside it, and a static `import msal` would have made the `[mssql]` extra
    mandatory with this test still green. Widening the derivation is the fix
    rather than adding `"msal"` to a list here: a list covers the driver
    somebody remembered.
    """

    def test_no_module_statically_imports_an_optional_driver(self) -> None:
        drivers = _declared_driver_modules()
        assert drivers, "no optional driver names were found; the derivation moved"

        for path in sorted(PACKAGE.rglob("*.py")):
            for root in _imported_roots(path, module_scope_only=True):
                assert root not in drivers, (
                    f"{path.relative_to(REPO_ROOT)} imports `{root}` at module "
                    "scope; that makes an extra mandatory and drags the driver "
                    "into the type gate's graph"
                )


def _declared_driver_modules() -> set[str]:
    """Every optional-driver name the package declares, read out of the package.

    Two halves, because the package says it in two idioms: a `DRIVER_MODULES`
    tuple (the engine adapters, and the leaves since `73`), and the literal a
    lazy `import_module` seam is given. Both are walked across every
    `prebuilt_*` module rather than one named one.
    """
    import importlib as _importlib

    from openstategraph import knowledge_engines

    names: set[str] = set()
    modules = [knowledge_engines]
    for path in sorted(PACKAGE.glob("prebuilt_*.py")):
        modules.append(_importlib.import_module(f"openstategraph.{path.stem}"))

    sources: list[str] = []
    for module in modules:
        for value in (module, *vars(module).values()):
            declared = getattr(value, "DRIVER_MODULES", None)
            if isinstance(declared, tuple):
                names.update(str(name).split(".")[0] for name in declared)
        sources.append(Path(module.__file__ or "").read_text())

    source = "\n".join(sources)
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value.split(".")[0])
    return names
