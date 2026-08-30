"""The framework-free run surface, pinned by resolution rather than by spelling.

`CLAUDE.md` states the rule for the TypeScript half — `core/` imports neither
React nor JointJS — and `src/layerBoundaries.test.ts` is what makes it a rule
rather than a preference. The owner's requirement for the streaming adaptor is
the same rule on the Python side, and it is the whole design constraint:

> the endpoint should call out to a workflow … it cannot be FastAPI, because
> most users use FastAPI but some might use a different framework — so it has
> to be agnostic or generic.

A surface that imports one web framework is that framework's adapter, and the
adopter on another one is back to hand-writing the fold that
`docs/wiring-it-in.md` §3 taught. So this file asks two questions, and the
second is the one that is easy to forget:

1. **Does anything in the surface's own import closure name a web framework?**
2. **Does the surface invent a second event vocabulary?** Because a core module
   free of FastAPI that publishes thirty field names of its own has broken the
   *other* standing rule — Pydantic is the single source of truth for the
   run/stream seam, and nobody mirrors it.

**Resolved, never matched**, which is `layerBoundaries`' finding restated for
Python. A grep for `import fastapi` is a gate on one spelling; the closure walk
below follows every `openstategraph.*` import — module-level and
function-local, since this codebase imports lazily on purpose — and asks what
each one *lands on*. A framework three modules down is the same defect as one
at the top, and it is the one a grep cannot see.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "openstategraph"

#: The modules the adaptor promise is made about. `run_stream` is the surface
#: an adopter iterates; `stream_parts` is the chunk decoder it shares with the
#: SSE fold; `loader` is the door that mints one, and a framework reaching the
#: surface through its own constructor would be the same breach.
SURFACE: tuple[str, ...] = (
    "openstategraph.run_stream",
    "openstategraph.stream_parts",
    "openstategraph.loader",
)

#: Every distribution that would make this somebody's adapter. Not a list of
#: what is installed — a list of what the promise excludes, so a framework
#: nobody here has ever used still fails on the day it appears.
WEB_FRAMEWORKS: frozenset[str] = frozenset(
    {
        "aiohttp",
        "bottle",
        "django",
        "falcon",
        "fastapi",
        "flask",
        "litestar",
        "quart",
        "sanic",
        "starlette",
        "tornado",
        "uvicorn",
        "werkzeug",
        # Not a framework, an ASGI *type*: importing it is how a module comes
        # to speak `receive`/`send` and stops being agnostic without ever
        # naming a server.
        "asgiref",
    }
)

#: The one directory whose modules are the operated web layer. Reaching it from
#: core inverts the dependency even when the module it lands on happens to be
#: framework-free today — `api/streaming.py` is, and it is still tier 3.
API_LAYER = "openstategraph.api"


def _module_path(name: str) -> Path | None:
    """Where a dotted `openstategraph.*` name lives on disk, or `None`."""
    relative = Path(*name.split(".")[1:])
    for candidate in (
        PACKAGE / relative.with_suffix(".py"),
        PACKAGE / relative / "__init__.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def _imports_of(path: Path) -> set[str]:
    """Every module this file imports, at any depth of its body.

    `ast.walk`, never the top-level statements only: this package imports
    langgraph, langchain and half of its own modules *inside* functions, on
    purpose — `import openstategraph` has to stay cheap — so a gate reading
    only the header would be blind to exactly the idiom the codebase uses.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import; this package writes none
                continue
            if node.module:
                found.add(node.module)
    return found


def _closure(roots: tuple[str, ...]) -> dict[str, set[str]]:
    """Every `openstategraph` module reachable from `roots`, and what it imports."""
    seen: dict[str, set[str]] = {}
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        path = _module_path(name)
        if path is None:
            continue
        imports = _imports_of(path)
        seen[name] = imports
        pending.extend(
            imported
            for imported in imports
            if imported.startswith("openstategraph.") and imported not in seen
        )
    return seen


class TestNoFrameworkIsReachable:
    """Question one: what does the closure land on."""

    def test_the_closure_was_actually_walked(self) -> None:
        """A gate that resolved nothing would pass everything.

        The failure this guards against is silent: rename a module, and
        `_module_path` starts answering `None`, and every assertion below holds
        vacuously over an empty closure.
        """
        closure = _closure(SURFACE)

        assert set(SURFACE) <= set(closure), (
            f"the surface itself did not resolve: {sorted(set(SURFACE) - set(closure))}"
        )
        assert len(closure) > 10, (
            f"only {len(closure)} modules reachable from the run surface, which is "
            "fewer than this package can possibly need — the walk is broken, not clean."
        )

    def test_nothing_in_the_closure_names_a_web_framework(self) -> None:
        offenders: dict[str, list[str]] = {}
        for module, imports in _closure(SURFACE).items():
            named = sorted(
                imported
                for imported in imports
                if imported.split(".")[0] in WEB_FRAMEWORKS
            )
            if named:
                offenders[module] = named

        assert not offenders, (
            f"a web framework is reachable from the framework-free run surface: "
            f"{offenders}.\n"
            "This is not a style rule. The adaptor exists because an adopter's "
            "endpoint may be on any framework, and a core that imports one has "
            "chosen for them — every other adopter is then back to hand-writing "
            "the fold.\n"
            "The framework-specific part belongs in the adopter's own handler, "
            "which is eight lines; `docs/adding-openstategraph-to-your-project.md` "
            "§8 carries one for FastAPI and one for Flask."
        )

    def test_the_new_modules_do_not_reach_the_operated_web_layer(self) -> None:
        """The two modules this promise is *about*, and only those.

        **Deliberately narrower than the framework walk above, and the reason
        is a measurement rather than a preference.** Asked of the whole
        closure, this fails today: `loader.py` imports
        `api.model_resolution`, `api.registries`, `api.services` and
        `api.workflow_store`, and so do `validation.py`,
        `compile/workflow_compiler.py` and three more. The library door has
        depended on four tier-3 modules since long before this surface existed.

        That inversion is real and is not this ticket's to unwind — it is a
        registry-homing question across seven modules, and pretending otherwise
        by widening the gate would have produced exactly the outcome this
        repository names as the death of a pin: a red test on day one, then a
        suppression, then nothing measured at all.

        What is not negotiable is that the surface added here does not deepen
        it. So the gate is exact about its own two modules, and the framework
        walk above is the one that covers everything — which is the assertion
        that actually carries the promise, because those four `api` modules are
        themselves framework-free and the walk proves it rather than assuming
        it.
        """
        owned = ("openstategraph.run_stream", "openstategraph.stream_parts")
        closure = _closure(owned)
        offenders = {
            module: sorted(i for i in imports if i.startswith(API_LAYER + "."))
            for module, imports in closure.items()
            if module in owned
            and any(i.startswith(API_LAYER + ".") for i in imports)
        }

        assert not offenders, (
            f"the run surface reached the operated web layer: {offenders}.\n"
            "`openstategraph.api.*` is tier 3 and may be renamed in a patch "
            "release; something both layers need belongs in core, the way "
            "`stream_parts.py` and the two message predicates in `messages.py` do."
        )

    def test_importing_the_surface_loads_no_framework(self) -> None:
        """The closure walk is static; this is the same question asked at run time.

        A subprocess rather than an assertion about this one, because pytest has
        already imported half the package — including, in a full run, the API
        layer's own tests.
        """
        probe = (
            "import sys, json;"
            "import openstategraph.run_stream;"
            "import openstategraph;"
            "openstategraph.load_workflow;"
            f"print(json.dumps(sorted(m for m in sys.modules "
            f"if m.split('.')[0] in {sorted(WEB_FRAMEWORKS)!r})))"
        )
        done = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=PACKAGE.parent,
        )

        assert done.returncode == 0, done.stderr
        assert done.stdout.strip() == "[]", (
            f"importing the run surface pulled in {done.stdout.strip()}"
        )


def _emitted() -> dict[str, set[str]]:
    """Every event `run_stream.py` can emit, and the fields it puts on each.

    Read out of the module's own `RunEvent(...)` calls rather than listed here,
    for the reason this whole file exists: a list somebody maintains by
    attention is the thing that drifts. A call this cannot read — a name built
    at run time, a payload spread from a variable — fails loudly below rather
    than being skipped, because a vocabulary that is partly invisible to the
    pin is a vocabulary the pin does not cover.
    """
    path = _module_path("openstategraph.run_stream")
    assert path is not None
    tree = ast.parse(path.read_text(), filename=str(path))

    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "RunEvent"):
            continue
        assert len(node.args) == 2, f"unreadable RunEvent call at line {node.lineno}"
        name, payload = node.args
        assert isinstance(name, ast.Constant) and isinstance(name.value, str), (
            f"the event name at line {node.lineno} is not a literal, so nothing "
            "can check it against the published vocabulary"
        )
        assert isinstance(payload, ast.Dict), (
            f"the payload at line {node.lineno} is not a literal dict"
        )
        keys = set()
        for key in payload.keys:
            assert isinstance(key, ast.Constant) and isinstance(key.value, str), (
                f"a non-literal payload key at line {node.lineno}"
            )
            keys.add(key.value)
        found.setdefault(name.value, set()).update(keys)
    return found


class TestTheVocabularyIsThePublishedOne:
    """Question two: is this a second contract wearing the first one's clothes."""

    def test_it_emits_something(self) -> None:
        emitted = _emitted()

        assert emitted, "no RunEvent literals found — the reader below is broken"

    def test_every_event_name_is_published(self) -> None:
        from openstategraph.api.streaming import RUN_EVENTS

        emitted = _emitted()
        invented = sorted(set(emitted) - set(RUN_EVENTS))

        assert not invented, (
            f"the run surface emits event names the wire does not publish: {invented}.\n"
            f"published: {sorted(RUN_EVENTS)}.\n"
            "One vocabulary, two transports. A consumer that moves from our SSE "
            "endpoint to an embedded stream — or reads both, which an adopter "
            "running the server beside the library does — must not have to learn "
            "the run twice."
        )

    @pytest.mark.parametrize("event", sorted(_emitted()))
    def test_every_field_is_published(self, event: str) -> None:
        from openstategraph.api.streaming import FRAME_FIELDS

        extra = sorted(_emitted()[event] - set(FRAME_FIELDS.get(event, ())))

        assert not extra, (
            f"the `{event}` event carries fields the published frame does not: "
            f"{extra}.\n"
            f"published for `{event}`: {sorted(FRAME_FIELDS.get(event, ()))}.\n"
            "A field invented here is a hand-mirror of the run/stream seam, which "
            "is the one thing `CLAUDE.md` forbids outright: Pydantic owns that "
            "seam and `docs/openapi.json` publishes it. Add the field to "
            "`_PAYLOAD_FIELDS` where every consumer learns about it, or do not "
            "carry it."
        )

    def test_the_envelope_key_cannot_collide_with_a_payload_field(self) -> None:
        """`RunEvent.as_dict()` puts `type` beside the payload, so `type` must be free."""
        from openstategraph.api.streaming import FRAME_FIELDS

        clashes = sorted(name for name, fields in FRAME_FIELDS.items() if "type" in fields)

        assert not clashes, (
            f"a published frame now carries a field called `type`: {clashes}. "
            "`RunEvent.as_dict()` would silently overwrite it — rename the "
            "envelope key there, or the field."
        )
