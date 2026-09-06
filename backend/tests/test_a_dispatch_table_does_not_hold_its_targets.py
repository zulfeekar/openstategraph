"""The second clause of the god-class rule, which had no instrument.

`CLAUDE.md` states the rule with a number and two clauses:

    Ceiling: ~10 public members, one reason to change.

`test_public_surface_ceiling.py` measures the first clause and goes red on it.
Nothing measured the second, and `rules-that-can-fail/04` is the record of what
that cost: `NodeRuntime` held **twenty node families as private methods across
5,331 lines** while presenting **nine public members**, so every session that
added a family ran the census, saw green, and added one more reason for the
class to change. No commit looked wrong. The clause that would have said so did
not exist.

`test_module_size_ceiling.py` (`rules-that-can-fail/03`) landed a module-length
measure afterwards, and the first question this file had to answer was whether
that already covers this. **It does not, and the number that settles it is 465.**
`src/view/topbar/TopBar.tsx` is the ticket's other named instance — 777 physical
lines of hardcoded JSX in a codebase carrying twelve `Registry<T>` sites — and
it measures 465 code lines, comfortably under 03's ceiling of 500. Length and
reasons-to-change are correlated, not the same thing, and a file can hold
several of the second while staying under a ceiling on the first.

## What this counts, and the three measures it is not

**Distinct dispatch targets a module defines and then registers into its own
registry.** Concretely: a `registry.register(key, target)` call whose `target`
resolves to a `def` or `class` in the same module.

That is narrow on purpose, and the narrowness was priced rather than assumed.
The ticket's own warning is the governing one — *a proxy that produces false
failures will be suppressed, and then it measures nothing* — so each broader
candidate was run against this package before being rejected:

- **Count of private methods.** A class with twenty small helpers doing one job
  is a good class. This measure would rank it beside the one this file was
  written for.
- **Every dict literal mapping three or more constants to local callables.**
  Run over `openstategraph/`, this names three modules and all three are
  correct designs: `evaluation/scoring.py` (ten metric functions in one table),
  `abc/tool_findings.py` (six harness formatters) and `compile/reducers.py`
  (four named reducers — which `CLAUDE.md` requires to be *"a named enum, not
  arbitrary functions"*, so a test asking for them to be scattered would be
  asking for a rule violation). Three false failures against one true one is
  the shape that gets a blanket suppression.
- **Fan-in, or import count.** Both measure how popular a module is, which is
  not what "one reason to change" means and which a well-factored kernel
  maximises on purpose.

## Why zero, and why there is no distribution to cut from

03 chose 500 from a distribution because *every* module has some length, so a
ceiling had to decide which ones must be argued for. This measure has no such
problem: a registry with none of its implementations beside it is the normal
state of this repository, and sixteen of the seventeen modules that register
anything are already at zero. The honest threshold is the one the code already
meets, so any exception is one line of `RECORDED` and a paragraph — the same
social gate the class censuses and the module census rely on.

Zero is also what `CLAUDE.md`'s **O** already says, which is the argument for
this file being a test at all rather than a second number:

    extend by **registering**, never by editing the engine.

Twenty families behind one `builder_for` *is* that pattern with every
implementation left in the engine. `compile/nodes/__init__.py` says so in its
own words, having been the split that fixed it.

## The TypeScript side does not get a mirror, and that is a recorded gap

Not an oversight — 03 and both class censuses run on both sides, so the absence
needs its reason stated where the canvas-features gap in `CLAUDE.md` states
its own. The TypeScript registration idiom takes a **single object argument**
(`register(new AnthropicProvider())`, `register({ id, body })`), so there is no
key-and-target pair to compare, and the object literal that wraps an imported
value is textually identical to the one that inlines an implementation. A
detector that cannot tell those apart is the false-failure machine the section
above rejects three other candidates for being.

And the ticket's TypeScript instance is the harder half regardless: `TopBar.tsx`
is not a dispatch table with its bodies inlined, it is the **absence** of a
dispatch table. An absence has no signature — a hardcoded row of five buttons
that should be a registry and a hardcoded row of five buttons that is genuinely
five buttons are the same text. Nothing here measures that, `CLAUDE.md` now
says nothing measures it, and the alternative — pretending otherwise — is what
this map exists to end.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from functools import lru_cache

import pytest

import openstategraph

#: A module may define none of the implementations it registers into its own
#: registry. See this file's docstring for why zero is the threshold rather
#: than a number picked off a distribution.
CEILING = 0

PACKAGE_ROOT = pathlib.Path(openstategraph.__path__[0])


def _registered_name(target: ast.expr) -> str | None:
    """The name a registration's second argument points at, if it points at one.

    `self._agent`, `cls._agent`, a bare `_agent`, and `SqliteRunSink(...)` all
    name something this module might define. Anything else — an attribute of an
    imported module, a lambda, a subscript — names nothing local by
    construction and is not a candidate.
    """
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        return target.attr if target.value.id in {"self", "cls"} else None
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Call):
        return _registered_name(target.func)
    return None


def _defined_here(tree: ast.Module) -> set[str]:
    """Names this module defines, including the alias a binding gives one.

    `def`s and `class`es at any depth, plus assignments whose right-hand side is
    one of them. The second clause is what stops `_agent = _agent_impl` in a
    class body from laundering a locally-defined builder past this census —
    while leaving `_agent = agent._agent`, the binding `compile/nodes/` actually
    uses, correctly uncounted: that one names a function defined elsewhere.
    """
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            if node.value.id in defined:
                defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return defined


def dispatch_targets_defined_here(source: str) -> set[str]:
    """The distinct implementations a module registers into a registry and owns."""
    tree = ast.parse(source)
    defined = _defined_here(tree)
    owned: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "register":
            continue
        if len(node.args) < 2:
            continue
        name = _registered_name(node.args[1])
        if name is not None and name in defined:
            owned.add(name)
    return owned


@lru_cache(maxsize=1)
def modules_holding_their_own_targets() -> dict[str, tuple[str, ...]]:
    """Derived, never hand-listed — the property that makes a census a census."""
    census: dict[str, tuple[str, ...]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        owned = dispatch_targets_defined_here(path.read_text(encoding="utf-8"))
        if len(owned) > CEILING:
            census[path.relative_to(PACKAGE_ROOT).as_posix()] = tuple(sorted(owned))
    return census


@dataclasses.dataclass(frozen=True)
class Recorded:
    """Exact, in both directions. The number is a tripwire, not an allowance."""

    targets: tuple[str, ...]
    reason: str


RUN_SINKS = """The registry and its one implementation in the same module, and the
argument is that there is one — `default_run_sink_registry`'s own docstring is
*"the shipped registry: one sink, and it writes to this machine"*, and the
module's docstring records that no exporter which could reach a network is
registered and disabled, because the design is **absence rather than a flag**.

So this is not a family album behind a selector. It is a registry that exists so
a stranger can add the second sink from outside without editing anything here —
which the module already demonstrates in a comment, in one line:
`run_sink_registry().register("acme", AcmeOtelSink())`. The extension point is
real and used; what sits beside it is the default, the way a `Base*` sits beside
the interface it implements.

The seam was considered and does not pay: moving `SqliteRunSink` to
`run_sinks/sqlite.py` buys a smaller file and a package where there was a
module, and the class shares this module's `RunSink` protocol, its row shapes
and its store-path resolution. `run_sinks.py` is already in
`test_module_size_ceiling.py`'s table at 600 code lines, so its length is
measured elsewhere and by a measure that will notice if the sink grows.

The number is exact for the reason every number in these censuses is: a
**second** locally-defined sink is the moment this stops being "the default
beside its registry" and starts being the shape this file was written for, and
it should land as a red test rather than as a diff nobody reads twice."""


RECORDED: dict[str, Recorded] = {
    "run_sinks.py": Recorded(("SqliteRunSink",), RUN_SINKS),
}


def test_no_module_holds_the_implementations_it_dispatches_to() -> None:
    """The instrument the god-class rule's second clause did not have."""
    census = modules_holding_their_own_targets()

    unrecorded = sorted(set(census) - set(RECORDED))
    departed = sorted(set(RECORDED) - set(census))

    assert not unrecorded, (
        f"registers implementations it defines itself: "
        f"{ {name: list(census[name]) for name in unrecorded} }.\n"
        "A registry whose entries are defined beside it is CLAUDE.md's O with "
        "the bodies left in the engine, and each entry is a separate reason for "
        "this module to change — the clause the public-member census cannot "
        "see, which is how NodeRuntime reached twenty families at nine public "
        "members.\n"
        "  - It is a family: give it its own module beside the registry and "
        "bind it here, the way `compile/nodes/agent.py` and its eleven siblings "
        "came out of `compile/node_runtime.py`. The registration line stays; "
        "only the body moves.\n"
        "  - It is the shipped default beside its own extension point, not a "
        "family: add it to RECORDED with the argument, naming the seam you "
        "considered and why it does not pay.\n"
        "Raising CEILING is neither of those. It is the move that made this "
        "clause unenforced in the first place, and this file exists to make "
        "somebody argue for it in public."
    )
    assert not departed, (
        f"recorded but no longer holding its own targets: {departed}. Good news "
        "— delete the entry, and its reasoning with it."
    )


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_each_recorded_exception_is_exact(name: str) -> None:
    """A ratchet, not an allowance: a second target is a new decision."""
    census = modules_holding_their_own_targets()

    assert census[name] == RECORDED[name].targets, (
        f"{name} registers {list(census[name])}, recorded as "
        f"{list(RECORDED[name].targets)}.\n"
        "Exact, not an upper bound: an exception with room to spare is how a "
        "ceiling becomes a floor, and one-more-beside-the-existing-one is "
        "precisely how a module acquires twenty reasons to change without any "
        "single commit looking wrong.\n"
        "If a target arrived, the argument recorded here has to still be true "
        "of it. If one left, re-record and say what came out."
    )


@pytest.mark.parametrize("reason", sorted({entry.reason for entry in RECORDED.values()}))
def test_every_exception_carries_reasoning(reason: str) -> None:
    # The same threshold and the same crude proxy as both class censuses and the
    # module census: length is weak evidence that somebody thought, and weak
    # evidence beats none.
    assert len(reason.strip()) > 400


class TestTheMeasureMeasuresWhatItClaims:
    """A measure nobody checks is as much a preference as a clause nobody measures."""

    def test_a_builder_defined_and_registered_here_is_counted(self) -> None:
        source = (
            "class Runtime:\n"
            "    def _agent(self, node):\n"
            "        return node\n"
            "\n"
            "    def _register(self):\n"
            "        registry.register('agent.llm', self._agent)\n"
        )
        assert dispatch_targets_defined_here(source) == {"_agent"}

    def test_a_builder_bound_from_another_module_is_not(self) -> None:
        # The shape `compile/node_runtime.py` has today, and the whole point of
        # the split: the registration line is unchanged and the body is gone.
        source = (
            "from . import agent\n"
            "\n"
            "class Runtime:\n"
            "    _agent = agent._agent\n"
            "\n"
            "    def _register(self):\n"
            "        registry.register('agent.llm', self._agent)\n"
        )
        assert dispatch_targets_defined_here(source) == set()

    def test_an_alias_does_not_launder_a_local_definition(self) -> None:
        source = (
            "def _agent_impl(self, node):\n"
            "    return node\n"
            "\n"
            "class Runtime:\n"
            "    _agent = _agent_impl\n"
            "\n"
            "    def _register(self):\n"
            "        registry.register('agent.llm', self._agent)\n"
        )
        assert dispatch_targets_defined_here(source) == {"_agent"}

    def test_a_locally_constructed_instance_is_counted(self) -> None:
        # `registry.register("sqlite", SqliteRunSink(path))` — the one recorded
        # exception's shape, which a name-only reader would miss entirely.
        source = (
            "class Sink:\n"
            "    pass\n"
            "\n"
            "def build():\n"
            "    registry.register('sqlite', Sink(path))\n"
        )
        assert dispatch_targets_defined_here(source) == {"Sink"}

    def test_distinct_targets_are_counted_once_each(self) -> None:
        # `_static_text` is registered for every type in `STATIC_TEXT_NODE_TYPES`.
        # Ten registrations of one builder are one reason to change, not ten.
        source = (
            "def _static_text(self, node):\n"
            "    return node\n"
            "\n"
            "def build():\n"
            "    for kind in kinds:\n"
            "        registry.register(kind, _static_text)\n"
            "    registry.register('skill.file', _static_text)\n"
        )
        assert dispatch_targets_defined_here(source) == {"_static_text"}

    def test_the_shape_this_file_was_written_for_is_seen(self) -> None:
        """Not a synthetic mutation — `node_runtime.py` as it actually was.

        Sixteen distinct builders defined and registered in one module, against
        nine public members and a green class census. Reduced here to the two
        lines per family that carry the shape, because the point is that the
        measure sees it, not that the file was long — `test_module_size_ceiling`
        already measures the length, and 03's own ceiling would not have seen
        `TopBar.tsx` at 465 code lines doing something adjacent.
        """
        families = (
            "_agent",
            "_router",
            "_grader",
            "_guardrail",
            "_guard_check",
            "_human_approval",
            "_input",
            "_static_text",
            "_output",
            "_passthrough",
            "_memory_segment",
            "_orchestrator",
            "_worker",
            "_subgraph",
            "_resolve_vocabulary",
            "_format_report_function",
        )
        body = "".join(f"    def {name}(self, node):\n        return node\n" for name in families)
        registrations = "".join(f"        registry.register('{name}', self.{name})\n" for name in families)
        source = f"class NodeRuntime:\n{body}\n    def _register_node_types(self):\n{registrations}"

        assert dispatch_targets_defined_here(source) == set(families)
