"""Shape test scaffolded with this package — a starting point, not a suite.

`openstategraph new` writes this alongside `workflow.json`. It asserts the
*document*, not the template that produced it — a template is a scaffold
input, and it has already stopped existing by the time this file runs.
Edit it as the document changes; it is yours now.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.package_testing import assert_document_shape, load_document

PACKAGE = Path(__file__).resolve().parents[1]


def test_document_shape() -> None:
    """The document loads, its node types are what was scaffolded, and it
    compiles clean under the strict default (no dropped edges, no dangling
    references, no duplicate ids)."""
    document = load_document(PACKAGE)
    assert_document_shape(
        document,
        node_types=[
            "input.text",
            "orchestrate.supervisor",
            "orchestrate.worker",
            "function.format_report",
            "route.grader",
            "output.formatted",
        ],
    )
