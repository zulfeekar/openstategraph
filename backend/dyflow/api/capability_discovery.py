"""Capability discovery — ticket 18, the `code -> canvas` channel.

A developer drops a `BaseTool` subclass into a workflow's `tools/` folder, and
this is what turns it into something the editor can list — not by convention
alone (a bare "any public class" rule would register a helper class or an
`__init__.py` re-export too), but by the ticket's own settled predicate:
**folder scopes where to look, subclassing decides what counts.**

Scope, stated honestly: this covers **capabilities** (tools and functions
becoming usable), which is what the ticket's requirement actually describes —
"a developer defines a function... and the frontend surfaces it as a usable
object." It does **not** cover the ticket's second, larger target — a
hand-written `Final*` **node type** appearing in the palette, which needs the
SSE-broadcast-manifest-refresh design the ticket sketches and a matching
frontend `NodeTypeRegistry.upsert()` consumer, neither of which exists yet.
That half is left open, not fabricated as done.

**Import executes code.** Discovery imports the workflow's own `tools/` and
`functions/` modules, which runs their module-level code — the same trust
model `pytest` already uses to collect `conftest.py`. Acceptable for a local
dev tool; a real problem the moment this is ever hosted for someone else's
code. Recorded here as the ticket asked, not solved — there is no sandboxing.

**Qualified ids, not bare class/function names.** Two workflows can each
define `tools/my_tool.py` with a class `MyTool`; a bare name would collide.
Every discovered capability is imported under a name derived from the
workflow's own slug (`<slug>.tools.<module>`), so two workflows' identically
named files never share a Python module object, and the returned id is
`<slug>/tools.<ClassName>` (or `<slug>/functions.<function_name>`) —
answering the ticket's own qualified-id question directly.
"""

from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dyflow.abc.tool import BaseTool


@dataclass(frozen=True)
class ToolCapability:
    id: str
    name: str
    description: str
    args_schema: dict[str, Any]


@dataclass(frozen=True)
class FunctionCapability:
    id: str
    name: str
    docstring: str
    signature: str


def _import_module(path: Path, qualified_name: str) -> Any:
    """Imports one file under a workflow-qualified module name.

    Never `importlib.reload`, and never the file's own bare module name —
    both are how two workflows' same-named files would collide or how a
    previously-discovered class would silently stop `isinstance`-matching a
    freshly reloaded base (the exact hazard the ticket calls out; the fix
    there is a process restart during development, not reload — this
    function just avoids the *naming* half of that hazard).
    """
    spec = importlib.util.spec_from_file_location(qualified_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover_tools(workflow_dir: Path, slug: str) -> list[ToolCapability]:
    """Every `BaseTool` subclass defined in `<workflow_dir>/tools/*.py`.

    Only classes *defined* in the scanned module count — an import re-exported
    through the module (e.g. `from .other import SomeTool`) is skipped by
    checking `__module__`, so an `__init__.py` re-export never registers the
    same tool twice under two different qualified ids.
    """
    tools_dir = workflow_dir / "tools"
    if not tools_dir.is_dir():
        return []

    found: list[ToolCapability] = []
    seen_classes: set[type] = set()

    for path in sorted(tools_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        qualified_module = f"{slug}.tools.{path.stem}"
        try:
            module = _import_module(path, qualified_module)
        except Exception:
            # A syntax error or a bad import in one file must not blank the
            # whole capability list — the same reasoning `WorkflowStore.list`
            # already applies to one unreadable `workflow.json`.
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseTool or not issubclass(obj, BaseTool):
                continue
            if obj.__module__ != qualified_module:
                continue
            if obj in seen_classes or inspect.isabstract(obj):
                continue
            seen_classes.add(obj)
            try:
                instance = obj()
            except Exception:
                continue
            found.append(
                ToolCapability(
                    id=f"{slug}/tools.{obj.__name__}",
                    name=instance.name,
                    description=instance.description,
                    args_schema=instance.Args.model_json_schema(),
                )
            )

    return found


def discover_functions(workflow_dir: Path, slug: str) -> list[FunctionCapability]:
    """Every top-level, non-underscore function in `<workflow_dir>/functions/*.py`.

    Convention-based, deliberately looser than `tools/`'s subclass predicate —
    there is no `IFunction`/`BaseFunction` ladder to hang discovery on (a
    function is a callable, not a class), and the ticket's own debate between
    "explicit decorator" and "convention" is left as convention here: a
    workflow's `functions/` folder is already a stated-scope boundary, so an
    extra per-function marker would be a second signal saying the same thing
    the folder already says.
    """
    functions_dir = workflow_dir / "functions"
    if not functions_dir.is_dir():
        return []

    found: list[FunctionCapability] = []

    for path in sorted(functions_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        qualified_module = f"{slug}.functions.{path.stem}"
        try:
            module = _import_module(path, qualified_module)
        except Exception:
            continue

        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_") or obj.__module__ != qualified_module:
                continue
            found.append(
                FunctionCapability(
                    id=f"{slug}/functions.{name}",
                    name=name,
                    docstring=inspect.getdoc(obj) or "",
                    signature=str(inspect.signature(obj)),
                )
            )

    return found


__all__ = ["FunctionCapability", "ToolCapability", "discover_functions", "discover_tools"]
