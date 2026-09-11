"""A timeout is dropped for a node whose body cannot be interrupted.

**The defect this pins, because it shipped.** `add_node(timeout=...)` is a
LangGraph 1.2 parameter, and LangGraph refuses it for a synchronous body — the
refusal is at *compile* time, so it takes the whole graph down rather than the
one node. `_node_overrides` passed a `TimeoutPolicy` for any node whose card
carried `timeoutSeconds`, and the editor offers that field on every executable
type, so a document with a timeout on an Output node could not be loaded at
all. The value was reachable in two clicks and there was no way back to a
working graph except editing the JSON by hand.

**The library fact was already written down.** `test_a_library_default_is_never_literalised.py`
asserts that LangGraph's own timeout module says "only supported for async".
Nothing asserted *our* code against it, which is the whole argument for the
drift patrol (`langchain-drift-watch/05`): a fact recorded in one place while
another place contradicts it is the defect this repository keeps finding in
itself.

**Why the compiler drops rather than refuses.** Documents carrying the setting
exist and cannot compile today; a fix that refused them at load would strand
them, and a `validate` that turned an ignored setting into `PROBLEMS FOUND`
would fail a working graph in somebody's CI over advice. So the override is
removed, one sentence is reported per node, and the saved document is never
rewritten. The editor half (`02`) stops *new* documents acquiring it.

**And the decision is taken from the built body, never from a list of type
ids.** `is_interruptible` already answers "can this body be cancelled", which
is the same question as "can this body carry a timeout". A second table of
async node types beside the first is the shape that produced this defect, and
`test_no_second_table_says_which_types_are_async` refuses it.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

from openstategraph.compile.diagnostics import REPORT_ONLY, CompileDiagnostics, Finding
from openstategraph.compile.node_runtime import RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler
from openstategraph.loader import normalize_document

PACKAGE = REPO_ROOT / "workflows" / "classifier-router-qa"
SYNC_NODE = "out-general"
SYNC_NODE_TYPE = "output.formatted"


def _document_with_a_timeout_on_a_sync_node() -> dict[str, Any]:
    """The shipped example, with a timeout typed onto its Output card."""
    document = normalize_document(json.loads((PACKAGE / "workflow.json").read_text()))
    for node in document["nodes"]:
        if node["id"] == SYNC_NODE:
            node.setdefault("data", {})["timeoutSeconds"] = "30"
    return document


def _sync_factory(node_id: str, node: dict[str, Any], plan: Any) -> Any:
    def body(state: dict[str, Any]) -> dict[str, Any]:
        return {}

    return body


def _async_factory(node_id: str, node: dict[str, Any], plan: Any) -> Any:
    async def body(state: dict[str, Any]) -> dict[str, Any]:
        return {}

    return body


@pytest.mark.library_contract
def test_the_library_still_refuses_a_timeout_on_a_sync_body() -> None:
    """LangGraph rejects the combination at compile time, not at run time.

    Pinned here as well as in the library-facts file because this is the seam
    that depends on it: the day this stops being true, the compiler may stop
    dropping the override, and nothing else would say so.
    """
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import TimeoutPolicy

    builder = StateGraph(RunState)

    def sync_body(state: dict[str, Any]) -> dict[str, Any]:
        return {}

    builder.add_node("n", sync_body, timeout=TimeoutPolicy(run_timeout=1))
    builder.add_edge(START, "n")
    builder.add_edge("n", END)

    with pytest.raises(ValueError) as raised:
        builder.compile()

    assert "only supported for async" in str(raised.value)


def test_a_sync_node_with_timeout_seconds_compiles() -> None:
    """The document that could not be loaded at all now loads."""
    diagnostics = CompileDiagnostics()

    graph = WorkflowCompiler().build(
        _document_with_a_timeout_on_a_sync_node(),
        RunState,
        _sync_factory,
        diagnostics=diagnostics,
    )

    assert graph is not None
    assert diagnostics.subjects(Finding.TIMEOUT_NEEDS_ASYNC_NODE) == [
        (SYNC_NODE, SYNC_NODE_TYPE)
    ]


def test_the_finding_is_a_report_and_not_a_failure() -> None:
    """It never reaches an exit code: an ignored setting is advice."""
    assert Finding.TIMEOUT_NEEDS_ASYNC_NODE in REPORT_ONLY

    diagnostics = CompileDiagnostics()
    WorkflowCompiler().build(
        _document_with_a_timeout_on_a_sync_node(),
        RunState,
        _sync_factory,
        diagnostics=diagnostics,
    )

    assert diagnostics.failure_warnings() == []

    # But it is still said. `warnings()` is what a developer surface reads;
    # `failure_warnings()` is what an exit code reads, and this belongs only in
    # the first.
    sentence = " ".join(diagnostics.warnings())
    assert SYNC_NODE in sentence
    assert SYNC_NODE_TYPE in sentence
    assert "asynchronously" in sentence


def test_a_document_with_no_sink_still_compiles() -> None:
    """Correctness first: the override is dropped whether or not anyone listens.

    `build` is called without a `diagnostics` sink from several places. A
    version that only removed the override when someone was recording would
    reintroduce the defect for every one of them.
    """
    graph = WorkflowCompiler().build(
        _document_with_a_timeout_on_a_sync_node(), RunState, _sync_factory
    )

    assert graph is not None


def test_an_async_node_keeps_its_timeout() -> None:
    """The capability is withdrawn only where it cannot work."""
    from openstategraph.compile.workflow_compiler import safe_name

    diagnostics = CompileDiagnostics()
    graph = WorkflowCompiler().build(
        _document_with_a_timeout_on_a_sync_node(),
        RunState,
        _async_factory,
        diagnostics=diagnostics,
    )

    assert not diagnostics.any(Finding.TIMEOUT_NEEDS_ASYNC_NODE)

    node = graph.nodes[safe_name(SYNC_NODE)]
    # Read off the installed PregelNode rather than assumed: the attribute is
    # the library's, and a name typed from memory is the defect one layer up.
    policy = getattr(node, "timeout", None)
    assert policy is not None, "the async node lost a timeout it can honour"
    assert getattr(policy, "run_timeout", None) == 30.0


def test_the_finding_reaches_a_loaded_workflow(tmp_path: pathlib.Path) -> None:
    """End to end: the package that could not load, loads and says why.

    Through `load_workflow` rather than the compiler alone, because the sink is
    the thing being tested — the compiler records into whatever it is handed,
    and the defect a user meets is the sentence not arriving.
    """
    import shutil

    from langgraph.checkpoint.memory import InMemorySaver

    from openstategraph import load_workflow

    package = tmp_path / "classifier-router-qa"
    shutil.copytree(PACKAGE, package)
    stored = json.loads((package / "workflow.json").read_text())
    for node in stored["document"]["nodes"]:
        if node["id"] == SYNC_NODE:
            node.setdefault("data", {})["timeoutSeconds"] = "30"
    (package / "workflow.json").write_text(json.dumps(stored, indent=2))

    workflow = load_workflow(package, checkpointer=InMemorySaver())

    said = " ".join(workflow.warnings)
    assert SYNC_NODE in said
    assert "timeout was not applied" in said
    # And the document on disk is untouched: the value a user typed stays
    # theirs to remove.
    again = json.loads((package / "workflow.json").read_text())
    kept = [
        n for n in again["document"]["nodes"] if n["id"] == SYNC_NODE
    ][0]
    assert kept["data"]["timeoutSeconds"] == "30"


def test_every_door_that_compiles_hands_the_compiler_a_sink() -> None:
    """No surface compiles without somewhere to record what it noticed.

    `build` takes `diagnostics` as an optional keyword so a test can compile
    without one, and that default is a trap for a *shipped* door: a compile-time
    finding is simply lost, and the surface reports a clean workflow it had
    already noticed something about. There were eight such doors when this was
    written — the loader, the blocking run, both streaming runs, the graph
    preview, two MCP tools and a mount. Five is what a careful reading found;
    this test found the other three, which is the argument for writing it.

    Written the way `test_a_runs_diagram_opens_its_mounts.py` is: parse every
    shipped module for the call rather than keeping a list of the doors, because
    a list is the thing that goes stale.
    """
    import ast

    package = pathlib.Path(__import__("openstategraph").__file__).parent

    offenders: list[str] = []
    for module in sorted(package.rglob("*.py")):
        if "examples" in module.parts or "templates" in module.parts:
            # Shipped as package data for a user to copy, not doors of ours.
            continue
        tree = ast.parse(module.read_text(encoding="utf-8", errors="ignore"))
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            attribute = call.func
            if not isinstance(attribute, ast.Attribute) or attribute.attr != "build":
                continue
            # `WorkflowCompiler().build(...)` or `compiler.build(...)`, never
            # `node_instance.build()` — the compiler's is the one with a
            # document and a state schema in front of it.
            if len(call.args) < 3:
                continue
            if any(keyword.arg == "diagnostics" for keyword in call.keywords):
                continue
            offenders.append(f"{module.relative_to(package)}:{call.lineno}")

    assert offenders == [], (
        "a door compiles with no diagnostics sink, so anything the compiler "
        f"notices there is lost: {offenders}"
    )


def test_no_second_table_says_which_types_are_async() -> None:
    """Neither module that decides a timeout holds a list of node type ids.

    The defect was two descriptions of one thing. A hard-coded list of async
    families beside the timeout decision would be a third, and it would go
    stale in exactly the same silence — a family migrated to `async def` would
    keep being refused a timeout it could now honour, with every test green.

    Measured on the literal, not on proximity: an earlier draft of this test
    matched `node:agent.llm-1` inside `safe_name`'s docstring, which is an
    example id and not a table. What is forbidden is a *container* of node type
    ids, because that is the only shape a second table can take.
    """
    import ast
    import re

    type_id = re.compile(r"^[a-z]+\.[a-z_][a-z0-9_-]*$")
    package = pathlib.Path(__import__("openstategraph").__file__).parent
    deciders = [
        package / "compile" / "workflow_compiler.py",
        package / "compile" / "node_doors.py",
    ]

    offenders: list[str] = []
    for module in deciders:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for literal in ast.walk(tree):
            if not isinstance(literal, (ast.Set, ast.List, ast.Tuple)):
                continue
            ids = [
                element.value
                for element in literal.elts
                if isinstance(element, ast.Constant)
                and isinstance(element.value, str)
                and type_id.match(element.value)
            ]
            if len(ids) >= 2:
                offenders.append(f"{module.name}:{literal.lineno} {ids}")

    assert offenders == [], (
        "a node-type table sits in a module that decides timeouts: "
        f"{offenders} — ask the built body with is_interruptible instead"
    )
