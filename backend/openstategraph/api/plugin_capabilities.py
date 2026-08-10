"""App-scoped capabilities: what an *installed distribution* puts in the palette.

Register **PK-06**. Ticket 05 made a third party's tool bindable — write one
`[project.entry-points."openstategraph.tools"]` stanza, `pip install`, and the
runtime resolves `tool.acme-ping`. Nothing put it in the editor. So "extend
without forking" was half a promise: the capability existed and no user could
wire it, because authoring an atom is a two-place job (a Python tool the
runtime binds, a node definition the editor renders) and a third party cannot
add a TypeScript file to this repository.

**One registry, two readers.** Everything here reads
`api.registries.process_tool_layer()` — the same cached `(built-in, plugin)`
layer `build_tool_registry` itself lays down for a run. A second, hand-kept
list of "tools the palette may show" would drift within a release, and the
drift's shape is the worst one available: a palette offering a card the
runtime cannot bind.

**Scope is part of the payload, not a guess.** A workflow's own `tools/`
capability travels with that workflow and vanishes when another is opened
(`capability_discovery.py`); a plugin's tool is installed process-wide and is
available in *every* workflow. The palette already draws that distinction
("This workflow" versus the always-available sections), so the two are
reported as two lists rather than one list with a flag the editor has to
interpret.

**Precedence is spoken aloud.** The documented order is built-in < installed
plugin < workflow-local, so a plugin claiming `tool.web-search` legitimately
replaces the bundled one — that is what installing a plugin is *for*. But a
palette card that silently changes identity because of an unrelated
`pip install` is how a user stops trusting the palette, so the replacement is
reported on the tool (`replaces_builtin`) *and* as a warning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: Where a developer who did half the job is sent. Named in the message rather
#: than left to a search, because the whole point of the message is that the
#: reader currently has no idea a second place exists.
AUTHORING_DOC = "docs/building-an-atom.md"


@dataclass(frozen=True)
class PluginToolCapability:
    """One installed distribution's tool, as the editor needs to render it.

    `id` is the tool's own `node_type`, deliberately — unlike a workflow-local
    capability, whose id is qualified by the slug that owns it, a plugin's tool
    is process-wide and its `node_type` *is* its identity. The editor registers
    the node type under this id, so a document that binds `tool.acme-ping`
    resolves to the same string at both ends.
    """

    id: str
    name: str
    description: str
    args_schema: dict[str, Any]
    node_type: str
    #: The distribution to thank, or to blame — always shown on the card.
    distribution: str
    #: `ToolField`s the tool declared, already flattened to JSON.
    fields: list[dict[str, Any]] = field(default_factory=list)
    #: True when this node type also exists as a bundled tool, which this one
    #: replaces per the documented ordering.
    replaces_builtin: bool = False


def _field_payload(spec: Any) -> dict[str, Any]:
    """One `ToolField` as data, tolerant of a plugin that got it slightly wrong.

    A plugin's declaration is a stranger's code: it may be a `ToolField`, or a
    plain dict written against a doc example. Both are accepted and normalised
    here rather than in the editor, so exactly one place knows the shape.
    """
    def get(name: str, default: Any = None) -> Any:
        if isinstance(spec, dict):
            return spec.get(name, default)
        return getattr(spec, name, default)

    key = str(get("key", "") or "")
    options = get("options", ()) or ()
    return {
        "key": key,
        "label": str(get("label", "") or "") or key,
        "kind": str(get("kind", "text") or "text"),
        "default_value": get("default_value", ""),
        "placeholder": str(get("placeholder", "") or ""),
        "hint": str(get("hint", "") or ""),
        "options": [
            {"value": str(option), "label": str(option)}
            if isinstance(option, str)
            else {"value": str(option[0]), "label": str(option[-1])}
            for option in options
        ],
    }


def _declared_fields(tool: Any, node_type: str, distribution: str) -> tuple[list[dict[str, Any]], list[str]]:
    """`node_fields`, validated. A malformed field costs its card nothing."""
    specs = getattr(tool, "node_fields", ()) or ()
    fields: list[dict[str, Any]] = []
    warnings: list[str] = []
    for spec in specs:
        try:
            payload = _field_payload(spec)
        except Exception as exc:  # a stranger's object, shaped like nothing
            warnings.append(
                f'{distribution} declared an unreadable card field on "{node_type}" '
                f"({type(exc).__name__}: {exc}); the field is not shown."
            )
            continue
        if not payload["key"]:
            warnings.append(
                f'{distribution} declared a card field with no key on "{node_type}"; '
                "there is nowhere for its value to be stored, so it is not shown."
            )
            continue
        fields.append(payload)
    return fields, warnings


def plugin_tool_capabilities() -> tuple[list[PluginToolCapability], list[str]]:
    """Every installed distribution's tool, plus everything that failed.

    The warnings are the loader's own (a distribution that would not import, a
    tool with no `node_type`, two distributions claiming one) with the
    built-in-replacement notices added — the honesty rule ticket 05 set, now
    reaching the surface a user actually looks at.
    """
    from openstategraph.api.registries import process_tool_layer

    builtin, discovered = process_tool_layer()
    warnings = list(discovered.warnings)
    capabilities: list[PluginToolCapability] = []

    for node_type, tool in sorted(discovered.values.items()):
        distribution = discovered.sources.get(node_type) or "an installed distribution"
        try:
            args_schema = tool.Args.model_json_schema()
        except Exception as exc:
            warnings.append(
                f'{distribution} ships "{node_type}" with an argument model the editor '
                f"cannot read ({type(exc).__name__}: {exc}); its card has no arguments."
            )
            args_schema = {}
        fields, field_warnings = _declared_fields(tool, node_type, distribution)
        warnings.extend(field_warnings)
        replaces_builtin = node_type in builtin
        if replaces_builtin:
            warnings.append(
                f'{distribution} replaces the built-in tool "{node_type}". Installed '
                "plugins outrank built-ins (built-in < plugin < workflow-local), so the "
                f"palette shows {distribution}'s card and runs its tool. Uninstall it to "
                "get the bundled one back."
            )
        capabilities.append(
            PluginToolCapability(
                id=node_type,
                name=getattr(tool, "name", "") or node_type,
                description=getattr(tool, "description", "") or "",
                args_schema=args_schema,
                node_type=node_type,
                distribution=distribution,
                fields=fields,
                replaces_builtin=replaces_builtin,
            )
        )
    return capabilities, warnings


def bindable_tool_types() -> list[str]:
    """Every tool node type this process can bind, regardless of workflow.

    Built-ins plus installed plugins — the process-wide half of
    `build_tool_registry`. A workflow's own `tools/` are *not* here: they are
    discovered per slug and reported as workflow-scoped capabilities.
    """
    builtin, discovered = _layers()
    return sorted(set(builtin) | set(discovered.values))


def _layers() -> tuple[dict[str, Any], Any]:
    from openstategraph.api.registries import process_tool_layer

    builtin, discovered = process_tool_layer()
    try:
        from openstategraph.prebuilt_knowledge import knowledge_lookup_for

        builtin.update(knowledge_lookup_for(None))
    except Exception:  # pragma: no cover - the knowledge layer is optional
        logger.debug("Knowledge tool unavailable while listing bindable types", exc_info=True)
    return builtin, discovered


def editor_renderable_types() -> frozenset[str]:
    """Node types the editor can actually draw, read from the generated catalogue.

    `port_specs.json` is emitted from `src/nodes/**` (register RC-01), so this
    is not a hand-kept mirror of the TypeScript — it *is* the TypeScript,
    compiled. A missing artifact raises there rather than degrading to an empty
    set, which would make every tool look half-authored.
    """
    from openstategraph.compile.node_catalogue import CATALOGUE

    return CATALOGUE.node_types


def unrenderable_tool_warning(
    bindable: Iterable[str],
    renderable: Iterable[str],
    declared: Iterable[str],
) -> str | None:
    """The half-authored message: bindable by the runtime, invisible in the editor.

    A tool reaches the editor by one of two routes, and a type on neither is
    the two-place-authoring mistake this warning exists to end:

    - a **node definition in `src/nodes/tools/`**, which the generated
      catalogue reports (`renderable`) — how a *bundled* tool gets a card;
    - a **declaration in the capabilities payload** (`declared`) — a plugin's
      `node_fields`, or a workflow-local discovery, which the editor renders
      generically with no TypeScript at all.

    Pure on purpose: the three sets are arguments, so the sentence a developer
    reads is testable without a registry, an entry point or an HTTP call.
    """
    renderable = frozenset(renderable)
    declared = frozenset(declared)
    missing = sorted({t for t in bindable if t and t not in renderable and t not in declared})
    if not missing:
        return None
    listed = ", ".join(missing)
    return (
        f"{len(missing)} tool{'s' if len(missing) > 1 else ''} the runtime can bind "
        f"{'have' if len(missing) > 1 else 'has'} no editor card, so no one can wire "
        f"{'them' if len(missing) > 1 else 'it'} on a canvas: {listed}. A tool is authored "
        "in two places — the Python tool and the node definition the editor renders. Add "
        "one in src/nodes/tools/ and run `npm run generate:ports`, or declare the card from "
        f"the tool itself with `node_fields` and ship it as a plugin ({AUTHORING_DOC}, "
        "Part 3)."
    )


# No `__all__`, for the reason `capability_discovery.py` states at its own
# foot: this is a Tier 3 module with no stability guarantee, and `__all__`
# reads as a promise. `openstategraph.abc.ToolField` is the promise a plugin
# author depends on; everything here is how this server uses it.
