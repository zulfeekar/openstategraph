"""The per-request setup path — plan, tool import, skill read, build — is
milliseconds, and it never touches the network.

`launch-readiness/113` suspected this path of being the cost behind `109`
("a turn takes far longer than a comparable assistant"). The ticket's own
instruction was **measure before building**, and the measurement said no:
against a private package — 28 nodes, four `tools/*.py`, five `skills/*.md`, the
heaviest package this project has — the whole setup path is **~27 ms warm**
and ~85 ms on a process's first pass, against turns of 27–57 s. The argument
and the numbers are `docs/decisions/per-request-compile-cost.md`; the
instrument that produced them is `scripts/measure_setup_path.py`.

This file is what stops that decision from becoming a story. Two pins, and
they are deliberately different in kind:

- **A ceiling, which is a smoke alarm and not a stopwatch.** A wall-clock
  assertion tight enough to catch a 3× regression would flake on a loaded
  machine, so the ceiling here is loose by two orders of magnitude. What it
  actually catches is the regression that would matter: setup acquiring a
  *blocking* cost — a network round trip, a model call, a subprocess — rather
  than getting somewhat slower.
- **No sockets, which is sharp.** Compiling a document is pure local work.
  A `build` that opens a connection is the defect the ceiling would only
  notice once it was slow, and this notices it the first time.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "openstategraph" / "examples"

#: Two orders of magnitude above the measured warm figure for the heaviest
#: real package. See the module docstring for why it is not tighter.
CEILING_SECONDS = 5.0


class _NeverCalledModel:
    """Enough surface for the compiler to bind nodes, and nothing that runs."""

    def bind_tools(self, *_a: Any, **_k: Any) -> "_NeverCalledModel":
        return self

    def with_structured_output(self, *_a: Any, **_k: Any) -> "_NeverCalledModel":
        return self

    def with_config(self, *_a: Any, **_k: Any) -> "_NeverCalledModel":
        return self

    def invoke(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("the setup path must not call a model")


def _setup_once(package: Path, root: Path) -> None:
    """Exactly what `api/routes/runs.py` does before it starts the graph."""
    from openstategraph.api.services import WorkflowServices
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    raw = json.loads((package / "workflow.json").read_text())
    document = raw.get("document", raw)

    services = WorkflowServices(root)
    compiler = WorkflowCompiler()
    compiler.plan(document)
    runtime = services.runtime_for(package.name, document, _NeverCalledModel(), warnings=[])
    compiler.build(document, RunState, runtime.factory(document))


@pytest.fixture(name="package")
def _package(monkeypatch: pytest.MonkeyPatch) -> Path:
    """A shipped example carrying a `tools/*.py`, so the tool-import half of
    the path is genuinely exercised rather than skipped as absent."""
    package = EXAMPLES / "guarded-lookup"
    assert list((package / "tools").glob("*.py")), "this pin needs a package with tools/"
    monkeypatch.setenv("OPENSTATEGRAPH_WORKFLOWS_ROOT", str(EXAMPLES))
    return package


def test_the_setup_path_is_milliseconds_not_seconds(package: Path) -> None:
    _setup_once(package, EXAMPLES)  # warm the lazy imports, as a live server is

    started = time.perf_counter()
    _setup_once(package, EXAMPLES)
    elapsed = time.perf_counter() - started

    assert elapsed < CEILING_SECONDS, (
        f"the per-request setup path took {elapsed * 1000:.0f} ms against a "
        f"{CEILING_SECONDS * 1000:.0f} ms ceiling. This ceiling is loose on "
        "purpose, so crossing it means setup has acquired a blocking cost "
        "rather than merely slowed down. Re-run scripts/measure_setup_path.py "
        "and update docs/decisions/per-request-compile-cost.md before raising it."
    )


def test_the_setup_path_opens_no_socket(package: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planning, importing a package's tools and building a graph are local
    work. The moment one of them dials out, the cost stops being ours to
    predict — and `113`'s measurement stops speaking for anyone's network."""
    _setup_once(package, EXAMPLES)  # imports first: a lazy import may vendor-check

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise AssertionError(
            "the setup path opened a socket. Compiling a document must not "
            "reach the network — see docs/decisions/per-request-compile-cost.md."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)

    _setup_once(package, EXAMPLES)
