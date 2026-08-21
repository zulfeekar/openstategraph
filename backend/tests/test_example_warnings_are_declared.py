"""A shipped example may warn — but only about something it declared.

`scripts/build_gallery_diagrams.py` refused to publish any example that
compiled with a warning, which was right while every warning meant something
was wrong. `Finding` changed that: `UNWIRED_REVISE` exists precisely to say
*this graph is legal and less capable than it looks*, and `support-triage`
ships one on purpose (`workflow-gallery` 31). So the generator exited 1 on a
clean checkout for months and the gallery SVGs went stale
(`workflow-gallery` 55).

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


def test_support_triage_is_the_one_that_declares_something() -> None:
    """The deliberate case, named — so deleting the declaration is a red test."""
    declaring = [e.slug for e in catalogue() if e.expected_findings]
    assert declaring == ["support-triage"]
    assert catalogue()[[e.slug for e in catalogue()].index("support-triage")].expected_findings == (
        (Finding.UNWIRED_REVISE.value, ("grader1",)),
    )


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
