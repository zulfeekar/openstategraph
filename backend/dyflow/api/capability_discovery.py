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
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dyflow.abc.tool import BaseTool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCapability:
    id: str
    name: str
    description: str
    args_schema: dict[str, Any]
    #: The canvas node type the tool itself declares (`BaseTool.node_type`).
    #: Empty when the tool is not placeable on a canvas.
    node_type: str = ""


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


def discover_tool_instances(workflow_dir: Path, slug: str) -> list[tuple[str, BaseTool]]:
    """`(qualified_id, instance)` for every tool the workflow defines.

    The instances are the same objects `discover_tools` describes — returned
    so the runtime can *bind* them, not merely list them. (An earlier attempt
    re-imported each class from its qualified id by string surgery:
    `__import__("tabular-analytics.tools")` — a hyphenated slug is never a
    legal module name, so every slug-based run silently lost all its tools.)
    """
    tools_dir = workflow_dir / "tools"
    if not tools_dir.is_dir():
        return []

    found: list[tuple[str, BaseTool]] = []
    seen_classes: set[type] = set()

    for path in sorted(tools_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        qualified_module = f"{slug}.tools.{path.stem}"
        try:
            module = _import_module(path, qualified_module)
        except Exception:
            logger.warning("Skipping unimportable tool module %s", path, exc_info=True)
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
                logger.warning(
                    "Skipping tool %s.%s: constructor failed",
                    qualified_module,
                    obj.__name__,
                    exc_info=True,
                )
                continue
            found.append((f"{slug}/tools.{obj.__name__}", instance))

    return found


def discover_tool_registry(workflow_dir: Path, slug: str) -> dict[str, BaseTool]:
    """The runtime's tool registry: canvas node type → tool instance.

    Keyed by each tool's **own** `node_type` declaration — the single source
    of truth for wiring identity (ticket 33). A tool that declares none is
    listable but not placeable, so it is simply absent here.
    """
    registry: dict[str, BaseTool] = {}
    for _, instance in discover_tool_instances(workflow_dir, slug):
        if instance.node_type:
            registry[instance.node_type] = instance
    return registry


def discover_tools(workflow_dir: Path, slug: str) -> list[ToolCapability]:
    """Every `BaseTool` subclass defined in `<workflow_dir>/tools/*.py`.

    Only classes *defined* in the scanned module count — an import re-exported
    through the module (e.g. `from .other import SomeTool`) is skipped by
    checking `__module__`, so an `__init__.py` re-export never registers the
    same tool twice under two different qualified ids.
    """
    return [
        ToolCapability(
            id=qualified_id,
            name=instance.name,
            description=instance.description,
            args_schema=instance.Args.model_json_schema(),
            node_type=instance.node_type,
        )
        for qualified_id, instance in discover_tool_instances(workflow_dir, slug)
    ]


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
            logger.warning("Skipping unimportable function module %s", path, exc_info=True)
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


def discover_function_callables(workflow_dir: Path, slug: str) -> dict[str, Any]:
    """The runtime's function registry: `function.<name>` → the callable.

    The node-type convention mirrors tools' `node_type` declaration without
    demanding one: a function's *name* is already its identity (that is what
    `discover_functions` lists), so `function.format_report` in a document
    binds `def format_report(...)` in the workflow's `functions/`. The
    signature contract is deliberately narrow — `fn(text: str) -> str`, a
    deterministic transform of the node's upstream text — because a function
    with access to raw graph state would be a second, unserialisable place
    for control flow to hide (expressions are a JSON AST; code is referenced
    by name, never embedded).
    """
    functions_dir = workflow_dir / "functions"
    if not functions_dir.is_dir():
        return {}

    registry: dict[str, Any] = {}
    for path in sorted(functions_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        qualified_module = f"{slug}.functions.{path.stem}"
        try:
            module = _import_module(path, qualified_module)
        except Exception:
            logger.warning("Skipping unimportable function module %s", path, exc_info=True)
            continue
        for name, obj in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("_") or obj.__module__ != qualified_module:
                continue
            registry[f"function.{name}"] = obj
    return registry


__all__ = [
    "FunctionCapability",
    "ToolCapability",
    "discover_function_callables",
    "discover_functions",
    "discover_tool_instances",
    "discover_tool_registry",
    "discover_tools",
]
