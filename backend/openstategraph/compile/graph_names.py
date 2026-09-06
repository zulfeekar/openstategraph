"""Which canvas node, in which document, a compiled graph name refers to.

A compiled `StateGraph` names its nodes with `safe_name(node_id)`, and a run's
frames carry those names. Turning one back into something a user's open canvas
can light up takes two maps, and they always travelled together — as two
attributes on `NodeRuntime`, read by `api/streaming.py` through
`getattr(runtime, name, None) or {}` because the contract was loose
(reviews-2026-08-14 ticket 07).

They are one question in two halves, and the second half exists because the
first is not enough. `node_ids_by_name` cannot say *which document* a resolved
id belongs to: the shipped `concierge` mounts `chinook-assistant`, and both
documents have an `in1`, a `router1` and an `out1`. Without `mount_slugs` a
client with the child open lights its `router1` when the **parent's** router
ran — a quieter version of the lie tickets 33/34 are about.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


class GraphNames:
    """The naming half of a run's path: graph name -> canvas node, and mount
    path -> the document that mount descends into.

    One reason to change: how a compiled name relates to what a user drew.
    """

    def __init__(self) -> None:
        self._node_ids: dict[str, str] = {}
        self._mount_slugs: dict[str, str] = {}

    @property
    def node_ids_by_name(self) -> Mapping[str, str]:
        """Graph node name -> the canvas node id it was compiled from."""
        return MappingProxyType(self._node_ids)

    @property
    def mount_slugs(self) -> Mapping[str, str]:
        """Mount path -> the workflow slug that mount descends into."""
        return MappingProxyType(self._mount_slugs)

    def remember(self, name: str, node_id: str) -> None:
        """Note that `name` is `node_id`. **The first writer wins.**"""
        self._node_ids.setdefault(name, node_id)

    def mounted(self, mount_path: str, slug: str) -> None:
        """Note that the mount at `mount_path` descends into `slug`."""
        self._mount_slugs[mount_path] = slug

    def absorb(self, child: GraphNames, *, through: str, slug: str) -> None:
        """Fold a mounted child's names into this document's.

        Upward, because the child's frames ride the **parent's** one SSE
        stream — the parent's stream fold is the only place that can resolve
        them.

        The two halves fold by opposite rules, which is the substance here:

        - **Names merge first-wins.** This document's own answer stays
          authoritative where two documents share an id.
        - **Mount slugs are re-keyed by the whole path.** Node ids are unique
          within a document and nowhere else, so two sibling subtrees that
          each mount at a node called `inner` are two different mounts of two
          different packages. A flat map collapsed them first-wins and
          attributed one's frames to the other's slug.

        Call this **after the child's `build()`**, not after its `factory()`:
        a mount inside the child is resolved by that build, so a grandchild's
        ids only exist on the child once it has run. Reading them earlier is
        what left ticket 25's leak open two levels down — for A mounts B
        mounts C, C's router and grader names never reached the fold.
        """
        for name, canvas_id in child.node_ids_by_name.items():
            self.remember(name, canvas_id)
        self.mounted(through, slug)
        for mount_path, mounted_slug in child.mount_slugs.items():
            self.mounted(f"{through}/{mount_path}", mounted_slug)
