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

from openstategraph.abc.tool import BaseTool, _abstract_tool_diagnosis, _is_deliberate_base

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

    ## The invalidation policy (gap PF-01)

    **Every call re-executes the module, from the source bytes on disk. There
    is no cache, and the one the interpreter supplies is turned off.**

    The question was framed as "cache or not", and the honest answer is that
    the caching had already happened and nobody had chosen its policy.
    `spec.loader.exec_module` is a `SourceFileLoader`, so it writes a
    `__pycache__/*.pyc` **inside the developer's workflow package** and
    validates it on the next call against `(source mtime in whole seconds,
    source size in bytes)`. Both halves of that key are coarse, and together
    they are wrong for this use: *an edit that keeps the file's byte length
    and lands in the same second as the previous one is invisible.* Measured,
    not reasoned about — changing a tool's description from
    `"Greets someone by name."` to `"Greets someone, warmly."` (same length)
    served the old string back, and it is not an exotic edit: flipping `<` to
    `>`, changing a digit in a row cap, or renaming a variable to another of
    the same length all qualify, and an editor that saves as you type makes
    the same-second half routine. That is stale *runtime* code, not merely a
    stale panel — `discover_tool_instances` binds these classes into the run.

    So the source is read and compiled here rather than handed to the loader.
    Three properties fall out, each pinned by a test in
    `backend/tests/test_capability_discovery.py::TestTheInvalidationPolicy`:

    | Property | Why it is worth the re-execution |
    | --- | --- |
    | an edit takes effect on the next call | a workflow package *is* files on disk; needing a restart to see your own edit is not a dev loop |
    | `isinstance(x, BaseTool)` always holds | the base resolves through `sys.modules` and is never reloaded, however often a leaf is executed — the docstring's hazard belongs to reloading the *base*, which caching a leaf neither causes nor cures |
    | nothing is added to `sys.modules` | each execution is self-contained and collectable, so re-execution accumulates nothing and two workflows' `tools/db.py` cannot shadow each other |

    And a cross-call *class identity* guarantee is not among the things given
    up, because it never held: two calls already yielded two distinct class
    objects, so nothing in the codebase can have been relying on it.

    The cost of not caching is small and was measured rather than assumed:
    **~1.5 ms per call** for `chinook-assistant`, the largest shipped package,
    at three tools — below the noise of the HTTP round trip it rides on, and
    linear in tool count. Should a package ever get large enough for that to
    matter, the invalidation key must be the **file's content hash**, never
    its mtime and never process lifetime; anything coarser reintroduces
    exactly the staleness this function exists to have removed.
    """
    spec = importlib.util.spec_from_file_location(qualified_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    # Deliberately not `spec.loader.exec_module(module)` — see above. The spec
    # is still built the normal way so `__file__`, `__name__`, `__package__`
    # and `__loader__` are exactly what a normally-imported module gets; only
    # the bytecode-cache path is bypassed, by compiling the bytes ourselves.
    # `path` is passed to `compile` so tracebacks still name the real file.
    code = compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
    exec(code, module.__dict__)  # noqa: S102 — the trust model is in the module docstring
    return module


def _note(warnings: list[str] | None, message: str, *, exc_info: bool = False) -> None:
    """One finding: logged **and** surfaced.

    Both, never one or the other. The log line is what an operator greps after
    the fact; the returned string is what reaches `runtime_warnings()`, the run
    response, `CompiledWorkflow.warnings` and the CLI — the channel a developer
    who never opens a server log actually reads. Ticket 07's rule is that a
    capability which failed to load must not fail silently, and a WARNING in a
    log nobody is watching is a quieter kind of silence.
    """
    logger.warning("%s", message, exc_info=exc_info)
    if warnings is not None:
        warnings.append(message)


def discover_tool_instances(
    workflow_dir: Path,
    slug: str,
    *,
    warnings: list[str] | None = None,
) -> list[tuple[str, BaseTool]]:
    """`(qualified_id, instance)` for every tool the workflow defines.

    The instances are the same objects `discover_tools` describes — returned
    so the runtime can *bind* them, not merely list them. (An earlier attempt
    re-imported each class from its qualified id by string surgery:
    `__import__("chinook-assistant.tools")` — a hyphenated slug is never a
    legal module name, so every slug-based run silently lost all its tools.)

    **Every skip in this loop is a decision, and each one is written down**
    (ticket 07 / register RC-04). The loop used to drop six different
    situations on the floor without a word, one of which — an abstract class,
    which is what a subclass overriding `run` instead of `_execute` becomes —
    produced a tool that installed, validated, ran and was simply absent. The
    inventory, in the order the code meets it:

    | Skip | Decision |
    | --- | --- |
    | `_`-prefixed module | **ignore** — the stated private-file convention |
    | module will not import | **surface** — every tool in it is missing |
    | not a `BaseTool` subclass | **ignore** — folder scopes, subclass decides |
    | defined elsewhere (`__module__`) | **ignore**, then re-checked at the end |
    | already seen | **ignore** — one class, two names in one module |
    | abstract, deliberately named a base | **ignore** — see `_is_deliberate_base` |
    | abstract for any other reason | **surface**, with a specific diagnosis |
    | constructor raised | **surface** — names the tool and the exception |
    | duplicate `node_type` | **surface** — names both classes and the winner |
    | empty `node_type` | **ignore** — documented as "not placeable" |

    `warnings` is an optional sink so no existing caller had to change; a
    caller that passes one gets the findings, a caller that does not still
    gets the log lines.
    """
    tools_dir = workflow_dir / "tools"
    if not tools_dir.is_dir():
        return []

    found: list[tuple[str, BaseTool]] = []
    seen_classes: set[type] = set()
    #: node_type -> the class name that claimed it first.
    claimed: dict[str, str] = {}
    #: Classes a scanned module re-exported, judged after the whole folder has
    #: been walked — "defined elsewhere" is only innocent if that elsewhere was
    #: itself scanned, and we cannot know that until the walk is over.
    reexported: list[tuple[type, str]] = []

    for path in sorted(tools_dir.glob("*.py")):
        if path.stem.startswith("_"):
            # IGNORED. `_helpers.py`/`__init__.py` are private by the same
            # convention `discover_functions` uses for `_helper()`. A tool
            # *defined* in one and re-exported is caught after this loop.
            continue
        qualified_module = f"{slug}.tools.{path.stem}"
        try:
            module = _import_module(path, qualified_module)
        except Exception as exc:
            _note(
                warnings,
                f"Tool module {path.name} could not be imported "
                f"({type(exc).__name__}: {exc}) — every tool it defines is missing from "
                "this run.",
                exc_info=True,
            )
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseTool or not issubclass(obj, BaseTool):
                # IGNORED. The settled predicate: the folder scopes where to
                # look, subclassing decides what counts. A Pydantic Args model
                # or a helper class living beside a tool is not a finding.
                continue
            if obj.__module__ != qualified_module:
                reexported.append((obj, path.name))
                continue
            if obj in seen_classes:
                # IGNORED. `inspect.getmembers` yields one class once per name
                # it is bound to; an alias is not a second tool.
                continue
            if inspect.isabstract(obj):
                if _is_deliberate_base(obj):
                    # IGNORED, loudly in the log only: a family parent named
                    # `_AcmeBase`/`AbstractAcme`/`BaseAcme` is doing its job.
                    logger.debug(
                        "Passing over deliberate tool base %s in %s", obj.__name__, path.name
                    )
                else:
                    _note(warnings, f"{_abstract_tool_diagnosis(obj)} (in tools/{path.name})")
                continue
            seen_classes.add(obj)
            try:
                instance = obj()
            except Exception as exc:
                _note(
                    warnings,
                    f"Tool {obj.__name__} in tools/{path.name} could not be constructed "
                    f"({type(exc).__name__}: {exc}) — it is missing from this run.",
                    exc_info=True,
                )
                continue
            if instance.node_type:
                first = claimed.get(instance.node_type)
                if first is not None:
                    _note(
                        warnings,
                        f'Tool node type "{instance.node_type}" is declared by both {first} '
                        f"and {obj.__name__} in {slug}/tools — {obj.__name__} wins and "
                        f"{first} can never be bound. Give one of them its own node_type.",
                    )
                else:
                    claimed[instance.node_type] = obj.__name__
            else:
                # IGNORED. `BaseTool.node_type` documents empty as "not
                # placeable on a canvas", which is correct for a tool only ever
                # handed to an agent programmatically. Listable, not bindable.
                logger.debug(
                    "Tool %s declares no node_type; listable but not placeable", obj.__name__
                )
            found.append((f"{slug}/tools.{obj.__name__}", instance))

    _warn_about_unreachable_reexports(reexported, seen_classes, tools_dir, warnings)
    return found


def _source_file(cls: type) -> Path | None:
    """Which file a class was written in, without trusting `sys.modules`.

    `inspect.getfile` resolves a class through `sys.modules[cls.__module__]`,
    and discovery deliberately loads modules *without* registering them there
    (that is how two workflows' identically named files stay apart). So the
    reliable signal is the bytecode of any function the class body defines.
    """
    for member in cls.__dict__.values():
        code = getattr(member, "__code__", None)
        if code is not None:
            return Path(code.co_filename).resolve()
    try:
        return Path(inspect.getfile(cls)).resolve()
    except (TypeError, OSError):
        return None


def _warn_about_unreachable_reexports(
    reexported: list[tuple[type, str]],
    seen_classes: set[type],
    tools_dir: Path,
    warnings: list[str] | None,
) -> None:
    """The `__module__` guard's blind spot, made visible.

    The guard exists so an `__init__.py` re-export does not register the same
    tool twice, and for a class defined in a *scanned* module it is exactly
    right. But a class defined in `tools/_hidden.py` — private, never scanned —
    and re-exported from a public module reads as present in the source and is
    absent from every run: the same silent-loss shape as the abstract skip.

    Scoped by file location on purpose: `from openstategraph.prebuilt_web
    import WebSearchTool` is a legitimate reuse of a framework tool, not a lost
    capability, and only a class whose own file sits in *this* `tools/` folder
    is something this workflow meant to ship.
    """
    folder = tools_dir.resolve()
    for cls, through in reexported:
        if cls in seen_classes:
            continue
        origin = _source_file(cls)
        if origin is None or origin.parent != folder or origin.name == through:
            continue
        _note(
            warnings,
            f"Tool {cls.__name__} is re-exported by tools/{through} but defined in "
            f"tools/{origin.name}, which discovery does not scan (a leading underscore "
            "means private) — so it is absent from this run. Move the class into a module "
            "without a leading underscore.",
        )


def discover_tool_registry(
    workflow_dir: Path,
    slug: str,
    *,
    warnings: list[str] | None = None,
) -> dict[str, BaseTool]:
    """The runtime's tool registry: canvas node type → tool instance.

    Keyed by each tool's **own** `node_type` declaration — the single source
    of truth for wiring identity (ticket 33). A tool that declares none is
    listable but not placeable, so it is simply absent here.
    """
    registry: dict[str, BaseTool] = {}
    for _, instance in discover_tool_instances(workflow_dir, slug, warnings=warnings):
        if instance.node_type:
            registry[instance.node_type] = instance
    return registry


def discover_tools(
    workflow_dir: Path,
    slug: str,
    *,
    warnings: list[str] | None = None,
) -> list[ToolCapability]:
    """Every `BaseTool` subclass defined in `<workflow_dir>/tools/*.py`.

    Only classes *defined* in the scanned module count — an import re-exported
    through the module (e.g. `from .other import SomeTool`) is skipped by
    checking `__module__`, so an `__init__.py` re-export never registers the
    same tool twice under two different qualified ids.

    `warnings` is the same optional sink `discover_tool_instances` takes. The
    *listing* path had never passed one, so a tool module that would not import
    was a WARNING in a server log and an empty palette in the editor — the
    silence register PK-06 names. The capabilities endpoint passes one.
    """
    return [
        ToolCapability(
            id=qualified_id,
            name=instance.name,
            description=instance.description,
            args_schema=instance.Args.model_json_schema(),
            node_type=instance.node_type,
        )
        for qualified_id, instance in discover_tool_instances(
            workflow_dir, slug, warnings=warnings
        )
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


# No `__all__` here on purpose. In Python `__all__` reads as "this is the
# public surface", and this module is Tier 3 — internal, no stability
# guarantee (see `openstategraph/api/__init__.py`). The names it exported
# were the ones it hands its own siblings, and a third party would have read
# that as a promise. `openstategraph.__all__` and `openstategraph.abc` are
# the promises.


def discover_skills(workflow_dir: Path) -> str:
    """Procedural memory, file-first (tickets 65+66): `skills/*.md` under a
    workflow package, concatenated as prompt context for its agents.

    Deliberately the simplest honest tier of the skills ladder — full
    progressive disclosure (deepagents' 3-level SKILL.md loading) belongs to
    the deep tier and is recorded on ticket 66. A missing directory is the
    common case and costs nothing.

    These are the package's **ambient** skills, and they stay *context*: they
    are house style for every agent in the package, not a choice made about one
    node. A skill **wired to a node's `skill` port** is the other thing, and it
    lands in the *rules* — see `docs/decisions/skill-layer.md`.

    Frontmatter is parsed rather than pasted (`SkillDocument`): a file that
    declares a `name` is headed by it, and no YAML block reaches the model.
    """
    skills_dir = workflow_dir / "skills"
    if not skills_dir.is_dir():
        return ""
    from openstategraph.skills import SkillDocument

    parts: list[str] = []
    for path in sorted(skills_dir.glob("*.md")):
        skill = SkillDocument.load(path)
        if skill.body:
            heading = f"## Skill: {skill.name}"
            if skill.description:
                heading += f"\n{skill.description}"
            parts.append(f"{heading}\n{skill.body}")
    return "\n\n".join(parts)


def discover_middlewares(workflow_dir: Path, slug: str) -> dict[str, Any]:
    """Workflow-supplied middleware, one slot per file (tickets 32+37).

    `middlewares/<slot_name>.py` must expose a module-level `MIDDLEWARE`
    object (any LangChain `AgentMiddleware` — including the library's own
    prebuilts, pre-configured). The file's stem IS the slot name, so a file
    called `summarization.py` *replaces* the tier's summarization slot and a
    novel name adds a new slot — local fills-or-replaces, the base keeps the
    canonical order. Rarely needed (the prebuilts cover most cases — the
    user's own words on ticket 37); when it is, it is one file, no
    registration.
    """
    middlewares_dir = workflow_dir / "middlewares"
    if not middlewares_dir.is_dir():
        return {}
    found: dict[str, Any] = {}
    for path in sorted(middlewares_dir.glob("*.py")):
        if path.stem.startswith("_"):
            continue
        try:
            module = _import_module(path, f"{slug}.middlewares.{path.stem}")
        except Exception:
            logger.warning("Skipping unimportable middleware module %s", path, exc_info=True)
            continue
        middleware = getattr(module, "MIDDLEWARE", None)
        if middleware is None:
            logger.warning("%s defines no MIDDLEWARE object; skipped", path)
            continue
        found[path.stem] = middleware
    return found
