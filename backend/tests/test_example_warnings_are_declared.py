"""A shipped example may warn — but only about something it declared.

`scripts/build_gallery_diagrams.py` refused to publish any example that
compiled with a warning, which was right while every warning meant something
was wrong. `Finding` changed that: `UNWIRED_REVISE` exists precisely to say
*this graph is legal and less capable than it looks*, and `support-triage`
used to ship one on purpose (`workflow-gallery` 31) — until `workflow-gallery`
78 wired its `revise` edge and the declaration was retired with it, so no
example currently declares anything. So the generator exited 1 on a clean
checkout for months and the gallery SVGs went stale (`workflow-gallery` 55).

The rule that replaces "no warnings": **a warning the example declared is
fine; anything else fails.** A declaration that stopped firing fails too — a
stale expectation is how a gate quietly stops gating.

Nothing ran that check outside the script, which is why nobody noticed. This
module is where it runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openstategraph import load_workflow
from openstategraph.compile.diagnostics import CompileDiagnostics, Finding
from openstategraph.examples import DATA, Example, catalogue, warning_drift


def compiled_warnings(slug: str) -> list[str]:
    workflow = load_workflow(DATA / slug)
    try:
        return list(workflow.warnings)
    finally:
        workflow.close()


@pytest.mark.parametrize("example", catalogue(), ids=lambda e: e.slug)
def test_every_example_warns_only_as_declared(example: Example) -> None:
    undeclared, absent = warning_drift(example, compiled_warnings(example.slug))
    assert undeclared == [], (
        f"{example.slug} compiles with a warning it never declared: {undeclared}. "
        "Fix the example, or declare the finding in examples/index.json."
    )
    assert absent == [], (
        f"{example.slug} declares a finding it no longer produces: {absent}."
    )


def test_exactly_same_package_twice_currently_declares_a_finding() -> None:
    """`support-triage` was the deliberate `UNWIRED_REVISE` case (gallery 31)
    — its grader shipped `pass` only, and `expectedFindings` said so on
    purpose. `workflow-gallery` 78 wired its `revise` edge to match the dev
    workspace copy, so it no longer produces that finding and its declaration
    was removed from `examples/index.json` along with the `_comment`
    explaining it — a declaration that stopped firing is drift, per this
    module's own rule, and a stale declaration is worse than none. Between
    that and `launch-readiness` 40 the list really was empty.

    `same-package-twice` is the new deliberate case: two sibling mounts of
    `chained-summarizer`, each carrying its own `data.overrides` on purpose —
    the shipped illustration of "one definition, two instances" — so the two
    `Finding.OVERRIDE_APPLIED` reports it now compiles with are exactly what
    the example is *for*, declared rather than left as undeclared drift.

    No other package in the gallery currently ships a deliberate, declared
    warning. Inventing one to keep this test's premise alive was considered
    and rejected the same way the docstring above rejected it for
    `UNWIRED_REVISE`; if the gallery wants a second one, add it under its own
    ticket and this assertion is where it gets named.
    """
    declaring = [e.slug for e in catalogue() if e.expected_findings]
    assert declaring == ["same-package-twice"]


def test_an_undeclared_warning_is_drift() -> None:
    plain = Example(slug="x", pattern="p")
    undeclared, absent = warning_drift(plain, ["something new went wrong"])
    assert undeclared == ["something new went wrong"]
    assert absent == []


def test_a_declaration_that_no_longer_fires_is_drift() -> None:
    declared = Example(
        slug="x", pattern="p", expected_findings=((Finding.UNWIRED_REVISE.value, ("g1",)),)
    )
    undeclared, absent = warning_drift(declared, [])
    assert undeclared == []
    assert absent == [CompileDiagnostics.sentence_for(Finding.UNWIRED_REVISE).format("g1")]


def test_a_declaration_is_formatted_from_the_shared_template() -> None:
    """Declared by kind and subject, never by pasted prose.

    The sentence comes from `_SENTENCES`, so rewording a finding cannot turn a
    correct declaration into drift.
    """
    declared = Example(
        slug="x", pattern="p", expected_findings=((Finding.UNWIRED_REVISE.value, ("g1",)),)
    )
    sentence = CompileDiagnostics.sentence_for(Finding.UNWIRED_REVISE).format("g1")
    assert warning_drift(declared, [sentence]) == ([], [])
