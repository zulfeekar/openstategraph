#!/usr/bin/env python3
"""Regenerate the compiled-graph diagrams embedded in ``site/gallery.html``.

    python3 scripts/build_gallery_diagrams.py [--check]

Every diagram on the gallery page is the Mermaid the **compiler actually
produced** — ``compiled.get_graph(xray=True).draw_mermaid()`` on each package
(``xray`` expands nothing here; see the note on ``ALIASES`` below)
under ``backend/openstategraph/examples/``. Compiling needs no credentials and
calls no model, so this script is free to run.

``draw_mermaid()``, never ``draw_mermaid_png()``: the PNG helper posts the graph
to the Mermaid.Ink API, and we do not send a user's graph to a third party. The
same rule is why the rendering below happens on this machine, against the
mermaid build this repository already vendors, rather than against a CDN — the
published page must make no external request at all.

The page itself is hand-written (there is no site generator, deliberately). This
script only rewrites the regions marked

    <!--mmd:SLUG--> … <!--/mmd:SLUG-->

leaving every word of prose alone. ``--check`` re-renders and fails if the
committed page is out of date instead of writing it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

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

# The three composition examples show their children beside them, because a mount
# renders as one featureless box and `xray=True` cannot open it — the parent holds
# a closure over the child, not a LangGraph subgraph. A child therefore appears on
# the page more than once, and each appearance is rendered separately so its
# element ids stay unique in the document.
ALIASES = {
    "chained-summarizer-l3": "chained-summarizer",  # 11, level 3
    "chained-summarizer-x2": "chained-summarizer",  # 12, both mounts
    "sql-qa-mounted": "sql-qa",  # 13, the `database` branch
    "web-research-digest-mounted": "web-research-digest",  # 13, the `web` branch
}


def slugs() -> list[str]:
    index = json.loads((EXAMPLES / "index.json").read_text())
    return [entry["slug"] for entry in index["examples"]]


def mermaid_sources() -> dict[str, str]:
    """Compile every example and return its Mermaid text.

    Imported here rather than at module scope so ``--help`` works without the
    backend installed.
    """
    sys.path.insert(0, str(REPO / "backend"))
    from openstategraph import load_workflow  # noqa: PLC0415

    sources: dict[str, str] = {}
    for slug in slugs():
        workflow = load_workflow(EXAMPLES / slug)
        if workflow.warnings:
            raise SystemExit(f"{slug} compiled with warnings: {workflow.warnings}")
        sources[slug] = workflow.graph.get_graph(xray=True).draw_mermaid()
    for alias, slug in ALIASES.items():
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

    Mermaid scopes a ~9 KB stylesheet by element id into every diagram. Twenty-one
    copies of it is most of the page, so it is dropped for one shared block in
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


def inject(page: str, svgs: dict[str, str]) -> str:
    wanted = set(re.findall(r"<!--mmd:([a-z0-9-]+)-->", page))
    missing = wanted - set(svgs)
    if missing:
        raise SystemExit(f"page asks for diagrams that no example produces: {sorted(missing)}")
    unused = set(svgs) - wanted
    if unused:
        print(f"note: no placeholder on the page for {sorted(unused)}", file=sys.stderr)

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

    svgs = {slug: tidy(svg) for slug, svg in render(mermaid_sources()).items()}
    before = PAGE.read_text()
    after = inject(before, svgs)

    if args.check:
        if before != after:
            print(
                "site/gallery.html is out of date — "
                "run python3 scripts/build_gallery_diagrams.py",
                file=sys.stderr,
            )
            return 1
        print(f"{PAGE.relative_to(REPO)} is current ({len(svgs)} diagrams)")
        return 0

    PAGE.write_text(after)
    print(f"wrote {len(svgs)} diagrams into {PAGE.relative_to(REPO)} ({len(after):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
