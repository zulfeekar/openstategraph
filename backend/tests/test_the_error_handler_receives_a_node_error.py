"""The graph-wide error handler is handed a real `NodeError`.

**The defect this pins.** `NodeError` was imported in a `try/except ImportError`
that fell back to `None`, beside two others that do the same. The two beside it
fail safe: `TimeoutPolicy` and `CachePolicy` are only ever *stored*, so absent
means the feature is skipped. This one is different — it is the annotation on
`_default_error_handler`'s second parameter, and LangGraph injects the failure
context only into a parameter both named `error` and annotated `NodeError`. A
fallback that replaced the annotation with `None` would not raise; it would
change the handler's contract silently, and the failure would look like a node
that produced nothing.

**Why the fix is to delete the fallback rather than harden it.** Every feature
0.3.0 documents through this compiler — per-node timeout, caching, graph-wide
retry defaults, the error handler itself — is a `langgraph>=1.2` construct. So
`>=1.0` was a floor the product never actually supported, and the fallback
could not be exercised by any installation the product works on. A fallback
nobody can reach is a fallback nobody tests. Raising the floor turns a silent
wrong answer into a loud import error, which is the trade this repository
prefers everywhere else.

`langchain-drift-watch` 03.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import tomllib

import pytest

from langgraph.errors import NodeError

from openstategraph.compile import workflow_compiler
from openstategraph.compile.workflow_compiler import (
    _default_error_handler,
    _error_handler_for,
    parse_failure_marker,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.library_contract
def test_the_handler_parameter_is_what_the_library_matches_on() -> None:
    """Named `error`, annotated `NodeError` — class or the literal string.

    `from __future__ import annotations` in the compiler makes it the string,
    which the matcher accepts. Both spellings are allowed here so a future
    removal of that import does not fail this test for no behaviour change.
    """
    for handler in (_default_error_handler, _error_handler_for({})):
        parameters = list(inspect.signature(handler).parameters.values())
        assert len(parameters) == 2, f"{handler} lost its arity"
        second = parameters[1]
        assert second.name == "error"
        assert second.annotation in (NodeError, "NodeError"), (
            f"{handler} annotates its injected parameter {second.annotation!r}; "
            "LangGraph injects only into `error: NodeError`"
        )


@pytest.mark.library_contract
def test_a_real_node_error_is_what_the_handler_reads() -> None:
    """The handler reads `.node` and `.error` off a genuine `NodeError`.

    Constructed from the library's own class rather than a stand-in, because a
    duck-typed stub would pass whatever the handler did and is precisely what
    the fallback would have produced.
    """
    cause = ConnectionError("the provider refused")
    error = NodeError("n1", cause)

    update = _error_handler_for({"n1": "canvas-1"})({}, error)

    outputs = update["outputs"]
    # Filed under the canvas id, not the graph name: every reader of `outputs`
    # uses the former, so the mapping is the whole point of this seam.
    assert list(outputs) == ["canvas-1"]
    described = parse_failure_marker(outputs["canvas-1"])
    assert described is not None, "the output is not a failure marker"
    assert "refused" in described


def test_no_library_import_in_the_compiler_falls_back_to_none() -> None:
    """No `except ImportError` in the compiler assigns `None` to a library name.

    The shape, not the name: the next one of these would be written the same
    way and would be just as silent.
    """
    source = pathlib.Path(workflow_compiler.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        imports_a_library = any(
            isinstance(statement, ast.ImportFrom)
            and (statement.module or "").split(".")[0]
            in {"langgraph", "langchain", "langchain_core"}
            for statement in node.body
        )
        if not imports_a_library:
            continue
        for handler in node.handlers:
            for statement in ast.walk(handler):
                if (
                    isinstance(statement, ast.Assign)
                    and isinstance(statement.value, ast.Constant)
                    and statement.value.value is None
                ):
                    names = [
                        target.id
                        for target in statement.targets
                        if isinstance(target, ast.Name)
                    ]
                    offenders.extend(f"line {statement.lineno}: {n}" for n in names)

    assert offenders == [], (
        "a library import degrades to None in the compiler: "
        f"{offenders} — require the version instead, so the failure is loud"
    )


def test_the_declared_floor_is_the_version_the_compiler_needs() -> None:
    """`pyproject` requires the langgraph that has these constructs.

    Derived from the metadata rather than typed twice: the number lives in one
    place and this reads it.
    """
    metadata = tomllib.loads(
        (REPO_ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )
    requirement = next(
        line
        for line in metadata["project"]["dependencies"]
        if line.startswith("langgraph")
    )

    floor = requirement.split(">=")[1].split(",")[0].strip()
    major, minor = (int(part) for part in floor.split(".")[:2])
    assert (major, minor) >= (1, 2), (
        f"langgraph is required at {floor}, but NodeError, TimeoutPolicy and "
        "CachePolicy all arrived in 1.2 and the compiler imports them outright"
    )
