"""How each node family calls the package function its document names.

`osg-agent-experience/59`. Four node families name a package function by its
short name, and each one decides for itself how to call it. `guard.check`
decides by **inspecting the signature** — one parameter and it gets the
candidate, two and it also gets the run's own record
(`osg-agent-experience/50`) — which means a function's parameter list is a
protocol, and nothing said so anywhere a developer meets it. A variadic
wrapper reads as accepting two, gets two, and forwards two to a one-argument
implementation: `TypeError`, live, reported as a review's last reason after
the model had been paid.

**One table, two consumers.** `validation.uncallable_functions` reads it to
refuse a signature before a run costs anything, and
`test_a_function_is_refused_before_it_is_called.py` reads it to assert that
each family's field hint states the shapes it calls. A fifth family therefore
cannot arrive with a convention nobody wrote down — which is the defect this
module is named after, one level up.

The `function.<name>` node itself is deliberately **not** here: its contract is
`fn(text) -> str` with no inspection and no choice, its card has no field to
carry a hint, and a node type minted from Python has no static schema for the
second consumer to read. It is checked by the same code through
`FUNCTION_NODE_SHAPES` below, and it is not a row in a table about *fields*.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CallConvention:
    """One family, the field that names its function, and how it calls it."""

    node_type: str
    #: The `data` key holding the function's short name.
    field: str
    #: Each shape, as the number of positional arguments the node passes, with
    #: the spelling a hint has to use for it. In the order the node prefers.
    shapes: tuple[tuple[int, str], ...]

    @property
    def spellings(self) -> tuple[str, ...]:
        return tuple(spelling for _, spelling in self.shapes)

    @property
    def widest(self) -> int:
        return max(count for count, _ in self.shapes)

    @property
    def chooses_by_inspection(self) -> bool:
        """Whether this family reads the signature to decide which shape to use.

        Only where there is more than one shape. It is the whole reason a
        variadic function is a finding here and ordinary everywhere else: the
        platform reads `*args` as room for the second argument and takes it.
        """
        return len(self.shapes) > 1


#: The four families whose card carries a field naming a package function.
CALL_CONVENTIONS: tuple[CallConvention, ...] = (
    CallConvention("guard.check", "check", ((1, "fn(text)"), (2, "fn(text, summary)"))),
    CallConvention("route.check", "check", ((1, "fn(text)"),)),
    CallConvention("resolve.vocabulary", "source", ((1, "fn(phrase)"),)),
    CallConvention("resolve.source", "catalogue", ((1, "fn(question)"),)),
)

#: A `function.<name>` node's own contract — one argument, never a choice.
FUNCTION_NODE_SHAPES: tuple[tuple[int, str], ...] = ((1, "fn(text)"),)


def _accepts(fn: Any, count: int) -> bool:
    """Whether `fn` can be called with `count` positional arguments.

    Asked of the signature by binding placeholders rather than by counting
    parameters: defaults, keyword-only parameters and `*args` all change the
    answer, and `Signature.bind` is the one thing that already knows how.
    Tolerant of a callable that cannot be inspected at all — a C builtin, an
    exotic partial — which is taken as callable, because refusing what we
    cannot read would fail a run that works.
    """
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    try:
        signature.bind(*range(count))
    except TypeError:
        return False
    return True


def _is_variadic(fn: Any) -> bool:
    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in parameters)


def signature_finding(
    fn: Any,
    shapes: tuple[tuple[int, str], ...],
    *,
    subject: str,
    name: str,
    chooses_by_inspection: bool = False,
) -> str | None:
    """The sentence to report about `fn`, or `None` when it is callable.

    Two findings, and they are different failures. A signature **no** shape
    can satisfy is a step that cannot run at all. A **variadic** signature
    where the family chooses by inspection is a step that runs and may raise
    inside the function it delegates to — the platform reads `*args` as room
    for the second argument, so it passes two, and only the code behind the
    wrapper knows whether that is true.
    """
    spellings = " or ".join(spelling for _, spelling in shapes)
    written = _written(fn, name)
    if not any(_accepts(fn, count) for count, _ in shapes):
        return (
            f'{subject} names function "{name}", written {written} — no call this node '
            f"type makes can reach it. It is called as {spellings}."
        )
    if chooses_by_inspection and _is_variadic(fn):
        widest = max(count for count, _ in shapes)
        return (
            f'{subject} names function "{name}", written {written}. This node type reads '
            f"the signature to decide how to call it, and a variadic one reads as room "
            f"for every argument — so it is called with {_words(widest)} ({spellings.split(' or ')[-1]}), "
            "and an implementation behind it that takes fewer raises TypeError mid-run. "
            f"Name the parameters you accept: {spellings.split(' or ')[0]}."
        )
    return None


def _words(count: int) -> str:
    return {1: "one argument", 2: "two arguments"}.get(count, f"{count} arguments")


def _written(fn: Any, name: str) -> str:
    try:
        return f"def {name}{inspect.signature(fn)}"
    except (TypeError, ValueError):  # pragma: no cover - uninspectable callable
        return f"def {name}(...)"
