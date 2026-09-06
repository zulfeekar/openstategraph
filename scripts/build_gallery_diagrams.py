#!/usr/bin/env python3
"""Regenerate the compiled-graph diagrams embedded in ``site/gallery.html``.

    python3 scripts/build_gallery_diagrams.py [--check]

Every diagram on the gallery page is the Mermaid the **compiler actually
produced** — ``CompiledWorkflow.mermaid()`` on each package under
``backend/openstategraph/examples/``, which is ``draw_mermaid()`` with every
mount opened to any depth. Compiling needs no credentials and calls no model, so
this script is free to run.

An example is refused if it compiles with a warning it did not **declare**
(``expectedFindings`` in ``examples/index.json``), and equally if it declares
one it no longer produces. Not "no warnings at all": ``Finding`` exists to say
a graph is legal and less capable than it looks, and ``support-triage`` used to
ship one on purpose — until ``workflow-gallery`` 78 wired its ``revise`` edge,
no example in the gallery currently declares one, but the mechanism stays: under
the old "no warnings" rule this script exited 1 on a clean checkout and the
committed diagrams went stale (``workflow-gallery`` 55). The same comparison
runs in ``backend/tests/test_example_warnings_are_declared.py``, so a new
warning in a broken example fails a suite and not only this script.

Every box carries the **title its author gave the node**, not the id the
compiler used. That is the same relabelling ``workflow-gallery`` 56 wrote for a
customer's preview (``api/customer_graph.py``), reached through the same seam,
because a reader of this page is that reader: ``draft1`` is the compiler's word
and *Draft* is the author's. It is also what stops two different examples from
being one picture — ``evaluator-optimizer`` and ``budget-exhaustion`` compile to
byte-identical Mermaid and their authors had already told them apart
(``workflow-gallery`` 69). Where a node has no title its id survives, because
inventing a friendly name is the lie 56 refused.

``CompiledWorkflow.mermaid()`` itself is unchanged: a developer asking the
compiler what it built still gets ``__start__`` and every id, which is
``workflow-gallery`` 62's deliberate behaviour and the vocabulary a mount bug is
reported under.

``draw_mermaid()``, never ``draw_mermaid_png()``: the PNG helper posts the graph
to the Mermaid.Ink API, and we do not send a user's graph to a third party. The
same rule is why the rendering below happens on this machine, against the
mermaid build this repository already vendors, rather than against a CDN — the
published page must make no external request at all.

The page itself is hand-written (there is no site generator, deliberately). This
script only rewrites the regions marked

    <!--mmd:SLUG--> … <!--/mmd:SLUG-->

leaving every word of prose alone.

``--check`` asks whether every committed picture is still **the graph the
compiler builds** — it compiles, and reads the committed SVG, and compares the
two through ``scripts/diagram_gate.py``. It does **not** re-render: until
``workflow-gallery`` 80 it compared the rendered bytes, which is a comparison
no two machines can pass, because mermaid lays a flowchart out from the
browser's own font metrics and CI has no Inter installed. That module carries
the measurements. The consequence worth knowing here: ``--check`` needs neither
node nor a browser, so the CI job installs neither.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from diagram_gate import drift  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "backend" / "openstategraph" / "examples"
PAGE = REPO / "site" / "gallery.html"
RENDERER = REPO / "scripts" / "render_mermaid.mjs"

# The sentinel colours scripts/render_mermaid.mjs feeds mermaid, plus the two
# fills LangGraph writes into the diagram source itself, mapped onto the site's
# shadcn-zinc tokens. Going through CSS custom properties is what keeps a
# build-time SVG following the reader's light/dark theme.
COLOUR_MAP = {
    "#fe0001": "transparent",
    "#fe0002": "hsl(var(--card))",
    "#fe0003": "hsl(var(--border))",
    "#fe0004": "hsl(var(--foreground))",
    "#fe0005": "hsl(var(--muted-foreground))",
    "#f2f0ff": "hsl(var(--muted))",  # LangGraph's `classDef default`
    "#bfb6fc": "hsl(var(--accent))",  # LangGraph's `classDef last`
}

# Attributes mermaid emits for its own re-layout machinery. A static page never
# reads them, and `data-points` alone is a base64 blob per edge.
NOISE_ATTRS = re.compile(r'\s(?:data-points|data-look|data-edge|data-et|data-id)="[^"]*"')

# A second rendering of a graph the page already draws under another name, so
# its element ids stay unique in the document: alias -> (slug, why a reader
# needs this picture twice).
#
# **Empty on purpose.** It used to hold four entries, and they were a workaround:
# a mount rendered as one featureless box, because `xray=True` opens a LangGraph
# subgraph and the parent holds a *closure* over the child, so drawing the child
# again beside its parent was the only way to show what was inside. Gallery 28
# taught `CompiledWorkflow.mermaid()` to splice the child in to any depth, and
# gallery 54 took the four to the rendered page one at a time. All four lost the
# same argument: the parent already draws that graph, the child is also its own
# numbered example further down, and the third copy was costing the parent the
# width it needed to be legible.
#
# The rule that survives is not "no aliases" — a flat, unnested look at a child
# is a legitimate second view. It is that the reason has to be *written down*
# here, where the next person deciding will read it, rather than inferred from a
# mapping. `backend/tests/test_gallery_draws_each_graph_once.py` refuses an entry
# that carries no reason, and refuses an undeclared duplicate.
ALIASES: dict[str, tuple[str, str]] = {}


def slugs() -> list[str]:
    index = json.loads((EXAMPLES / "index.json").read_text())
    return [entry["slug"] for entry in index["examples"]]


def as_the_author_named_it(text: str, document, mounts) -> str:
    """One diagram in the vocabulary of the person who drew it.

    A thin, named wrapper over ``api/customer_graph.customer_mermaid`` so the
    page reaches the relabelling through the seam that already exists rather
    than growing a second one — the rule that a diagram is rewritten in exactly
    one place is worth more here than the two saved lines. ``mounts`` maps a
    mount's graph node name to the child's own document, so a node three levels
    down is named by *its* author (a title map keyed by bare id would answer the
    parent's word for the three different ``in1``s in ``nested-mounts``).

    Imported inside the function for the same reason ``mermaid_sources`` does:
    ``--help`` must work without the backend installed.
    """
    from openstategraph.api.customer_graph import customer_mermaid  # noqa: PLC0415

    return customer_mermaid(text, document, mounts)


def mermaid_sources() -> dict[str, str]:
    """Compile every example and return its Mermaid text, named by its author.

    Imported here rather than at module scope so ``--help`` works without the
    backend installed.
    """
    sys.path.insert(0, str(REPO / "backend"))
    from openstategraph import load_workflow  # noqa: PLC0415
    from openstategraph.api.diagram import mounted_documents  # noqa: PLC0415
    from openstategraph.api.workflow_store import WorkflowStore  # noqa: PLC0415

    from openstategraph.examples import get, warning_drift  # noqa: PLC0415

    # An example's mounts resolve to sibling packages under `examples/`, so the
    # store the labeller loads child documents from is rooted there and reaches
    # nothing of this developer's own `workflows/` tree.
    store = WorkflowStore(EXAMPLES)

    sources: dict[str, str] = {}
    for slug in slugs():
        workflow = load_workflow(EXAMPLES / slug)
        undeclared, absent = warning_drift(get(slug), workflow.warnings)
        if undeclared:
            raise SystemExit(f"{slug} compiled with a warning it never declared: {undeclared}")
        if absent:
            raise SystemExit(f"{slug} declares a finding it no longer produces: {absent}")
        # `_mounts` is what the compiler recorded while it built each child, and
        # it is what `mermaid()` itself expands from; the labeller needs the same
        # map to join each mount to the document that names its nodes.
        mounts = mounted_documents(getattr(workflow, "_mounts", {}), store)
        sources[slug] = as_the_author_named_it(workflow.mermaid(), workflow.document, mounts)
    for alias, (slug, _reason) in ALIASES.items():
        sources[alias] = sources[slug]
    return sources


def render(sources: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(  # noqa: S603
        ["node", str(RENDERER)],
        input=json.dumps(sources),
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"mermaid renderer failed:\n{result.stderr}")
    return json.loads(result.stdout)


def tidy(svg: str) -> str:
    """Strip what a static, theme-aware page does not need from mermaid's SVG.

    Mermaid scopes a ~9 KB stylesheet by element id into every diagram. One copy
    per diagram is most of the page, so it is dropped for one shared block in
    the page's own CSS (`.mmd svg …`), which is also what lets the tokens above
    do their work.
    """
    svg = re.sub(r"<style>.*?</style>", "", svg, flags=re.DOTALL)
    # Only the arrowhead is ever referenced; mermaid defines twelve markers.
    used = set(re.findall(r"url\(#([^)]+)\)", svg))
    svg = re.sub(
        r'<marker id="([^"]+)".*?</marker>',
        lambda m: m.group(0) if m.group(1) in used else "",
        svg,
        flags=re.DOTALL,
    )
    svg = NOISE_ATTRS.sub("", svg)
    svg = svg.replace(' style=";"', "")
    for sentinel, token in COLOUR_MAP.items():
        svg = svg.replace(sentinel, token)
    # Width is the page's business, not the diagram's.
    svg = re.sub(r'\sstyle="max-width:[^"]*"', "", svg, count=1)
    svg = svg.replace('<svg ', '<svg role="img" ', 1)
    return svg.strip()


def regions(page: str) -> dict[str, str]:
    """What the page currently draws, by slug — the committed SVG of each."""
    return {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"<!--mmd:([a-z0-9-]+)-->(.*?)<!--/mmd:\1-->", page, flags=re.DOTALL
        )
    }


def reconcile(page: str, produced: set[str]) -> set[str]:
    wanted = set(re.findall(r"<!--mmd:([a-z0-9-]+)-->", page))
    missing = wanted - produced
    if missing:
        raise SystemExit(f"page asks for diagrams that no example produces: {sorted(missing)}")
    unused = produced - wanted
    if unused:
        print(f"note: no placeholder on the page for {sorted(unused)}", file=sys.stderr)
    return wanted


def check(sources: dict[str, str], page: str) -> int:
    """Is every committed picture still the graph the compiler builds?

    Compiling only — no node, no chromium, no font. See ``diagram_gate`` for
    why the bytes are not what is compared.
    """
    wanted = reconcile(page, set(sources))
    drawn = regions(page)
    complaints: list[str] = []
    for slug in sorted(wanted):
        if slug not in drawn:
            complaints.append(f"{slug}: the page opens a diagram region it never closes")
            continue
        complaints.extend(drift(slug, sources[slug], drawn[slug]))
    if complaints:
        print("\n".join(complaints), file=sys.stderr)
        print(
            "site/gallery.html no longer draws the graphs it claims to — "
            "run python3 scripts/build_gallery_diagrams.py",
            file=sys.stderr,
        )
        return 1
    print(f"{PAGE.relative_to(REPO)} draws the live graph ({len(wanted)} diagrams)")
    return 0


def inject(page: str, svgs: dict[str, str]) -> str:
    wanted = reconcile(page, set(svgs))

    for slug, svg in svgs.items():
        if slug not in wanted:
            continue
        page = re.sub(
            f"(<!--mmd:{slug}-->).*?(<!--/mmd:{slug}-->)",
            lambda m, svg=svg: m.group(1) + svg + m.group(2),
            page,
            flags=re.DOTALL,
        )
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed page differs from a fresh render",
    )
    args = parser.parse_args()

    sources = mermaid_sources()
    before = PAGE.read_text()

    if args.check:
        return check(sources, before)

    svgs = {slug: tidy(svg) for slug, svg in render(sources).items()}
    after = inject(before, svgs)
    PAGE.write_text(after)
    print(f"wrote {len(svgs)} diagrams into {PAGE.relative_to(REPO)} ({len(after):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
