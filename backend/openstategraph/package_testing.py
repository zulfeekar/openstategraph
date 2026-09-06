"""What every workflow package's `tests/` directory was writing by hand.

`docs/adoption.md` promises each package a `tests/` directory holding "real
tests, not decoration", and most of the gallery now has one. Read together
they turned out to share a spine, re-typed file by file: load `workflow.json`, check
the envelope is version 1 and the document version 3, pin the model, then look
up a node or compare an edge set. This module is that spine, extracted once.

**It asserts a document, not a run — and the difference is the whole design.**
The plan that produced this helper (`.scratch/workflow-gallery/research/`
ticket 10, follow-up (a)) sketched an `assert_run_shape(result, decisions=…,
attempts=…, sections=…)`, on the expectation that a package's fixture would
grade a run. It does not, and should not. Every gallery example's smoke run is
recorded in its `AGENTS.md` because a real run costs cloud tokens, and a run
driven by a stubbed model asserts the stub — `examples/chained-summarizer`'s
own test file calls that theatre, correctly. So the mechanical, free,
reproducible half is what a package test takes, and the model-dependent half
stays a recorded observation. The helper is named for what it actually does.

Three ways of measuring a workflow live in this repository and they are not
interchangeable — `docs/evaluation.md` §"Grading during a run vs grading a
dataset" draws the line, and this module is the third of them:

| | asserts | costs | when |
| --- | --- | --- | --- |
| `route.grader` | a candidate answer, in-graph | a model call | every run |
| `openstategraph eval` | a dataset of known answers | a model call per case | deliberately |
| **this module** | the document and its compiled plan | nothing | every `pytest` |

Public surface, deliberately small: `load_document`, `node_of`, `types_of`,
`edges_of`, `assert_document_shape`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "Edge",
    "assert_document_shape",
    "edges_of",
    "load_document",
    "node_of",
    "types_of",
]

#: `(source node, source port, target node, target port)` — an edge flattened
#: to the tuple nine package tests had each defined for themselves.
Edge = tuple[str, str, str, str]

_ENVELOPE_VERSION = 1
_DOCUMENT_VERSION = 3


def load_document(package: Path | str) -> dict[str, Any]:
    """The document inside `<package>/workflow.json`, envelope checked.

    The two version assertions are the reason this is a function and not a
    one-line `json.loads`. They are what stops a test suite from silently
    grading a format it no longer speaks, and each package's own test file
    used to write them out by hand — so each one also had to remember to.
    Failures name the package, because a bare `assert envelope["version"] ==
    1` in a shared helper would name none of its callers.
    """
    package = Path(package)
    envelope: dict[str, Any] = json.loads((package / "workflow.json").read_text())
    assert envelope["version"] == _ENVELOPE_VERSION, (
        f"{package.name}: envelope version {envelope['version']!r}, "
        f"expected {_ENVELOPE_VERSION}"
    )
    document: dict[str, Any] = envelope["document"]
    assert document["version"] == _DOCUMENT_VERSION, (
        f"{package.name}: document version {document['version']!r}, "
        f"expected {_DOCUMENT_VERSION}"
    )
    return document


def node_of(document: dict[str, Any], node_id: str) -> dict[str, Any]:
    """One node by id.

    The hand-written form was `next(n for n in document["nodes"] if ...)`,
    whose failure is a bare `StopIteration` naming neither the id nor the file.
    """
    nodes: list[dict[str, Any]] = document["nodes"]
    for node in nodes:
        if node["id"] == node_id:
            return node
    known = ", ".join(sorted(n["id"] for n in nodes))
    raise AssertionError(f"no node {node_id!r} in this document; it has: {known}")


def types_of(document: dict[str, Any]) -> list[str]:
    """Node types in document order — the "it is four nodes and nothing else"
    assertion, which is order-sensitive on purpose: the order is the file's."""
    return [node["type"] for node in document["nodes"]]


def edges_of(document: dict[str, Any]) -> set[Edge]:
    """Every edge as a flat tuple.

    A *set*, not a list: two documents wired identically must compare equal
    regardless of the order the editor happened to serialise the edges in.
    """
    return {
        (
            edge["source"]["nodeId"],
            edge["source"]["portId"],
            edge["target"]["nodeId"],
            edge["target"]["portId"],
        )
        for edge in document["edges"]
    }


def assert_document_shape(
    document: dict[str, Any],
    *,
    model: str | None = None,
    node_types: Sequence[str] | None = None,
    edges: Iterable[Edge] | None = None,
    compiles: bool = True,
) -> None:
    """The baseline every package document must satisfy, in one call.

    The unconditional half — unique node ids, no edge pointing at a node that
    does not exist — is the half nobody wrote by hand, and it is exactly the
    defect a hand-edited `workflow.json` acquires. The compiler downgrades a
    dangling edge to a *warning* and drops it, so a graph can assemble, run,
    and quietly not contain the edge somebody drew.

    `model`, `node_types` and `edges` each become an assertion only when
    supplied. `model` defaults to `None` — assert nothing — and that default
    **changed** with install-experience T10: it used to be `GALLERY_MODEL`, the
    Ollama-cloud string all 22 shipped examples pinned, and that constant is
    gone with the pins. A document naming no vendor inherits the instance
    default, which is what makes `pip install 'openstategraph[anthropic]'` mean
    Anthropic for a copied example.

    Nothing is lost by the weaker default, because what it guarded is asserted
    once over the whole gallery rather than 22 times inside it:
    `tests/test_documented_install.py::test_no_shipped_example_names_a_provider`
    covers every example, including one whose own test forgets to call this.
    A package that genuinely must run on a particular model still says so by
    passing `model=`.

    `compiles` runs the real `WorkflowCompiler` and requires a warning-free
    plan — the default, because a document that parses while its graph refuses
    to assemble is the failure worth catching cheaply.
    """
    ids = [node["id"] for node in document["nodes"]]
    duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
    assert not duplicates, f"duplicate node ids: {', '.join(duplicates)}"

    known = set(ids)
    for source, _, target, _ in sorted(edges_of(document)):
        assert source in known, f"edge from unknown node {source!r}"
        assert target in known, f"edge to unknown node {target!r}"

    if model is not None:
        actual = document.get("settings", {}).get("model")
        assert actual == model, f"model is {actual!r}, expected the pin {model!r}"

    if node_types is not None:
        assert types_of(document) == list(node_types)

    if edges is not None:
        assert edges_of(document) == set(edges)

    if compiles:
        # Imported here rather than at module scope: loading the compiler pulls
        # in the LangGraph runtime, and a package test that only reads its own
        # JSON should not pay for that.
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        warnings = WorkflowCompiler().plan(document).warnings
        assert warnings == [], "the compiler warned: " + "; ".join(warnings)
