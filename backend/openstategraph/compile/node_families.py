"""node type -> the family that builds it. The compiler's registration seam.

`NodeRuntime._builders` is the built-in half of this dispatch and stays a
literal table of bound methods: those are the families this build implements
itself, they are checked first, and nothing installed can shadow one. This
module is the other half — the families an installed distribution contributes
through the `openstategraph.node_families` entry-point group, so that adding a
node *family* stops being an edit to `compile/node_runtime.py`
(install-experience ticket 08).

**Not public.** `openstategraph.abc` states the rule this follows: the ladders
are semver-public and the registries are not, "precisely so the registry
objects stay free to change shape". A plugin author writes an entry-point
stanza and a `BaseNodeFamily` subclass; nothing here is in their import list.
"""

from __future__ import annotations

import logging
from typing import Any

from openstategraph.abc.node_family import INodeFamily

logger = logging.getLogger(__name__)

#: Node-type prefixes a distribution may not claim.
#:
#: `function.` because a `function.<name>` node binds a callable by the name
#: written in the *document*, and the document belongs to the package: a
#: distribution able to inject one would change what a package's own node
#: resolves to, with nowhere in the document to name the provider or even to
#: see that a provider exists. That is `extensions`' own reasoning for
#: refusing an `openstategraph.functions` group, and it does not stop being
#: true when the same claim arrives dressed as a node family.
#:
#: `workflow.` because `workflow.subgraph` is not a node type in the ordinary
#: sense — it mounts a second document, and the whole mount/override contract
#: is the compiler's own.
RESERVED_PREFIXES = ("function.", "workflow.")


class NodeFamilyRegistry:
    """The families this process knows about, and who contributed each.

    Small on purpose: `register`, `get`, `types` and `source_of`. It is a
    lookup that also remembers attribution — which is not decoration, because
    the only useful sentence about a node family that is missing or shadowed
    names the distribution to go and fix.
    """

    def __init__(self) -> None:
        self._families: dict[str, INodeFamily] = {}
        self._sources: dict[str, str] = {}

    def register(self, family: Any, *, source: str = "a local registration") -> str | None:
        """Register `family`, or return one sentence saying why not.

        Returns rather than raises, for the reason every other discovery path
        here does: one half-installed plugin in a venv must never cost an
        adopter every other capability in it. The caller decides whether the
        sentence becomes a log line, a compile warning, or both.
        """
        node_type = str(getattr(family, "node_type", "") or "")
        if not node_type:
            return (
                f"Node family {type(family).__name__!r} from {source} declares no "
                "node_type, so no document could name it."
            )
        if not isinstance(family, INodeFamily):
            return (
                f"Node family {type(family).__name__!r} from {source} has no build(context) "
                "method — see openstategraph.abc.BaseNodeFamily."
            )
        if node_type.startswith(RESERVED_PREFIXES):
            return (
                f'{source} claims node type "{node_type}", which is reserved by the '
                "compiler itself. Namespace it under your own prefix instead."
            )
        first = self._sources.get(node_type)
        if first is not None:
            # Two distributions claiming one wiring identity is ambiguity, not
            # a precedence question — the same call `_discover_tools` makes,
            # and the same answer: name both, register the last.
            return (
                f'Two node families claim node type "{node_type}": {first} and {source}. '
                f"{source} wins; {first}'s family can never be built. Uninstall one, or "
                "ask its author to namespace the node type."
            )
        self._families[node_type] = family
        self._sources[node_type] = source
        return None

    def get(self, node_type: str) -> INodeFamily | None:
        """The family serving this node type, or `None`."""
        return self._families.get(node_type)

    def types(self) -> frozenset[str]:
        """Every node type this registry can build."""
        return frozenset(self._families)

    def source_of(self, node_type: str) -> str:
        """Who contributed this node type — for a sentence a user can act on."""
        return self._sources.get(node_type, "an unknown source")


def discovered_node_families() -> tuple[NodeFamilyRegistry, list[str]]:
    """`(registry, warnings)` for the installed `openstategraph.node_families`.

    Resolved once per process by `extensions`' own cache, so this is cheap to
    call per `NodeRuntime`; the returned registry is **shared**, and therefore
    read-only to callers, exactly as `Discovered` is.
    """
    from openstategraph.extensions import entry_point_node_families

    found = entry_point_node_families()
    registry = found.values
    assert isinstance(registry, NodeFamilyRegistry)
    return registry, list(found.warnings)


__all__ = [
    "RESERVED_PREFIXES",
    "NodeFamilyRegistry",
    "discovered_node_families",
]
