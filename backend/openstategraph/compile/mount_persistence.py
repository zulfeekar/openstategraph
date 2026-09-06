"""How long a mounted child's own state lives — the mount's one lifecycle field.

`organisms-first-class` 30. LangGraph makes a child's persistence a
**tri-state** on `.compile(checkpointer=…)`, and the installed 1.2.10 docs
(`langgraph/use-subgraphs.mdx`, "Subgraph persistence") spell out all three:

| value | meaning |
| --- | --- |
| `None` (default) | per-invocation — each call starts fresh and inherits the parent's checkpointer, so `interrupt()` and durable execution still work *within* one call |
| `True` | per-thread — the child's own state accumulates across calls on the same thread |
| `False` | stateless — no checkpoints, no durable execution (and, the doc says, no interrupts — see below, because at *this* boundary that half is not what happens) |

Until this ticket `NodeRuntime._subgraph` passed **no** `checkpointer` argument
at all, so every mount in this product was per-invocation and the per-thread
case was inexpressible. What approximated it was the `messages` copy across the
boundary — the parent's dialogue handed to the child on every invoke, which was
the right fix for the Architect re-asking its interview question and is *not*
the child's own accumulated graph state.

**Two things are decided here rather than at the call site**, because they are
one decision and were measured together:

- **which checkpointer argument the child compiles with**, and
- **whether the parent's dialogue is copied in**.

The second is not a taste. Measured on a real parent and child over two calls
on one thread: under `checkpointer=True` the child's own message history is
already in its checkpoint, so copying the parent's in as well left the child
holding five messages where four had been said. A per-thread child owns its
history; a per-invocation or stateless child has none of its own and the copy
is the only continuity it can have.

**Why the mount and not the package.** `CLAUDE.md` fixes *package* as the
reusable definition and *instance* as one mount of it carrying its own
`data.overrides`, and whether a child should remember depends on how it is
used, not on what it is — the same analyst package is a one-off lookup in one
document and a running conversation in another. So this is a field on the mount
node, per instance.

**It is a field, not an override.** `docs/decisions/mount-overrides.md` says an
override *narrows* a mount; a persistence mode redefines the child's lifecycle,
so it does not go through the override editor.

**And it is not the obvious upgrade.** The doc warns that stateful subgraphs
**conflict under parallel calls to the same subgraph** — they write to one
checkpoint namespace — so per-thread is the exception a developer reaches for
deliberately. `stateless` costs more still, though **not** what the doc's
sentence predicts: a mount is a *closure*, not a LangGraph subgraph node, so
the `interrupt()` a stateless child raises travels up and is held by the
**parent's** checkpointer. It pauses, it resumes, and it answers — measured at
one level and at two (`organisms-first-class` 64, then 65).

What it cannot do is remember. Resuming re-enters the mount node in every mode,
and only this one has no child checkpoint to pick up from, so the child runs
again **from its first step**: counted on the child's own pre-gate node, once
under per-invocation and per-thread and **twice** under stateless. A step that
called a tool or wrote to the world before the gate does it a second time, on
the approval path. That is reported at compile time rather than refused —
`Finding.STATELESS_MOUNT_REDOES`, recorded by `NodeRuntime._subgraph` for a
stateless mount over a child that holds a gate at any depth — and said again on
the mount's own field in the editor.

An absent or unrecognised value is `per-invocation`, which is byte-identical to
every document saved before this module existed. Tolerant in reading, strict in
trusting: an invented mode is resolved to the default rather than acted on.
"""

from __future__ import annotations

#: Fresh each call, inheriting the parent's checkpointer. The default, and what
#: every mount did before this module.
PER_INVOCATION = "per-invocation"
#: The child's own state accumulates across calls on the same thread.
PER_THREAD = "per-thread"
#: No checkpoints at all. It still pauses through the parent's checkpointer;
#: what it loses is the ability to resume where it stopped (see the module
#: docstring — the doc's "no interrupts" is not what happens at this boundary).
STATELESS = "stateless"

#: The whole of the tri-state, in the order the doc's own table lists it. The
#: TypeScript field's options are pinned against this set.
MOUNT_PERSISTENCE_MODES = (PER_INVOCATION, PER_THREAD, STATELESS)

_CHECKPOINTER: dict[str, bool | None] = {
    PER_INVOCATION: None,
    PER_THREAD: True,
    STATELESS: False,
}


def mount_persistence(value: object) -> str:
    """The mode a mount's `data.persistence` names, resolved against the set."""
    text = value.strip() if isinstance(value, str) else ""
    return text if text in _CHECKPOINTER else PER_INVOCATION


def mount_checkpointer(mode: str) -> bool | None:
    """What `WorkflowCompiler.build` should be given for that mode."""
    return _CHECKPOINTER[mount_persistence(mode)]


def carries_the_parents_dialogue(mode: str) -> bool:
    """Whether the parent's `messages` are copied into this child's invoke.

    False for `per-thread` alone: that child keeps its own history, and copying
    the parent's on top of it says every turn twice.
    """
    return mount_persistence(mode) != PER_THREAD


__all__ = [
    "MOUNT_PERSISTENCE_MODES",
    "PER_INVOCATION",
    "PER_THREAD",
    "STATELESS",
    "carries_the_parents_dialogue",
    "mount_checkpointer",
    "mount_persistence",
]
