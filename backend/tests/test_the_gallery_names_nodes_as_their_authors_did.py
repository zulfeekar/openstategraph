"""The gallery page names a node the way its author did, not the way the compiler did.

`workflow-gallery` 69. 54's duplicate check found two pairs of *different*
examples compiling to byte-identical Mermaid — `evaluator-optimizer` against
`budget-exhaustion`, `knowledge-lookup-qa` against `sql-qa`. Their authors had
already separated them: one calls its nodes *Draft* / *Review* / *Release
note*, the other *Answer* / *Impossible rubric* / *Last candidate*. The page
threw those away because `mermaid()` prints the node **id**.

The assertions below read the **injected diagram regions of the shipped page**,
never the prose around them — 54's own near-miss was a mutation that came back
green off the page's CSS comment. What a reader can tell apart is the thing
under test, so the test looks at what the reader looks at.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "site" / "gallery.html"
SCRIPT = REPO / "scripts" / "build_gallery_diagrams.py"
EXAMPLES = REPO / "backend" / "openstategraph" / "examples"


def _builder():
    spec = importlib.util.spec_from_file_location("build_gallery_diagrams", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _region(slug: str) -> str:
    found = re.search(f"<!--mmd:{slug}-->(.*?)<!--/mmd:{slug}-->", PAGE.read_text(), re.S)
    assert found, f"the page has no diagram for {slug}"
    return found.group(1)


def _titles(slug: str) -> list[str]:
    payload = json.loads((EXAMPLES / slug / "workflow.json").read_text())
    document = payload.get("document", payload)
    return [str(n.get("title") or "").strip() for n in document["nodes"]]


def test_a_reader_can_tell_the_two_revision_loops_apart() -> None:
    one, other = _region("evaluator-optimizer"), _region("budget-exhaustion")
    assert one != other, (
        "examples 04 and 07 draw the same picture — a reader meets the canonical "
        "revision loop and the step-budget example as one graph (gallery 69)."
    )
    for title in _titles("evaluator-optimizer"):
        assert title in one, f"{title!r} is what this author called a node; the page drops it"
    for title in _titles("budget-exhaustion"):
        assert title in other


def test_a_reader_can_tell_the_two_single_agent_answerers_apart() -> None:
    one, other = _region("knowledge-lookup-qa"), _region("sql-qa")
    assert one != other, "examples 15 and 17 draw the same picture (gallery 69)"
    assert "Vault Registrar" in one
    assert "Analyst" in other


def test_the_page_stopped_printing_the_compilers_vocabulary() -> None:
    """An id is the compiler's word, not the author's — and `__start__` is LangGraph's."""
    page = PAGE.read_text()
    regions = "\n".join(re.findall(r"<!--mmd:[a-z0-9-]+-->(.*?)<!--/mmd:", page, re.S))
    assert regions.strip(), "no diagrams on the page — every assertion here would pass vacuously"
    for machinery in ("__start__", "__end__", "__default_error_handler__"):
        assert machinery not in regions, (
            f"{machinery} is the compiler's own node and is drawn to a reader of the gallery"
        )


def test_an_untitled_node_keeps_its_id_rather_than_being_given_a_name() -> None:
    """Inventing a friendly label is the lie 56 rejected; the id is the honest fallback."""
    builder = _builder()
    text = "graph TD;\n\tin1(in1)\n\tagent1(agent1)\n\tin1 --> agent1;\n"
    named = builder.as_the_author_named_it(
        text, {"nodes": [{"id": "in1", "title": "Question"}, {"id": "agent1"}]}, {}
    )
    assert "in1(Question)" in named
    assert "agent1(agent1)" in named


def test_the_compilers_own_diagram_is_untouched() -> None:
    """62 gives a developer `__start__` and every compiler id on purpose.

    This change is the *page*'s rendering, so `CompiledWorkflow.mermaid()` must
    still answer what it always answered.
    """
    import sys

    sys.path.insert(0, str(REPO / "backend"))
    from openstategraph import load_workflow  # noqa: PLC0415

    text = load_workflow(EXAMPLES / "evaluator-optimizer").mermaid()
    assert "__start__" in text
    assert "draft1(draft1)" in text
    assert "Draft" not in text


def test_a_node_three_levels_down_is_named_by_its_own_author() -> None:
    """Titles are keyed by mount path, not bare id — 56's reason, applied here.

    All three `nested-mounts` documents call their entry node `in1`, so a flat
    title map would answer the parent's word for every one of them. The
    innermost package's own words are the pin.
    """
    region = _region("nested-mounts")
    assert "Cut to one sentence" in region, (
        "the grandchild's nodes are drawn under the compiler's ids — the mount "
        "documents never reached the labeller"
    )
    assert "Chained Summarizer" in region, "the opened mount is not named at all"
