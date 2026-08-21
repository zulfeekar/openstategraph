"""The gallery page shows each compiled graph once, and shows a mount's inside.

`workflow-gallery` 54, and the defect it uncovered on the way (68).

Batch C of `site/gallery.html` is about composition, and for as long as a mount
compiled to one featureless box the only way to show a reader what was inside
one was to draw the child *again* beside its parent. `scripts/build_gallery_diagrams.py`
did that with an `ALIASES` table: four extra renderings of three packages that
were already on the page under their own names.

`workflow-gallery` 28 removed the reason — `CompiledWorkflow.mermaid()` opens
every mount to any depth — so the two pins here are what replaces the table:

1. **No graph is drawn twice.** A reader meets each example once. An alias is
   still allowed, but it must carry a written reason for why this reader needs
   this graph a second time; a bare mapping is refused. A number in prose has
   no way to fail, so the rule is the shape of the entry rather than a count.

2. **A mount's cluster is visible.** `tidy()` strips mermaid's own ~9 KB
   scoped stylesheet from every diagram and the page restyles them once in its
   own tokens — so a class the page does not style falls back to SVG defaults,
   and the SVG default fill is **black**. That is what shipped: every
   `<g class="cluster">` mermaid emits for an opened mount is `<rect style="">`,
   and examples 11, 12 and 13 drew their nesting as solid black rectangles with
   the mount's name written on it in black. Structurally correct, illegible,
   and invisible to every test — which is why the judgement 54 asks for could
   not be made until this was fixed.
"""

from __future__ import annotations

import importlib.util
import re
from collections import defaultdict
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "site" / "gallery.html"
SCRIPT = REPO / "scripts" / "build_gallery_diagrams.py"

# Two pairs of *different* packages used to compile to a byte-identical picture
# — `evaluator-optimizer`/`budget-exhaustion` and `knowledge-lookup-qa`/`sql-qa`,
# found by the check below rather than by anyone looking, which is the best
# argument for having it. **Empty since `workflow-gallery` 69**: everything that
# made each pair two examples lived in prompts, rubrics and tool wiring, but
# their authors had *also* named the nodes apart ("Draft"/"Review" against
# "Answer"/"Impossible rubric"), and the page threw those away because it drew
# ids. It draws titles now, and the four graphs separate on their own.
#
# Kept as an empty declaration rather than deleted: a future collision between
# two examples whose authors chose the same words is a real possibility, and
# this is where the reason for tolerating one gets written down.
KNOWN_TWINS: set[frozenset[str]] = set()


def _builder():
    spec = importlib.util.spec_from_file_location("build_gallery_diagrams", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _embedded() -> list[str]:
    return re.findall(r"<!--mmd:([a-z0-9-]+)-->", PAGE.read_text())


def _diagrams() -> str:
    """Only the injected SVG, never the hand-written page around it.

    The first draft of this searched the whole file, and a mutation run caught
    it: the page's own CSS comment quotes `<g class="cluster"><rect style="">`
    to explain the rule, so turning the nesting off entirely left the test green
    on a comment. A test of the page's prose is not a test of its diagrams.
    """
    return "\n".join(re.findall(r"<!--mmd:[a-z0-9-]+-->(.*?)<!--/mmd:", PAGE.read_text(), re.S))


def test_the_page_embeds_diagrams_at_all() -> None:
    # Guards every assertion below from passing vacuously.
    assert len(_embedded()) > 20


def test_an_alias_must_say_why_the_reader_needs_that_graph_twice() -> None:
    for alias, entry in _builder().ALIASES.items():
        assert isinstance(entry, tuple) and len(entry) == 2, (
            f"{alias!r} maps to a bare slug. A second rendering of a graph the page "
            f"already draws needs a written reason, not a mapping — see gallery 54."
        )
        _slug, reason = entry
        assert isinstance(reason, str) and len(reason.split()) >= 5, (
            f"{alias!r} carries no real reason for drawing its graph twice."
        )


def test_no_graph_is_drawn_twice_without_a_reason() -> None:
    builder = _builder()
    sources = builder.mermaid_sources()
    by_graph: dict[str, list[str]] = defaultdict(list)
    for key in _embedded():
        by_graph[sources[key]].append(key)

    for keys in by_graph.values():
        if len(keys) == 1:
            continue
        if frozenset(keys) in KNOWN_TWINS:
            continue
        declared = [k for k in keys if k in builder.ALIASES]
        assert len(keys) - len(declared) <= 1, (
            f"the page draws one graph under {sorted(keys)} — a reader meets the same "
            f"picture more than once. Remove the extra rendering, or declare it in "
            f"ALIASES with the reason it earns its place."
        )


def test_a_mounts_cluster_is_not_painted_black() -> None:
    page = PAGE.read_text()
    clusters = re.findall(r'<g class="cluster"[^>]*>\s*<rect([^>]*)>', _diagrams())
    assert clusters, "no opened mount on the page — the composition examples lost their nesting"
    for attrs in clusters:
        assert "fill" not in attrs, (
            "a cluster rect now carries its own fill; the shared rule below may be dead"
        )

    rule = re.search(r"\.mmd svg \.cluster rect\s*\{([^}]*)\}", page)
    assert rule, (
        "site/gallery.html strips mermaid's stylesheet and restyles diagrams in its own "
        "tokens, and has no rule for `.cluster rect`. An unstyled SVG rect is filled "
        "black, so every opened mount is a black box (gallery 68)."
    )
    assert "fill:" in rule.group(1), "the cluster rule sets no fill, which is the whole defect"


def test_a_mounts_name_is_readable() -> None:
    page = PAGE.read_text()
    assert re.search(r"\.mmd svg \.cluster-label\b", page), (
        "the cluster label is the only thing naming which mount you are looking at"
    )
