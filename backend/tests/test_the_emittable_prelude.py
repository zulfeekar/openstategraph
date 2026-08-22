"""Which runtime modules an emitter may copy into someone else's repo verbatim.

`export-and-eject/02` asked for a new `emit/prelude/_runtime.py` holding the
"dependency-free heart of the runtime". Measured on 2026-08-22, that file would
have been a **fourth** home for code three carve-outs had just placed by
bounded context (`compile/reducers.py`, `compile/state.py`,
`compile/context.py`, `messages.py`), so it was not built. What the emitter
actually needs is not a directory — it is a *guarantee*, and this is the
guarantee:

**A module on the roster below imports nothing from `openstategraph`, at any
depth, so `inspect.getsource` on it produces text that compiles and runs
outside this package.** One copy, tested once, emitted verbatim — which is the
ticket's real argument, and the reason a triple-quoted string constant in the
emitter is forbidden: that would be a second implementation of code whose two
copies diverge silently, in someone else's repository.

**"At any depth" is stricter than the ticket asked for, and deliberately.** The
ticket said the prelude must not import from `openstategraph`; a lazy
`from openstategraph...` inside a function body satisfies that reading of a
module-level scan and still breaks the emitted file at call time, because
`getsource` carries the whole body. `reducers.reducer_for` shows the shape that
*is* allowed — a deferred `langgraph` import, third-party and therefore present
wherever the emitted graph runs.

The second half is the roster of the eleven names `export-and-eject/02` listed.
It is pinned as data so that when step 3 of the `node_runtime.py` split moves
one of them, this test goes red and the mover records the new home — rather
than the emitter discovering, later and elsewhere, that a name it planned to
inline now sits behind an `openstategraph` import.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "openstategraph"

#: The modules an emitter may inline verbatim today. Adding one is a promise
#: that it stays free of this package forever; removing one is a promise the
#: emitter no longer needs it.
PRELUDE = (
    "compile/reducers.py",
    "messages.py",
)

#: Every name `export-and-eject/02` asked for, mapped to **every** module-level
#: site that binds it, authoritative one first, and whether that authoritative
#: module is on the roster above.
#:
#: The extra sites are the part worth writing down. `compile/state.py` binds
#: `RESET` and the three reducers by *assignment* — a deliberate re-export, so
#: that the many readers importing them from the state module kept working when
#: `reviews-2026-08-14` 07 moved the implementations out. `api/threads.py` binds
#: a `_text` that is a different function entirely (one argument, not three).
#: An emitter reading a name off this list and copying the first file it found
#: would emit an alias or a homonym instead of the code; recording both makes
#: that a fact it can check rather than one it can discover in production.
HOMES: dict[str, tuple[tuple[str, ...], bool]] = {
    "RESET": (("compile/reducers.py", "compile/state.py"), True),
    "merge_decisions": (("compile/reducers.py", "compile/state.py"), True),
    "keep_max": (("compile/reducers.py", "compile/state.py"), True),
    "keep_latest_nonempty": (("compile/reducers.py", "compile/state.py"), True),
    "content_text": (("messages.py",), True),
    "RunState": (("compile/state.py",), False),
    "_thread_question": (("compile/state.py",), False),
    "_upstream_text": (("compile/state.py",), False),
    "_text": (("compile/context.py", "api/threads.py"), False),
    "_final_text": (("compile/node_runtime.py",), False),
    "Classification": (("abc/router.py",), False),
}


def _imported_modules(path: Path) -> set[str]:
    """Every module this file imports, at module level or inside a body.

    Depth is the point: `inspect.getsource` emits the whole file, so a
    function-local import travels with it and fails in the emitted copy exactly
    as a top-level one would.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A relative import resolves inside this package by definition.
            found.add("openstategraph" if node.level else (node.module or ""))
    return found


class TestThePreludeIsFreeOfThisPackage:
    @pytest.mark.parametrize("relative", PRELUDE)
    def test_it_imports_nothing_from_openstategraph(self, relative: str) -> None:
        offenders = sorted(
            name
            for name in _imported_modules(PACKAGE / relative)
            if name.split(".")[0] == "openstategraph"
        )
        assert not offenders, (
            f"{relative} is on the emitter's prelude roster, so it is copied "
            f"verbatim into repositories that do not have this package "
            f"installed — but it imports {offenders}. Either lift the "
            f"dependency or take the module off PRELUDE."
        )

    @pytest.mark.parametrize("relative", PRELUDE)
    def test_its_source_can_be_read_and_compiled(self, relative: str) -> None:
        module = __import__(
            "openstategraph." + relative[: -len(".py")].replace("/", "."),
            fromlist=["*"],
        )
        source = inspect.getsource(module)
        assert source.strip(), f"{relative} produced no source"
        compile(source, f"<emitted {relative}>", "exec")


class TestTheRosterIsWhereTheCodeIs:
    """The eleven names the ticket listed, checked against the filesystem.

    Not a restatement of `HOMES`: each name is looked for in *every* module of
    the package, so a name that moves is caught by where it is found rather
    than by where it was expected to be missing.
    """

    @pytest.mark.parametrize("name", sorted(HOMES))
    def test_the_name_is_bound_exactly_where_recorded(self, name: str) -> None:
        sites, _ = HOMES[name]
        binding = sorted(
            str(path.relative_to(PACKAGE)).replace("\\", "/")
            for path in PACKAGE.rglob("*.py")
            if _binds(path, name)
        )
        assert binding == sorted(sites), (
            f"{name} was recorded as bound in {sorted(sites)} and is bound in "
            f"{binding}. If it moved, update HOMES — and check whether its new "
            f"module is on PRELUDE, because the emitter has to carry this name "
            f"and cannot carry an openstategraph import with it. If a *new* "
            f"site appeared, say in HOMES whether it is a re-export, a homonym "
            f"or a second implementation; only the third is a defect, and it "
            f"is the one this ticket exists to prevent."
        )

    @pytest.mark.parametrize("name", sorted(HOMES))
    def test_emittability_matches_its_modules_imports(self, name: str) -> None:
        (relative, *_), emittable = HOMES[name]
        free = not any(
            imported.split(".")[0] == "openstategraph"
            for imported in _imported_modules(PACKAGE / relative)
        )
        assert free == emittable, (
            f"{name} lives in {relative}, which is "
            f"{'free of' if free else 'bound to'} openstategraph — but HOMES "
            f"records it as {'emittable' if emittable else 'not emittable'}. "
            f"A module that just became free is a candidate for PRELUDE."
        )

    def test_every_prelude_module_is_reachable_from_a_recorded_name(self) -> None:
        assert {sites[0] for sites, ok in HOMES.values() if ok} == set(PRELUDE)


def _binds(path: Path, name: str) -> bool:
    """Whether this file binds `name` at module level — def, class or assign.

    Module level only, and that is why `BaseRouter.normalise` is absent from
    `HOMES` while `Classification` is present: `normalise` reads `self.branches`,
    `self.fallback` and `self._match_mode`, so it is a method and not a thing an
    emitter could ever carry on its own. A `normalise` on a class and a
    `normalise` function are different things.
    """
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not our files
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        elif isinstance(node, ast.Assign):
            if any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            ):
                return True
    return False
