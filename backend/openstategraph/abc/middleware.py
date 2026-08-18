"""Middleware as an ordered, name-keyed slot table.

LangChain middleware is a **list whose order is significant three ways at
once**: ``before_*`` hooks run first-to-last, ``after_*`` hooks run
last-to-first, and ``wrap_*`` hooks nest with the first middleware outermost.
So "append mine" or "priority 40" expresses something that does not exist —
one number cannot describe three orderings. What *can* be expressed safely is
a **named slot**: the base owns the canonical slot order, a contributor names
the slot it fills, and replacement is by name.

This table is the shape ``resolveMiddleware()`` returns everywhere (CLAUDE.md
"Middleware order is a slot table, never a list position"). The compiler
flattens it to a list at the last moment and hands that to
``create_agent(middleware=[...])`` / ``create_deep_agent(middleware=[...])`` —
the *library's* middleware seam. Nothing here wraps, patches, or replaces a
model object: an earlier attempt monkey-patched ``model.invoke`` per node and
stacked wrappers on the shared cached model instance, which is exactly the
class of bug a real seam prevents.

The values are ``langchain.agents.middleware.AgentMiddleware`` instances (or
anything ``create_agent`` accepts). The table is deliberately ignorant of
their types — it orders, it does not inspect.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence


class MiddlewareSlotTable:
    """An ordered mapping of slot name → middleware instance.

    Flattening emits canonical slots first, in the canonical order, then
    unknown slots in the order they were first set — so a plugin that names a
    slot the base does not know about still lands deterministically, at the
    end, where it wraps nothing it was not told about.
    """

    def __init__(self, order: Sequence[str] = ()) -> None:
        self._order = tuple(order)
        self._slots: dict[str, Any] = {}
        #: First-set order for slots outside the canonical list.
        self._extra_order: list[str] = []

    def set(self, name: str, middleware: Any) -> None:
        """Fills (or replaces) one named slot."""
        if name not in self._slots and name not in self._order:
            self._extra_order.append(name)
        self._slots[name] = middleware

    def remove(self, name: str) -> None:
        """Empties a slot. Removing an unfilled slot is a no-op, not an error."""
        self._slots.pop(name, None)
        if name in self._extra_order:
            self._extra_order.remove(name)

    def get(self, name: str) -> Any | None:
        """What fills a slot, or ``None`` if nothing does.

        The read half of ``set``. It exists because ``merge`` needs to copy a
        table without reaching into its ``_slots`` — see below.
        """
        return self._slots.get(name)

    def merge(self, contributions: "dict[str, Any] | MiddlewareSlotTable | None") -> None:
        """Applies a batch of named contributions, replacement by slot name.

        A table source is read through ``names()``/``get()`` — its **own**
        flatten order — rather than through its ``_slots`` dict, which is
        *set* order (ticket 46, item 4). The two differ as soon as an extra
        slot is filled before a canonical one, and ordering contributions is
        the single guarantee this class exists to give: a merge that quietly
        reordered the source's extras would be the class failing at its one
        job, through the one path nobody was watching because every live
        caller happens to pass a plain dict.
        """
        if not contributions:
            return
        items: Iterable[tuple[str, Any]]
        if isinstance(contributions, MiddlewareSlotTable):
            items = [(name, contributions.get(name)) for name in contributions.names()]
        else:
            items = contributions.items()
        for name, middleware in items:
            self.set(name, middleware)

    def flatten(self) -> list[Any]:
        """The list ``create_agent`` receives. The only place order is decided."""
        canonical = [self._slots[name] for name in self._order if name in self._slots]
        extras = [self._slots[name] for name in self._extra_order if name in self._slots]
        return canonical + extras

    def names(self) -> list[str]:
        """Filled slots, in flatten order — what an inspector would display."""
        return [name for name in self._order if name in self._slots] + [
            name for name in self._extra_order if name in self._slots
        ]


__all__ = ["MiddlewareSlotTable"]
