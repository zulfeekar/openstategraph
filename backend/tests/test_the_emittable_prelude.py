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
    "compile/fields.py",
    "compile/reducers.py",
    "compile/state.py",
    "messages.py",
    "skills.py",
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
    "RunState": (("compile/state.py",), True),
    "_thread_question": (("compile/state.py",), True),
    "_upstream_text": (("compile/state.py",), True),
    "_text": (("compile/fields.py", "api/threads.py"), True),
    "_final_text": (("compile/node_runtime.py",), False),
    "Classification": (("abc/router.py",), False),
}


def _imported_modules(path: Path) -> set[str]:
    """Every module this file imports, at module level or inside a body.

    Depth is the point: `inspect.getsource` emits the whole file, so a
    function-local import travels with it and fails in the emitted copy exactly
    as a top-level one would.

    A relative import is resolved against this file's own position, so the
    result is a dotted `openstategraph.…` name that `_relative_path` can turn
    back into a roster entry. Recording it as the bare package name — which is
    what this did until `export-and-eject/16` — is fine for "does it import
    anything from us", and useless for "does it import anything *off the
    roster*", which is the question the closure rule asks.
    """
    here = path.relative_to(PACKAGE).parent.parts
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ("openstategraph", *here[: len(here) - (node.level - 1)])
                found.add(".".join((*base, node.module) if node.module else base))
            else:
                found.add(node.module or "")
    return found


def _relative_path(dotted: str) -> str:
    """`openstategraph.compile.state` -> `compile/state.py`, roster spelling."""
    return "/".join(dotted.split(".")[1:]) + ".py"


def _package_imports(relative: str) -> set[str]:
    """The `openstategraph` modules `relative` imports, in roster spelling."""
    return {
        _relative_path(name)
        for name in _imported_modules(PACKAGE / relative)
        if name.split(".")[0] == "openstategraph"
    }


class TestThePreludeIsFreeOfThisPackage:
    @pytest.mark.parametrize("relative", PRELUDE)
    def test_it_imports_nothing_from_off_the_roster(self, relative: str) -> None:
        """The roster is **closed under its own imports**, and that is the rule.

        `export-and-eject/02` wrote the strict form — zero `openstategraph`
        imports at any depth — because both of its two modules happened to
        have zero. `compile/state.py` cannot: `RunState`'s annotations *are*
        `reducer_for(...)` calls, so the reducers arrive by import or the
        schema does not exist. The strict form would have made the state
        schema permanently un-emittable to protect a property nobody needs.

        What the emitter actually needs is that the **set** it copies is
        self-contained, which is the same promise 02's commit already made in
        prose when it said tier one emits two files rather than one. So: an
        `openstategraph` import is allowed exactly when it names another
        roster module, which travels in the same emission and keeps its own
        import working. Anything else is still fatal at call time.
        """
        offenders = sorted(_package_imports(relative) - set(PRELUDE))
        assert not offenders, (
            f"{relative} is on the emitter's prelude roster, so it is copied "
            f"into repositories that do not have this package installed — but "
            f"it imports {offenders}, which the emission does not carry. "
            f"Either lift the dependency, put the module it needs on PRELUDE "
            f"too, or take {relative} off PRELUDE."
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
        free = not (_package_imports(relative) - set(PRELUDE))
        assert free == emittable, (
            f"{name} lives in {relative}, which imports "
            f"{sorted(_package_imports(relative) - set(PRELUDE)) or 'nothing'} "
            f"from off the roster — but HOMES records it as "
            f"{'emittable' if emittable else 'not emittable'}. A module whose "
            f"off-roster imports just went to zero is a candidate for PRELUDE."
        )

    def test_every_emittable_name_lives_on_the_roster(self) -> None:
        assert {sites[0] for sites, ok in HOMES.values() if ok} <= set(PRELUDE)

    def test_every_roster_module_is_a_home_or_a_dependency_of_one(self) -> None:
        """No module joins the roster for its own sake.

        Either a name the emitter carries lives in it, or a module holding
        such a name imports it — `skills.py` is the second kind, arriving
        because `_upstream_text`'s neighbour `_wired_skill` calls `skill_text`.
        A module that is neither is a module the emitter would copy and never
        read.
        """
        homes = {sites[0] for sites, ok in HOMES.values() if ok}
        needed = set(homes)
        for relative in homes:
            needed |= _package_imports(relative)
        assert set(PRELUDE) == needed


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


class TestTheRosterActuallySurvivesBeingEmitted:
    """The end the two property tests above are a proxy for.

    Closure over imports is an *argument* that the emitted set stands up on
    its own. This runs it: every roster module is written out by
    `inspect.getsource` into a bare tree, and a subprocess that cannot see
    this package at all imports the names `export-and-eject/16` set out to
    make carryable. A property test that agrees with itself is the failure
    mode `skills/ticket-loop` names; this one cannot.
    """

    def test_the_emitted_set_imports_with_this_package_absent(
        self, tmp_path: Path
    ) -> None:
        import subprocess
        import sys

        for relative in PRELUDE:
            target = tmp_path / "openstategraph" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            (target.parent / "__init__.py").write_text("")
            module = __import__(
                "openstategraph." + relative[: -len(".py")].replace("/", "."),
                fromlist=["*"],
            )
            target.write_text(inspect.getsource(module))
        (tmp_path / "openstategraph" / "__init__.py").write_text("")

        program = (
            "import sys; sys.path.insert(0, %r)\n"
            "from openstategraph.compile.state import ("
            "RunState, NO_MODEL_MARKER, _thread_question, _upstream_text)\n"
            "from openstategraph.compile.fields import _text\n"
            "from openstategraph.messages import content_text\n"
            "print(len(RunState.__annotations__), _text({'k': 'v'}, 'k'),"
            " _thread_question({}))\n" % str(tmp_path)
        )
        # cwd is the filesystem root and the real package is not installed
        # there, so an import that reached it would be reaching this checkout.
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            cwd="/",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["21", "v"]
