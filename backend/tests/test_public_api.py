"""The public surface, snapshotted. **This test failing is not a bug.**

It means the semver-public API changed, which is a decision, not an accident —
see the failure message for what to do about it.

Why a *signature* snapshot rather than a name list: a test asserting
`"load_workflow" in dir(openstategraph)` passes while a parameter is renamed,
a default flips, a keyword-only argument becomes positional, or a dataclass
field disappears — every one of which breaks an adopter at runtime, in their
service, months later. The snapshot catches all of them, and it catches them in
the diff of the pull request that caused them.

The second test here is the one that would have caught the leak this work
found: the public loader imported `api.registries._document_of`, an
underscore-prefixed name from the module tree we most want to call internal.
"""

from __future__ import annotations

import ast
import difflib
import inspect
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import pytest

import openstategraph
import openstategraph.abc
import openstategraph.errors
import openstategraph.extensions
import openstategraph.schema

SNAPSHOT = Path(__file__).resolve().parent / "public_api.txt"

#: Every module whose `__all__` is a promise. Nothing else is.
#:
#: `extensions` is here because its *group name strings* are the most
#: irreversible thing this framework publishes: they live in a third party's
#: own `pyproject.toml`, so a rename un-registers every plugin ever shipped
#: against them and does it silently, in their users' installs, not ours.
PUBLIC_MODULES = (
    openstategraph,
    openstategraph.abc,
    openstategraph.errors,
    openstategraph.extensions,
    openstategraph.schema,
)

FAILURE = """\

The public API changed.

If that was intended:
  1. update backend/tests/public_api.txt (the diff above is the new content),
  2. add a CHANGELOG.md entry under Added / Changed / Deprecated / Removed,
  3. for a REMOVAL or a signature change, ship the deprecation shim first —
     docs/stability.md, "Deprecation policy". Pre-1.0, a breaking change bumps
     the MINOR version, never the patch.

If it was not intended, you have just changed something an adopter imports.
"""


def describe(name: str, obj: Any) -> str:
    """One line per public name — enough to notice a real change, no more."""
    origin = getattr(obj, "__module__", "") or ""
    if origin and not origin.startswith("openstategraph"):
        # A re-export (pydantic's `Field`). Snapshotting *its* signature would
        # make this test fail on somebody else's patch release, which trains
        # everyone to update the snapshot without reading it. What we promise
        # about a re-export is which object it is, so pin that.
        return f"{name} = re-export of {origin}.{getattr(obj, '__qualname__', name)}"
    if inspect.isclass(obj):
        bases = ",".join(b.__name__ for b in obj.__bases__)
        if is_dataclass(obj):
            shape = ",".join(f.name for f in fields(obj))
            return f"{name} = dataclass({bases}) fields({shape})"
        try:
            signature = str(inspect.signature(obj))
        except (TypeError, ValueError):  # pydantic models, Protocols
            signature = "(...)"
        return f"{name} = class({bases}){signature}"
    if callable(obj):
        return f"{name} = def{inspect.signature(obj)}"
    return f"{name} = {type(obj).__name__}"


def snapshot_text() -> str:
    lines: list[str] = []
    for module in PUBLIC_MODULES:
        for name in sorted(getattr(module, "__all__", [])):
            if name == "__version__":
                # The number changes every release; that it is exported and is
                # a string is the contract, not its value.
                lines.append(f"{module.__name__}.__version__ = str")
                continue
            lines.append(f"{module.__name__}.{describe(name, getattr(module, name))}")
    return "\n".join(lines) + "\n"


class TestTheSurfaceIsWhatWeSaidItWas:
    def test_it_matches_the_committed_snapshot(self) -> None:
        current = snapshot_text()
        committed = SNAPSHOT.read_text() if SNAPSHOT.is_file() else ""

        if current != committed:
            diff = "\n".join(
                difflib.unified_diff(
                    committed.splitlines(),
                    current.splitlines(),
                    fromfile="public_api.txt (committed)",
                    tofile="public_api.txt (current)",
                    lineterm="",
                )
            )
            pytest.fail(diff + FAILURE, pytrace=False)

    def test_every_exported_name_actually_resolves(self) -> None:
        """An `__all__` entry that does not exist makes `import *` explode and
        is invisible to every other test."""
        for module in PUBLIC_MODULES:
            missing = [n for n in module.__all__ if not hasattr(module, n)]

            assert missing == [], f"{module.__name__} exports names it does not have: {missing}"

    def test_version_is_a_string(self) -> None:
        assert isinstance(openstategraph.__version__, str)
        assert openstategraph.__version__


class TestTierOneDoesNotLeanOnTierThree:
    """The guard for the leak this work found.

    `loader.py` imported `openstategraph.api.registries._document_of` — the one
    supported entry point reaching into an underscore-prefixed name inside the
    tree we most want to call internal. Function-scope imports of *public* api
    names stay legal: that is the lazy-import contract that keeps
    `import openstategraph` free of LangGraph. Importing a **private** name
    across that boundary is not, at any scope.
    """

    TIER_ONE = (
        "loader.py",
        "errors.py",
        "schema.py",
        "results.py",
        "_extras.py",
        "__init__.py",
        # Not Tier 1 itself, but it is the surface adopters type at, and it
        # reaches into `api/` for `serve` and `knowledge build`. Those imports
        # must stay on public names for the same reason the loader's did.
        "cli.py",
    )

    def _private_api_imports(self, path: Path) -> list[str]:
        tree = ast.parse(path.read_text())
        found: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("openstategraph.api"):
                continue
            found += [
                f"{path.name}: from {node.module} import {alias.name}"
                for alias in node.names
                if alias.name.startswith("_")
            ]
        return found

    def test_no_tier_one_module_imports_a_private_api_name(self) -> None:
        package = Path(openstategraph.__file__).resolve().parent
        leaks = [
            leak
            for name in self.TIER_ONE
            if (package / name).is_file()
            for leak in self._private_api_imports(package / name)
        ]

        assert leaks == [], (
            "A Tier 1 module reaches into a private Tier 3 name. Give it a "
            "public home (openstategraph/schema.py is where normalize_document "
            f"went) rather than widening the leak: {leaks}"
        )

    def test_importing_the_top_level_package_does_not_import_the_api_tree(self) -> None:
        """Module-scope imports of `openstategraph.api` would drag FastAPI's
        neighbourhood into every consumer's process. Function scope is fine."""
        tree = ast.parse((Path(openstategraph.__file__)).read_text())
        module_scope = [
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "openstategraph.api"
            )
        ]

        assert module_scope == []


class TestTierThreeMakesNoPromise:
    def test_the_api_package_says_it_is_internal(self) -> None:
        import openstategraph.api

        assert "not part of the public api" in (openstategraph.api.__doc__ or "").lower()

    def test_no_module_under_api_declares_an_all(self) -> None:
        """`__all__` in a private module buys nothing and reads as a promise."""
        api_dir = Path(openstategraph.__file__).resolve().parent / "api"
        offenders = [
            path.name
            for path in sorted(api_dir.glob("*.py"))
            if any(
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
                )
                for node in ast.parse(path.read_text()).body
            )
        ]

        assert offenders == []


class TestTheErrorsStayCatchableTheOldWay:
    """A new exception hierarchy that breaks existing handlers would be a worse
    trade than the untyped errors it replaces. So every error is *both*."""

    def test_a_missing_package_is_still_a_file_not_found_error(self, tmp_path) -> None:
        (tmp_path / "empty").mkdir()

        with pytest.raises(FileNotFoundError):
            openstategraph.load_workflow(tmp_path / "empty")

    def test_and_is_also_catchable_as_ours(self, tmp_path) -> None:
        (tmp_path / "empty").mkdir()

        with pytest.raises(openstategraph.OpenStateGraphError):
            openstategraph.load_workflow(tmp_path / "empty")

    def test_a_bad_package_name_is_still_a_value_error(self, tmp_path) -> None:
        directory = tmp_path / "My Package"
        directory.mkdir()
        (directory / "workflow.json").write_text('{"document": {"nodes": [], "edges": []}}')

        with pytest.raises(ValueError) as excinfo:
            openstategraph.load_workflow(directory)

        assert isinstance(excinfo.value, openstategraph.InvalidPackageName)

    def test_the_mcp_layer_raises_the_same_class_it_always_did(self) -> None:
        """`from openstategraph.mcp_server import DocumentError` must catch the
        object `openstategraph.errors` now defines — two classes with one name
        is how a caller ends up with a handler that never fires."""
        pytest.importorskip("mcp")
        from openstategraph.mcp_server import DocumentError

        assert DocumentError is openstategraph.DocumentError


class TestTheOldPrivateNameStillWorks:
    def test_document_of_is_the_same_object_as_normalize_document(self) -> None:
        from openstategraph.api.registries import _document_of
        from openstategraph.schema import normalize_document

        assert _document_of is normalize_document

    def test_the_mcp_normalizer_is_the_same_object_too(self) -> None:
        pytest.importorskip("mcp")
        from openstategraph.mcp_server import normalize_document as mcp_normalize
        from openstategraph.schema import normalize_document

        assert mcp_normalize is normalize_document
