"""Which mounted workflow a pause was raised inside.

`organisms-first-class` 64. The ticket asked for the child's state through
`get_state(config, subgraphs=True)`, and that is **refused with a measurement**
rather than left as an unused option: for a mount, `.tasks[0].state` is `None`
at every depth and in every persistence mode. The installed 1.2.10
`langgraph/use-subgraphs.mdx` §"View subgraph state" says why in its own note —
viewing subgraph state requires LangGraph to **statically discover** the
subgraph, and it does not work "when a subgraph is called inside a tool
function or other indirection". A mount is a closure over the child's
`invoke()`, which is that indirection exactly; `compile/composition.py` makes
the identical argument about `xray`, and for the same reason it will not change
until a mount stops being a closure.

What is reachable needs no second graph query at all. A pause propagates to
**every** level, and each level writes its own checkpoint under a namespace
whose segments are the mount nodes it passed through — `mount1:<uuid>` under
per-invocation persistence, a bare `mount1` under per-thread. So the deepest
namespace carrying a pending `__interrupt__` *is* the mount path down to the
document that raised the gate, and the compiler's own record of what it
mounted turns that path into package names.

Two honest limits, both pinned:

- **Stateless writes nothing.** `checkpointer=False` leaves no child
  checkpoint, so a stateless mount has no path to report. It still pauses, on
  the parent's checkpointer — that is a fact about this boundary, not a
  capability this module claims.
- **A path segment the compiler did not record** resolves to an empty
  workflow name rather than to a guess. A mount whose child could not be
  loaded is a box the compiler never opened, and inventing a slug for it would
  be the drift `composition.py` exists to prevent.
"""

from __future__ import annotations

from typing import Any, Mapping

#: LangGraph joins nested checkpoint namespaces with this, and suffixes each
#: segment with an invocation id after a colon (per-thread persistence has no
#: suffix, because there is one namespace per thread rather than per call).
_LEVELS = "|"
_SUFFIX = ":"


def mount_path(namespace: str) -> tuple[str, ...]:
    """The chain of mount node names a checkpoint namespace passed through."""
    if not namespace:
        return ()
    return tuple(segment.split(_SUFFIX, 1)[0] for segment in namespace.split(_LEVELS))


def mount_chain(
    path: tuple[str, ...], mounts: Mapping[str, Any]
) -> list[dict[str, str]]:
    """A mount path resolved against what the compiler recorded it built.

    One entry per level: the graph node the mount sits on, and the slug of the
    package it runs. Descent stops at the first level the record cannot
    explain, because a chain that guesses past a gap is worse than a short one.
    """
    chain: list[dict[str, str]] = []
    current: Mapping[str, Any] = mounts
    for name in path:
        mounted = current.get(name)
        if mounted is None:
            break
        chain.append({"node": name, "workflow": str(getattr(mounted, "slug", "") or "")})
        current = getattr(mounted, "mounts", {}) or {}
    return chain


def paused_mount_chain(
    checkpointer: Any, thread_id: str, mounts: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Where in a composition this thread's pause is waiting, top-down.

    Empty for a pause in the top document, for a stateless mount that stored
    no checkpoint, and for a checkpointer that cannot enumerate — a saver is
    allowed to refuse a listing, and the honest answer from one that cannot say
    is silence rather than a failed read of a pause somebody is waiting on.
    """
    if checkpointer is None or not mounts:
        return []
    config = {"configurable": {"thread_id": thread_id}}
    try:
        tuples = list(checkpointer.list(config))
    except Exception:  # pragma: no cover - saver-specific
        return []
    deepest: tuple[str, ...] = ()
    for tuple_ in tuples:
        if not any(
            channel == "__interrupt__" for _, channel, _ in (tuple_.pending_writes or [])
        ):
            continue
        namespace = str((tuple_.config or {}).get("configurable", {}).get("checkpoint_ns") or "")
        path = mount_path(namespace)
        if len(path) > len(deepest):
            deepest = path
    return mount_chain(deepest, mounts)
