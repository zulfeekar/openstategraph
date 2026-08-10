"""Extension without forking — what a third party's `pip install` registers.

**Tier 1 — semver-public.** The *group names* below are the contract: a third
party writes them into their own `pyproject.toml`, so renaming one silently
un-registers every plugin that ever shipped against it. The functions here are
public too, but almost nobody calls them: a plugin author writes a stanza, and
the framework does the rest.

    # in the THIRD PARTY's pyproject.toml
    [project.entry-points."openstategraph.tools"]
    acme = "acme_osg_tools:TOOLS"

**Why entry points at all**, when none of `langgraph`, `deepagents` or
`langgraph-supervisor` uses them: all three are published by the organisation
that owns the layer beneath them, so "send a PR upstream" is a real option for
their users. It is not for ours — `docs/adoption.md` states the honest cost of
editing this repo ("a merge you own forever"), and a framework that can only be
extended by the people who ship it is a closed system with extra steps.

**This is a third discovery source layered under the two that already exist,
not a new mechanism.** `build_tool_registry` already merges bundled defaults
with the open package's own `tools/`; entry points slot in between:

    built-in  <  third-party (here)  <  workflow-local

That order is the point. A plugin author may legitimately replace a bundled
default — that is what installing a plugin is *for* — while a package author's
own `tools/` still wins over whatever else happens to be in the venv, which is
the local-shadows-global rule the registry has always documented. A plugin that
could silently outrank a package's own tool would make a workflow's behaviour
depend on an unrelated `pip install`.

**Three properties, all of which mirror behaviour this codebase already gets
right:**

- **Honest.** Every entry point loads inside its own `try/except`. A failure
  logs one WARNING *naming the distribution*, lands on the returned
  `Discovered.warnings` (and from there on `CompiledWorkflow.warnings`), and is
  skipped. One half-installed plugin in a venv must never cost an adopter every
  other capability in it — the same rule the bundled Chinook guard follows.
- **Cheap.** Nothing here is imported at module scope: `importlib.metadata`
  enumeration walks `sys.path`, and `import openstategraph` is on every
  adopter's critical path. Discovery happens when a registry is built.
- **Switchable.** `OPENSTATEGRAPH_DISABLE_PLUGINS=1` excludes the whole
  mechanism, so a reproducible run does not depend on a colleague's venv.

**Two groups, deliberately — and `openstategraph.functions` is not one of
them.** A `function.<name>` node binds a callable by the name written in the
*document*, and the document belongs to the package; a distribution that could
inject `function.format_report` process-wide would change what a package's own
node resolves to, with nowhere in the document to name the provider or even to
see that a provider exists. Tools do not have that problem because a tool
carries its own namespaced `node_type` (`tool.acme-ping`), which is visible in
the document and collides loudly rather than quietly. Functions stay
package-local; a third party who wants to ship one ships a tool.

The **middleware** group sketched in `docs/decisions/framework-packaging.md`
§3.5 is deliberately still **not** reserved here: a group name is a promise,
and promising one we have not implemented would be exactly the decorative
contract this work exists to remove. The **provider** group beside it is now
implemented (ticket 02) and therefore reserved — see `PROVIDERS_GROUP` and
`openstategraph.providers`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Tools: a `BaseTool` subclass, an instance, or an iterable of either. Each
#: one is merged into the runtime tool registry under its own `node_type`.
TOOLS_GROUP = "openstategraph.tools"

#: Knowledge builders: an `IKnowledgeBuilder` concrete (class or instance), or
#: an iterable of them. Appended *after* the built-in ladder, so the mechanical
#: builders stamp ownership of their topics first.
KNOWLEDGE_BUILDERS_GROUP = "openstategraph.knowledge_builders"

#: Providers: an `openstategraph.providers.ProviderSpec`, or an iterable of
#: them. Loaded *after* the bundled three, so a plugin may replace a built-in's
#: default model — the same built-in < third-party order tools follow.
PROVIDERS_GROUP = "openstategraph.providers"

#: Every group this framework reads. Nothing else is a supported seam.
ENTRY_POINT_GROUPS = (TOOLS_GROUP, KNOWLEDGE_BUILDERS_GROUP, PROVIDERS_GROUP)

#: Set to `1`/`true`/`yes` to load nothing from the environment's entry points.
DISABLE_PLUGINS_ENV = "OPENSTATEGRAPH_DISABLE_PLUGINS"


@dataclass(frozen=True)
class Discovered:
    """What one group produced — and, just as importantly, what it did not.

    `warnings` is not a log-shaped afterthought: it is carried to
    `CompiledWorkflow.warnings` so that a capability which failed to appear is
    attributable to the distribution that failed to supply it.
    """

    #: The group's product: `{node_type: tool}` for tools, a list for builders.
    values: Any
    warnings: list[str] = field(default_factory=list)


def plugins_enabled() -> bool:
    """False when `OPENSTATEGRAPH_DISABLE_PLUGINS` names a truthy value."""
    return os.environ.get(DISABLE_PLUGINS_ENV, "").strip().lower() not in ("1", "true", "yes")


def _distribution_of(entry_point: Any) -> str:
    """The distribution name to blame, or an honest stand-in for it."""
    distribution = getattr(entry_point, "dist", None)
    return str(getattr(distribution, "name", None) or "an unknown distribution")


def _load_group(group: str) -> tuple[list[tuple[Any, Any]], list[str]]:
    """`(entry_point, loaded_object)` pairs, plus one warning per failure.

    Imported here rather than at module scope: see the module docstring.
    """
    if not plugins_enabled():
        return [], []

    from importlib.metadata import entry_points

    try:
        found = list(entry_points(group=group))
    except Exception as exc:  # a broken .dist-info in the environment
        message = (
            f"Could not enumerate {group!r} extensions ({type(exc).__name__}: {exc}); "
            "continuing without any."
        )
        logger.warning(message, exc_info=True)
        return [], [message]

    loaded: list[tuple[Any, Any]] = []
    warnings: list[str] = []
    for entry_point in found:
        try:
            loaded.append((entry_point, entry_point.load()))
        except Exception as exc:
            warnings.append(_skipped(entry_point, group, f"{type(exc).__name__}: {exc}"))
    return loaded, warnings


def _skipped(entry_point: Any, group: str, why: str) -> str:
    """One warning, logged and returned, always naming who to go and fix."""
    message = (
        f"Extension {getattr(entry_point, 'name', '?')!r} from "
        f"{_distribution_of(entry_point)} (group {group!r}) was skipped: {why}"
    )
    logger.warning(message)
    return message


def _each(obj: Any) -> list[Any]:
    """One object or many, without guessing at anything cleverer.

    A plugin author writes `= AcmeTool` or `= TOOLS` and should not have to
    know which we accept, so both work. A string is never an iterable here —
    that way an entry point pointing at a module attribute holding a name
    fails loudly instead of registering 9 one-character tools.
    """
    if isinstance(obj, (str, bytes)) or isinstance(obj, type):
        return [obj]
    try:
        return list(obj)
    except TypeError:
        return [obj]


def entry_point_tools() -> Discovered:
    """`{node_type: tool instance}` contributed by installed distributions.

    Keyed by each tool's own `node_type`, exactly as workflow-local discovery
    is: the tool declares its wiring identity, and a tool that declares none is
    reported rather than silently dropped, because there is nothing a document
    could bind it to.
    """
    import inspect

    from openstategraph.abc.tool import BaseTool, _abstract_tool_diagnosis

    registry: dict[str, Any] = {}
    #: node_type -> the distribution that claimed it first, so the second
    #: claimant is reported rather than silently overwriting the first.
    claimed: dict[str, str] = {}
    loaded, warnings = _load_group(TOOLS_GROUP)
    for entry_point, obj in loaded:
        for candidate in _each(obj):
            if isinstance(candidate, type) and issubclass(candidate, BaseTool):
                if inspect.isabstract(candidate):
                    # The RC-04 trap, aimed outward. `candidate()` would raise
                    # a TypeError here anyway, but its message ("Can't
                    # instantiate abstract class X with abstract method
                    # _execute") describes the symptom, not the mistake — and a
                    # stranger's class is exactly the code we cannot go and
                    # read for them. Say which method they implemented instead.
                    warnings.append(
                        _skipped(entry_point, TOOLS_GROUP, _abstract_tool_diagnosis(candidate))
                    )
                    continue
            try:
                tool = candidate() if isinstance(candidate, type) else candidate
            except Exception as exc:
                warnings.append(
                    _skipped(
                        entry_point,
                        TOOLS_GROUP,
                        f"constructing {getattr(candidate, '__name__', candidate)!r} raised "
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if not isinstance(tool, BaseTool):
                warnings.append(
                    _skipped(
                        entry_point,
                        TOOLS_GROUP,
                        f"{type(tool).__name__} is not an openstategraph.abc.BaseTool",
                    )
                )
                continue
            if not tool.node_type:
                warnings.append(
                    _skipped(
                        entry_point,
                        TOOLS_GROUP,
                        f"tool {tool.name!r} declares no node_type, so no document could bind it",
                    )
                )
                continue
            first = claimed.get(tool.node_type)
            if first is not None:
                # Two installed distributions claiming one wiring identity is
                # not a precedence question the ordering rule answers — it is
                # ambiguity, and a dict update would resolve it by whichever
                # `.dist-info` sorted later. Name both; register the last.
                message = (
                    f'Two installed distributions claim tool node type "{tool.node_type}": '
                    f"{first} and {_distribution_of(entry_point)}. "
                    f"{_distribution_of(entry_point)} wins; {first}'s tool can never be "
                    "bound. Uninstall one, or ask its author to namespace the node type."
                )
                logger.warning(message)
                warnings.append(message)
            claimed[tool.node_type] = _distribution_of(entry_point)
            registry[tool.node_type] = tool
    return Discovered(values=registry, warnings=warnings)


def entry_point_knowledge_builders() -> Discovered:
    """Knowledge builders contributed by installed distributions.

    The same jail and the same honesty as tools. Order is the caller's
    business: `run_build` appends these *after* `BUILDERS`, so a built-in
    stamps ownership of a topic before a plugin can claim it, and a
    cross-builder collision is refused and reported rather than overwritten.
    """
    from openstategraph.knowledge_builders import BaseKnowledgeBuilder

    builders: list[Any] = []
    loaded, warnings = _load_group(KNOWLEDGE_BUILDERS_GROUP)
    for entry_point, obj in loaded:
        for candidate in _each(obj):
            try:
                builder = candidate() if isinstance(candidate, type) else candidate
            except Exception as exc:
                warnings.append(
                    _skipped(
                        entry_point,
                        KNOWLEDGE_BUILDERS_GROUP,
                        f"constructing {getattr(candidate, '__name__', candidate)!r} raised "
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if not isinstance(builder, BaseKnowledgeBuilder):
                warnings.append(
                    _skipped(
                        entry_point,
                        KNOWLEDGE_BUILDERS_GROUP,
                        f"{type(builder).__name__} does not extend BaseKnowledgeBuilder",
                    )
                )
                continue
            builders.append(builder)
    return Discovered(values=builders, warnings=warnings)


def entry_point_providers() -> Discovered:
    """`ProviderSpec`s contributed by installed distributions.

    The same jail and the same honesty as tools, with one difference worth
    stating: a spec is *data*, so there is nothing to construct and nothing a
    plugin's constructor can do to us. The only failure modes left are an
    import that raises and an object that is not a `ProviderSpec` — and both
    are reported against the distribution that shipped them rather than
    silently skipped.

    Order is the caller's business: `providers.load_provider_catalogue`
    registers these *after* the built-ins, so a plugin may deliberately
    replace a bundled provider.
    """
    from openstategraph.providers import ProviderSpec

    specs: list[Any] = []
    loaded, warnings = _load_group(PROVIDERS_GROUP)
    for entry_point, obj in loaded:
        for candidate in _each(obj):
            if not isinstance(candidate, ProviderSpec):
                warnings.append(
                    _skipped(
                        entry_point,
                        PROVIDERS_GROUP,
                        f"{type(candidate).__name__} is not an "
                        "openstategraph.providers.ProviderSpec",
                    )
                )
                continue
            specs.append(candidate)
    return Discovered(values=specs, warnings=warnings)


__all__ = [
    "DISABLE_PLUGINS_ENV",
    "ENTRY_POINT_GROUPS",
    "KNOWLEDGE_BUILDERS_GROUP",
    "PROVIDERS_GROUP",
    "TOOLS_GROUP",
    "Discovered",
    "entry_point_knowledge_builders",
    "entry_point_providers",
    "entry_point_tools",
    "plugins_enabled",
]
