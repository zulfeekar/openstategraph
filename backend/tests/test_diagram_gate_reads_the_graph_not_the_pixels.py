"""The gallery's drift gate must fail on a changed graph and only on a changed graph.

`workflow-gallery` 80. Until this file existed the gate compared the rendered
SVG **bytes**, and that is a comparison whose answer depends on which fonts the
machine has installed — mermaid asks the browser how wide every label is and
lays the flowchart out from the answer. CI run 32659487566 is the receipt: exit
1 on the runner, exit 0 on the developer machine, off the same commit, one
session after the artefact had been correctly regenerated (`0b69884`).

So the two halves of the argument are pinned here rather than asserted in
prose, because the whole defect was a claim ("the committed page is out of
date") that had no way to be wrong about itself:

- **geometry is not drift** — move every coordinate and the gate stays quiet;
- **the graph is drift** — take one arrow, or rename one box, and it speaks.

A third is pinned because it is the failure mode of every parser-based gate:
a diagram the parser cannot read must **raise**, never quietly compare nothing
against nothing.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import diagram_gate  # noqa: E402
from diagram_gate import UnreadableDiagram, drift, shape_of_source, shape_of_svg  # noqa: E402


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gallery():
    return _script("build_gallery_diagrams")


@pytest.fixture(scope="module")
def committed(gallery) -> dict[str, str]:
    return gallery.regions((REPO / "site" / "gallery.html").read_text())


SUBJECT = "support-triage"


def test_every_committed_diagram_still_draws_the_graph_the_compiler_builds(gallery, committed):
    """The gate itself, as a test — so a stale picture fails a suite and not only CI.

    The same reason `test_example_warnings_are_declared.py` exists beside the
    script's own warning check.
    """
    sources = gallery.mermaid_sources()
    complaints: list[str] = []
    for slug, source in sources.items():
        assert slug in committed, f"the page draws no diagram for {slug}"
        complaints.extend(drift(slug, source, committed[slug]))
    assert not complaints, "\n".join(complaints)


def test_a_diagram_laid_out_by_a_different_font_is_not_drift(committed):
    """The CI failure, reproduced and then required to be silent.

    Every number in a mermaid SVG is a font metric, so a runner without Inter
    produces a different one for the same graph. Nudging every coordinate is
    that difference in its purest form: nothing about the graph moved.
    """
    svg = committed[SUBJECT]
    relaid = re.sub(r"\d+\.\d+", lambda m: f"{float(m.group(0)) * 1.07 + 3:.5f}", svg)
    assert relaid != svg
    assert shape_of_svg(relaid) == shape_of_svg(svg)
    assert drift(SUBJECT, _source_for(SUBJECT), relaid) == []


def test_a_lost_arrow_is_drift(committed):
    without = committed[SUBJECT].replace("flowchart-link", "gone", 1)
    complaints = drift(SUBJECT, _source_for(SUBJECT), without)
    assert complaints, "an arrow can vanish from the picture and the gate is quiet"
    assert any("arrows" in line for line in complaints)


def test_a_renamed_box_is_drift(committed):
    renamed = committed[SUBJECT].replace("<p>Which desk</p>", "<p>Which queue</p>")
    assert renamed != committed[SUBJECT]
    complaints = drift(SUBJECT, _source_for(SUBJECT), renamed)
    assert any("boxes" in line for line in complaints), complaints


def test_a_relabelled_arrow_is_drift(committed):
    relabelled = committed[SUBJECT].replace("&nbsp;revise&nbsp;", "&nbsp;retry&nbsp;")
    assert relabelled != committed[SUBJECT]
    complaints = drift(SUBJECT, _source_for(SUBJECT), relabelled)
    assert any("arrow labels" in line for line in complaints), complaints


@pytest.mark.parametrize("fragment", ["", "   ", "<div>not a diagram</div>", "<svg></svg>"])
def test_a_diagram_the_gate_cannot_read_is_not_a_pass(fragment):
    with pytest.raises(UnreadableDiagram):
        shape_of_svg(fragment)


def test_a_mermaid_line_the_gate_cannot_classify_is_not_a_pass():
    with pytest.raises(UnreadableDiagram):
        shape_of_source("graph TD;\n\ta(A)\n\ta ==> b;\n")


def test_the_gate_needs_no_browser(gallery, monkeypatch):
    """The property the whole ticket bought, stated where it can fail.

    A `--check` that renders is a `--check` whose answer depends on the machine,
    which is what CI run 32659487566 measured. So rendering during a check is
    made impossible here rather than merely avoided.
    """

    def refuse(*_args, **_kwargs):
        raise AssertionError("--check rendered a diagram")

    monkeypatch.setattr(gallery, "render", refuse)
    monkeypatch.setattr(sys, "argv", ["build_gallery_diagrams.py", "--check"])
    assert gallery.main() == 0


def test_the_behind_the_scenes_page_is_gated_the_same_way(monkeypatch):
    page = _script("build_behind_the_scenes")

    def refuse(*_args, **_kwargs):
        raise AssertionError("--check rendered a diagram")

    monkeypatch.setattr(page, "render_svg", refuse)
    monkeypatch.setattr(sys, "argv", ["build_behind_the_scenes.py", "--check"])
    assert page.main() == 0


def test_neither_page_is_gated_on_rendered_bytes():
    """No `--check` may compare a page it re-rendered.

    The defect was one line — `if before != after` over a page carrying fresh
    SVG — and it was written twice, once per script. This is what stops a third.
    """
    for name in ("build_gallery_diagrams", "build_behind_the_scenes"):
        text = (REPO / "scripts" / f"{name}.py").read_text()
        check = text.split("def check(", 1)[1].split("\ndef ", 1)[0]
        assert "render" not in check, f"{name}.check renders the page it is checking"


def _source_for(slug: str) -> str:
    return sys.modules["build_gallery_diagrams"].mermaid_sources()[slug]


def test_normalise_reads_the_two_spellings_of_one_label():
    """`&nbsp;revise&nbsp;` in the source and `<p>&nbsp;revise&nbsp;</p>` in the
    render are one label, and the gate has to know it — otherwise every
    conditional edge in the gallery reads as drift."""
    assert diagram_gate.normalise("&nbsp;revise&nbsp;") == "revise"
    assert diagram_gate.normalise("<p>&nbsp;revise&nbsp;</p>") == "revise"
