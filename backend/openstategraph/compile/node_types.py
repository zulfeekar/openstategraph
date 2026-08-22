"""node type -> the builder for it. The compiler's own dispatch table.

Two registries answer "what builds this node type", and they are separate
because their *audiences* are:

- `node_families.NodeFamilyRegistry` holds what an installed distribution
  contributed. Every refusal there **returns a sentence** rather than raising,
  because one half-installed plugin in a venv must not cost an adopter every
  other capability in it.
- this one holds the table **this build implements itself**. A second claim on
  one node type here is a programming error in our own source, so it raises,
  and the loudest moment to find it is import.

It is a `Registry<T>` in CLAUDE.md's sense — the behaviour, not a shared
address: a duplicate id throws, `upsert` is how you say you meant it, `list()`
enumerates, and a fresh one is constructible so registrations cannot leak
between tests. There is no module-level singleton on purpose.

**The one thing a plain dict could not hold, and why the second arm was an
`if`.** `builder_for` used to carry two branches after its dict lookup:
`workflow.subgraph`, and *any* type beginning `function.`. The first is a
closed set (`validation.MOUNT_NODE_TYPES`, one element) and was always just a
key somebody had not registered. The second is not a set at all — a
`function.<name>` node binds a callable named in the **document**, so the keys
are whatever a package's `functions/` folder defines and cannot be known when
the table is built. That is an **open namespace**, and it is a first-class
registration here (`register_namespace`) rather than a branch, so the whole
dispatch policy is one enumerable object instead of a table plus some control
flow no test could walk.

Exact registrations beat the namespace they fall under. That order is load-
bearing rather than incidental: `function.format_report` is a built-in, and a
package defining its own `format_report` must not shadow it silently — the
defect `export-and-eject/11` paid for.

**Not public.** `openstategraph.abc` states the rule: the ladders are
semver-public and the registries are not, so the registry objects stay free to
change shape.
"""

from __future__ import annotations

from typing import Any, Callable

#: A node builder: `(node_id, node, plan) -> graph node callable`.
NodeBuilder = Callable[..., Any]


class NodeTypeRegistry:
    """Node type -> builder, with an open-namespace arm.

    Small on purpose — `register`, `upsert`, `register_namespace`, `resolve`,
    `types`, `namespaces`, `list`, `mapping`. It is a lookup; everything about
    *what* is registered lives with the thing registering it.
    """

    def __init__(self) -> None:
        self._exact: dict[str, NodeBuilder] = {}
        self._namespaces: list[tuple[str, NodeBuilder]] = []

    def register(self, node_type: str, builder: NodeBuilder) -> None:
        """Claim one node type. Raises if it is already claimed."""
        if node_type in self._exact:
            raise ValueError(
                f'Node type "{node_type}" is already registered. Two claims on one '
                "node type is ambiguity, not precedence — use upsert() if you meant "
                "to replace it."
            )
        self._exact[node_type] = builder

    def upsert(self, node_type: str, builder: NodeBuilder) -> None:
        """Claim one node type, replacing any existing claim. Saying you meant it."""
        self._exact[node_type] = builder

    def register_namespace(self, prefix: str, builder: NodeBuilder) -> None:
        """Claim every node type under `prefix`. Raises if the prefix is claimed.

        For a family whose members are named by the document rather than by
        this table — see the module docstring.
        """
        if any(prefix == claimed for claimed, _ in self._namespaces):
            raise ValueError(
                f'Node-type namespace "{prefix}*" is already registered. '
                "Use upsert_namespace() if you meant to replace it."
            )
        self._namespaces.append((prefix, builder))

    def upsert_namespace(self, prefix: str, builder: NodeBuilder) -> None:
        """`register_namespace`, replacing any existing claim on the prefix."""
        self._namespaces = [entry for entry in self._namespaces if entry[0] != prefix]
        self._namespaces.append((prefix, builder))

    def resolve(self, node_type: str) -> NodeBuilder | None:
        """The builder for this node type, or `None` if nothing here claims it.

        Exact first, then the longest matching namespace, so a built-in can
        never be shadowed by the open family it happens to sit inside.
        """
        exact = self._exact.get(node_type)
        if exact is not None:
            return exact
        best: tuple[str, NodeBuilder] | None = None
        for prefix, builder in self._namespaces:
            if node_type.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
                best = (prefix, builder)
        return None if best is None else best[1]

    def types(self) -> frozenset[str]:
        """Every node type registered by exact name.

        Namespaces are deliberately absent: this answers "which types does
        this build name", and an open namespace names none of them. The
        shadow reports in `NodeRuntime` depend on that reading.
        """
        return frozenset(self._exact)

    def namespaces(self) -> tuple[str, ...]:
        """Every prefix registered as an open namespace, in registration order."""
        return tuple(prefix for prefix, _ in self._namespaces)

    def list(self) -> tuple[tuple[str, NodeBuilder], ...]:
        """Every registration, exact ones first, namespaces shown as `prefix*`."""
        return tuple(self._exact.items()) + tuple(
            (f"{prefix}*", builder) for prefix, builder in self._namespaces
        )

    def mapping(self) -> dict[str, NodeBuilder]:
        """A copy of the exact registrations, for callers that want a dict."""
        return dict(self._exact)


__all__ = ["NodeBuilder", "NodeTypeRegistry"]
