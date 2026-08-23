"""Resolving a mount address to the document that instance actually runs.

Ticket 42. A workflow package is a **class**; a mount node in a parent
document is an **instance**, and its props are `data.overrides`
(`docs/decisions/mount-overrides.md`). `concierge/wf-music` names one instance;
a second mount of the same package, `concierge/wf-other`, is a different one.

The editor needs to *display* an instance, which means it needs the child
package with that mount's overrides applied. The recorded decision was to
**serve** that rather than mirror the merge in TypeScript: the merge has
exactly one owner — `apply_mount_overrides` — and a second implementation
would be duplicated knowledge buying only a round trip.

So nothing here merges. This module walks the chain and delegates, which is
why the return value carries `warnings` through unchanged: validation is loud
but not fatal, and the editor is the surface that must say so.

Its own file, beside `model_resolution.py`, for the same reason that one has
one: a single named resolution concern, kept out of `main.py`.
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple

from openstategraph.compile.node_runtime import apply_mount_overrides
from openstategraph.validation import MOUNT_NODE_TYPES

#: The node types that mount another workflow, as a set for membership tests.
#:
#: **Derived, never restated** (production-ready ticket 08). This module held
#: its own literal, and so did three others; the fact is one fact, and the
#: cost of four copies is that a contributor adding a third organism edits the
#: two obvious ones and their mount silently fails to resolve in knowledge
#: building and in the architect's view of the platform — the two nobody
#: thinks to check. `validation.MOUNT_NODE_TYPES` is the declaration.
MOUNT_TYPES = frozenset(MOUNT_NODE_TYPES)


class MountResolutionError(Exception):
    """The address does not name an instance.

    Distinct from "the package is missing" (`WorkflowNotFoundError`) and from
    "that is not a slug" (`InvalidSlugError`), because the three are different
    answers and a caller renders them differently: a malformed address is a
    broken link, a missing package is a deleted workflow, and a segment that
    is not a mount is a hand-typed URL pointing at an ordinary node.
    """


class MountResolution(NamedTuple):
    """One instance, and everything a client needs to display it."""

    #: The **class** the instance is of — what capabilities, knowledge and the
    #: palette are still asked about, because those belong to the package.
    slug: str
    #: The mount node ids walked, from the root inward.
    mount_path: list[str]
    #: The child package with this mount's overrides applied. A copy; the
    #: package on disk is never written.
    document: dict[str, Any]
    #: Loud-but-not-fatal problems, in walk order — an override naming a child
    #: node id that does not exist, most often.
    warnings: list[str]


def resolve_mount_document(
    store: Any, root: str, mount_path: list[str], *, inherited: bool = False
) -> MountResolution:
    """Walk `root` inward along `mount_path`, applying each mount's overrides.

    Each step reads the mount node from the document produced by the *previous*
    step, not from the package on disk. That ordering is the whole of
    "recursion composes naturally": a grandparent may override a parent's
    `overrides` field itself, and only a walk that carries the merged document
    forward will see it.

    `inherited=True` skips **only the last** mount's overrides, answering "what
    would this instance run if it overrode nothing" — the value an inspector
    shows beside an overridden field, and the one a revert restores. It cannot
    be computed in the browser, because the override has already replaced the
    inherited value in the effective document.

    "The last level" really means **the overrides this address's own edits
    write to**. At depth one that is the root mount's `overrides`; at depth two
    it is the nested blob inside it, because a grandchild's override is
    expressed as an override of the parent's `overrides` field. The two are the
    same storage location by construction, which is what lets one flag serve
    every depth.

    Refuses rather than guesses, and every refusal names where the walk
    stopped — an address is usually hand-typed or stale, and "something went
    wrong" is not enough to fix either.
    """
    if not mount_path:
        # `/mounts/` must never quietly mean "the root document"; that question
        # already has an endpoint, and two endpoints answering it is how they
        # drift apart.
        raise MountResolutionError("a mount address needs at least one mount node id")

    document = store.load(root)
    slug = root
    warnings: list[str] = []
    # The chain so far, so a cycle is refused with the route that produced it
    # rather than by running out of memory. Mirrors the compiler's own
    # ancestry check at build time.
    visited = [root]

    for depth, mount_id in enumerate(mount_path):
        node = _node(document, mount_id)
        if node is None:
            raise MountResolutionError(
                f"{slug!r} has no node {mount_id!r} "
                f"(reached from {'/'.join([root, *mount_path[:depth]])})"
            )
        if str(node.get("type", "")) not in MOUNT_TYPES:
            raise MountResolutionError(
                f"{mount_id!r} in {slug!r} is not a mount — it is a "
                f"{node.get('type', 'node')!r}, which has no workflow to open"
            )

        data = node.get("data") or {}
        child_slug = str(data.get("workflow") or "").strip()
        if not child_slug:
            raise MountResolutionError(f"the mount {mount_id!r} in {slug!r} references no workflow")
        if child_slug in visited:
            raise MountResolutionError(
                f"{child_slug!r} mounts itself: {' -> '.join([*visited, child_slug])}"
            )

        is_last = depth == len(mount_path) - 1
        overrides = None if (inherited and is_last) else data.get("overrides")
        document, step_warnings = apply_mount_overrides(store.load(child_slug), overrides)
        warnings.extend(f"{mount_id}: {warning}" for warning in step_warnings)
        visited.append(child_slug)
        slug = child_slug

    return MountResolution(slug=slug, mount_path=list(mount_path), document=document, warnings=warnings)


def _node(document: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    nodes: list[dict[str, Any]] = document.get("nodes") or []
    for node in nodes:
        if node.get("id") == node_id:
            return node
    return None


class MountUsage(NamedTuple):
    """Who mounts a package, and who has already narrowed the field being pushed.

    `production-ready` ticket 17, "push to package": a field edited inside a
    mount can be corrected on the instance (the existing override) or on the
    package it comes from. Before that second write lands, the person making
    it has to be told two things — CLAUDE.md's own requirement, restated from
    the ticket: *confirm before writing, and name how many instances change*,
    and *warn about shadowing*, because a mount that already overrides this
    exact field will keep running its own value and the push will look like
    it silently failed.
    """

    #: Every direct mount of the package, anywhere in the workspace.
    #: Named `instance_count`, not `count` — `MountUsage` is a `NamedTuple`,
    #: and `count` is a real `tuple` method; naming a field the same shadows
    #: it and mypy refuses the assignment.
    instance_count: int
    #: The hosting packages whose mount already overrides this exact
    #: `(child_node_id, key)` pair, so the push will not reach them.
    shadowed_hosts: list[str]


def _shadows(overrides: Any, child_node_id: str, key: str) -> bool:
    """Whether one mount's own `overrides` already narrows this field.

    Accepts either spelling the field is stored in — a plain dict (a
    hand-authored or already-migrated document) or the JSON string the
    inspector's textarea saves — the same duality `apply_mount_overrides`
    reads, kept narrow here because this only needs to answer yes/no rather
    than produce a merged document.
    """
    if isinstance(overrides, str):
        if not overrides.strip():
            return False
        try:
            overrides = json.loads(overrides)
        except ValueError:
            return False
    if not isinstance(overrides, dict):
        return False
    fields = overrides.get(child_node_id)
    return isinstance(fields, dict) and key in fields


def find_mount_usages(store: Any, slug: str, child_node_id: str, key: str) -> MountUsage:
    """Every direct mount of `slug`, anywhere under `store`'s root.

    **Direct, not by depth.** A mount object is flat — `{type: ..., data:
    {workflow: slug, overrides: {...}}}` — so "every instance of this
    package" is exactly every node of a mount type whose `data.workflow`
    equals `slug`, in every package on disk, regardless of how deep that
    package itself sits in somebody else's mount chain. There is no such
    thing as a "nested mount of the same package" that this walk would miss:
    nesting is a property of which document *contains* the mount node, not
    of the mount node itself.

    Scans every listable package, including hidden ones — a hidden package
    (the concierge gateway) is a real instance that would silently miss the
    correction if this excluded it the way a customer-facing listing does.
    An unreadable package is skipped: it cannot be scanned and it is
    reported elsewhere as its own defect.
    """
    count = 0
    shadowed_hosts: list[str] = []
    for summary in store.list(include_hidden=True):
        if summary.error:
            continue
        document = store.load(summary.slug)
        for node in document.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            if str(node.get("type") or "") not in MOUNT_TYPES:
                continue
            data = node.get("data") or {}
            if not isinstance(data, dict):
                continue
            if str(data.get("workflow") or "").strip() != slug:
                continue
            count += 1
            if _shadows(data.get("overrides"), child_node_id, key):
                shadowed_hosts.append(summary.slug)
    return MountUsage(instance_count=count, shadowed_hosts=shadowed_hosts)
