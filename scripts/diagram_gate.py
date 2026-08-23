#!/usr/bin/env python3
"""What a committed Mermaid SVG must still say about the graph it was drawn from.

`site/gallery.html` and `site/behind-the-scenes.html` carry inline SVG that
`scripts/render_mermaid.mjs` rendered from `draw_mermaid()` output. Both pages
ship a drift gate — *is this picture still the graph the compiler builds?* —
and until `workflow-gallery` 80 both answered it by comparing the rendered
**bytes**.

**That comparison cannot be satisfied on two machines, and the evidence is
measurable.** Mermaid lays a flowchart out by asking the browser how wide each
label is, so every coordinate in the SVG is a font metric. Rendering one small
graph through the repo's own renderer with three font stacks gives three
different diagrams:

    Inter, ui-sans-serif, system-ui, sans-serif  ->  viewBox 0 0 87.62572 219
    DejaVu Sans, sans-serif                      ->  viewBox 0 0 89.61010 219
    Courier New, monospace                       ->  viewBox 0 0 106.86010 219

and `measureText("Draft")` in the same chromium reports 33.31px for `Inter`
against 29.54px for a font that is not installed. Inter *is* installed on the
developer machine this page was last built on and is *not* installed on a fresh
ubuntu CI runner, so the two render the same graph into different bytes. CI run
32659487566 is that failure: `--check` exit 1 in CI, exit 0 locally, off the
same commit, with the artefact freshly and correctly regenerated the session
before (`workflow-gallery` 79, `0b69884`).

Pinning the font was priced and rejected: a font file can be vendored, but text
*measurement* also differs between CoreText and FreeType for the same file, and
a pin whose correctness cannot be checked from the machine doing the pinning is
the disease rather than the cure.

So the gate compares what this repository actually produces — **the graph** —
and lets geometry be geometry. A `DiagramShape` is everything a reader of the
page is being told: which boxes, what they are called, how many arrows, and
what the labelled ones say. It is recoverable from the Mermaid source and from
the rendered SVG, and it is invariant under every font, chromium and mermaid
layout change.

What this deliberately does **not** catch, said out loud rather than implied:
a change to `tidy()`, to the colour sentinels, or to mermaid's own markup that
leaves the graph alone. Those move pixels, not meaning, and a gate that fails
on them is the gate this replaces.

`shape_of_svg` fails closed: a fragment that is not an SVG, or an SVG this
parser cannot read, raises rather than comparing empty against empty.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

#: A node declaration: `\tdraft1(Draft)`, `\ta__start__([<p>__start__</p>]):::first`.
_NODE = re.compile(r"^\s*([^\s()\[\]]+)\((.*)\)(?::::\w+)?\s*$")
#: `subgraph mount_mid["Nested Mounts (middle)"]`
_SUBGRAPH = re.compile(r'^\s*subgraph\s+\S+\["(.*)"\]\s*$')
#: A dotted edge, labelled (`grader1 -. &nbsp;revise&nbsp; .-> draft1;`) or not
#: (`lead1 -.-> worker1;`, which is what `Send` fan-out draws).
_DOTTED = re.compile(r"^\s*(\S+)\s+-\.\s*(?:(.*?)\s*\.)?->\s*(\S+);?\s*$")
#: A solid edge, with or without `-- label -->` / `-->|label|`.
_SOLID = re.compile(r"^\s*(\S+)\s*--(?:\s*(.*?)\s*--)?>\s*(?:\|(.*?)\|\s*)?(\S+);?\s*$")

#: Anything on a line that means "this is not a graph statement".
_IGNORED = re.compile(r"^\s*(?:---|config:|\s+\w+:|graph\b|flowchart\b|classDef\b|class\b|end\s*$|style\b|linkStyle\b)")

_NODE_LABEL = re.compile(r'<span[^>]*\bclass="nodeLabel"[^>]*>(.*?)</span>', re.DOTALL)
_EDGE_LABEL = re.compile(r'<span[^>]*\bclass="edgeLabel"[^>]*>(.*?)</span>', re.DOTALL)
_LINK = re.compile(r"\bflowchart-link\b")


def normalise(label: str) -> str:
    """One spelling for a label, whether it came from Mermaid or from SVG.

    The two carry the same text with different decoration: the source writes
    `&nbsp;revise&nbsp;` bare, the render wraps it in `<p>`. Tags out, entities
    resolved, whitespace collapsed — including the non-breaking space, which is
    a space to every reader of the page and is the only thing distinguishing
    the two spellings of every conditional edge label.
    """
    text = re.sub(r"<[^>]+>", "", label)
    text = html.unescape(text).replace("\xa0", " ")
    return " ".join(text.split())


@dataclass(frozen=True)
class DiagramShape:
    """The graph a diagram shows, with every pixel of it thrown away."""

    labels: tuple[str, ...]
    edges: int
    edge_labels: tuple[str, ...]


class UnreadableDiagram(ValueError):
    """The gate could not read a diagram, which is a failure and not a pass."""


def shape_of_source(mermaid: str) -> DiagramShape:
    labels: list[str] = []
    edge_labels: list[str] = []
    edges = 0
    for line in mermaid.splitlines():
        if not line.strip() or _IGNORED.match(line):
            continue
        subgraph = _SUBGRAPH.match(line)
        if subgraph:
            labels.append(normalise(subgraph.group(1)))
            continue
        dotted = _DOTTED.match(line)
        if dotted:
            edges += 1
            text = normalise(dotted.group(2) or "")
            if text:
                edge_labels.append(text)
            continue
        solid = _SOLID.match(line)
        if solid:
            edges += 1
            text = normalise(solid.group(2) or solid.group(3) or "")
            if text:
                edge_labels.append(text)
            continue
        node = _NODE.match(line)
        if node:
            inner = node.group(2)
            # Stadium/round/hexagon variants wrap the label again: `([x])`, `[x]`.
            inner = re.sub(r"^[\[({>\\/]+", "", inner)
            inner = re.sub(r"[\])}\\/]+$", "", inner)
            labels.append(normalise(inner))
            continue
        raise UnreadableDiagram(f"mermaid line this gate cannot classify: {line!r}")
    if not labels:
        raise UnreadableDiagram("mermaid source declares no nodes")
    return DiagramShape(tuple(sorted(labels)), edges, tuple(sorted(edge_labels)))


def shape_of_svg(svg: str) -> DiagramShape:
    if "<svg" not in svg:
        raise UnreadableDiagram("diagram region holds no <svg> element")
    labels = [normalise(text) for text in _NODE_LABEL.findall(svg)]
    if not labels:
        raise UnreadableDiagram("rendered diagram carries no node labels")
    edge_labels = [normalise(text) for text in _EDGE_LABEL.findall(svg)]
    return DiagramShape(
        tuple(sorted(labels)),
        len(_LINK.findall(svg)),
        tuple(sorted(text for text in edge_labels if text)),
    )


def drift(name: str, mermaid: str, svg: str) -> list[str]:
    """Everything the committed picture no longer says about the live graph."""
    want = shape_of_source(mermaid)
    got = shape_of_svg(svg)
    if want == got:
        return []
    complaints = [f"{name}: the committed diagram is not the graph the compiler builds"]
    if want.labels != got.labels:
        missing = sorted(set(want.labels) - set(got.labels))
        extra = sorted(set(got.labels) - set(want.labels))
        complaints.append(f"  boxes: missing {missing or '-'}, stale {extra or '-'}")
    if want.edges != got.edges:
        complaints.append(f"  arrows: the graph has {want.edges}, the picture draws {got.edges}")
    if want.edge_labels != got.edge_labels:
        complaints.append(
            f"  arrow labels: the graph says {list(want.edge_labels)}, "
            f"the picture says {list(got.edge_labels)}"
        )
    return complaints
