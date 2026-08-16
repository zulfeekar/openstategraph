#!/usr/bin/env python3
"""Regenerate the five artifacts embedded in ``site/behind-the-scenes.html``.

    python3 scripts/build_behind_the_scenes.py [--check]

The page walks one workflow — ``evaluator-optimizer`` — through the five
artifacts `.scratch/export-and-eject/research/10-python-export.md` §Q4 settled:
the document, the plan, the compiled graph, the rendered system prompt, and the
Python that runs it. **Every one of them is taken from the real thing**, which
is the whole point of the page: a walk-through of what the compiler does, typed
by hand, is a walk-through of what someone remembers the compiler doing.

Sourced here, and nowhere else:

1. **the document** — the committed ``workflow.json``, printed verbatim;
2. **the plan** — ``ValidateWorkflowTool``, the same seam ``openstategraph
   validate`` and the MCP server both go through;
3. **the graph** — ``compiled.get_graph().draw_mermaid()``, rendered to inline
   SVG by ``scripts/render_mermaid.mjs`` on this machine (never
   ``draw_mermaid_png()``, which posts the graph to a third party);
4. **the prompt** — ``SystemPrompt.describe()`` on the objects the compiler
   builds for those two nodes.

Artifact 5 is prose plus a code block, and is hand-written: it is an
*instruction*, not an output, and `backend/tests/test_behind_the_scenes.py`
pins the names it uses against the real API instead.

**The one transcription, named.** Step 4 needs the ``Grader`` / agent objects
that ``NodeRuntime._grader`` and ``._agent`` build inside per-invocation
closures, which nothing outside a run can reach. Rather than reimplement the
mapping, this script reads the config from the real document and passes it
through the runtime's **own** ``_text`` / ``_replaces_rules`` helpers, so the
only thing restated here is which key feeds which argument — four lines, marked
below. ``openstategraph prompt`` (research item F) is what removes even that,
and when it lands this script should call it.

Like ``build_gallery_diagrams.py``, this rewrites only the regions marked

    <!--bts:NAME--> … <!--/bts:NAME-->

and leaves every word of prose alone. ``--check`` re-renders and fails if the
committed page is out of date instead of writing it.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
PACKAGE = BACKEND / "openstategraph" / "examples" / "evaluator-optimizer"
PAGE = REPO / "site" / "behind-the-scenes.html"
RENDERER = REPO / "scripts" / "render_mermaid.mjs"

#: The two prompted nodes of the subject workflow. The agent first, because the
#: page reads top to bottom and that is the order the graph runs them.
PROMPTED = ("draft1", "grader1")

# Shared with build_gallery_diagrams.py — the sentinel colours render_mermaid.mjs
# feeds mermaid, mapped onto the site's shadcn-zinc tokens so a build-time SVG
# still follows the reader's light/dark theme. Duplicated rather than imported:
# the two scripts are one import away from being one script, and the moment
# either grows a second diagram style that becomes a coupling neither wants.
COLOUR_MAP = {
    "#fe0001": "transparent",
    "#fe0002": "hsl(var(--card))",
    "#fe0003": "hsl(var(--border))",
    "#fe0004": "hsl(var(--foreground))",
    "#fe0005": "hsl(var(--muted-foreground))",
    "#f2f0ff": "hsl(var(--muted))",
    "#bfb6fc": "hsl(var(--accent))",
}

NOISE_ATTRS = re.compile(r'\s(?:data-points|data-look|data-edge|data-et|data-id)="[^"]*"')


# --- the artifacts ---------------------------------------------------------- #


def document() -> dict:
    return json.loads((PACKAGE / "workflow.json").read_text())["document"]


def plan_text() -> str:
    """What `openstategraph validate <pkg>` prints, through the same seam.

    `ValidateWorkflowTool`, never a second validator — `cli.cmd_validate` says
    why: two validators is how a document passes one gate and fails the other.
    """
    from openstategraph.prebuilt_architect import ValidateWorkflowTool
    from openstategraph.schema import normalize_document

    raw = json.loads((PACKAGE / "workflow.json").read_text())
    verdict = ValidateWorkflowTool().run(document=json.dumps(normalize_document(raw)))
    if not verdict.ok:
        raise SystemExit(f"the subject workflow does not validate: {verdict.error}")
    return str(verdict.content).strip()


def mermaid_text() -> str:
    from openstategraph import load_workflow

    workflow = load_workflow(PACKAGE)
    if workflow.warnings:
        raise SystemExit(f"the subject workflow compiled with warnings: {workflow.warnings}")
    diagram = workflow.graph.get_graph(xray=True).draw_mermaid()
    # The page states, as a fact about this project rather than as an opinion,
    # that `--xray` expands nothing today. Asserting it here is what stops that
    # sentence outliving its truth: the day an agent stops being built lazily
    # inside its closure, this build fails and the page gets rewritten.
    if workflow.graph.get_graph(xray=False).draw_mermaid() != diagram:
        raise SystemExit(
            "xray now expands something — site/behind-the-scenes.html §3 says it does not"
        )
    return str(diagram)


def prompt_sections() -> dict[str, dict]:
    """`SystemPrompt.describe()` for each prompted node, plus what it renders to.

    Its first callers. The dict is exactly what `describe()` returns, with
    `render()` and the node's title alongside — nothing is reshaped here,
    because a page showing a tidied-up version of the structure is a page about
    a structure that does not exist.
    """
    from openstategraph.abc import agent as agent_family
    from openstategraph.abc.grader import Grader
    from openstategraph.compile.node_runtime import _replaces_rules, _text

    nodes = {node["id"]: node for node in document()["nodes"]}
    out: dict[str, dict] = {}
    for node_id in PROMPTED:
        node = nodes[node_id]
        data = node.get("data") or {}
        if node["type"] == "route.grader":
            # ── the transcription, and its whole extent ──────────────────────
            # Mirrors `NodeRuntime._grader`'s `grader_for`. `skill` and `model`
            # are runtime values (a wired skill arrives through state); this
            # page is about compile time, and says so.
            built = Grader(
                criteria=_text(data, "criteria"),
                rubric=[],
                skill="",
                replace_defaults=_replaces_rules(data),
                model=None,
            )
        else:
            # Mirrors `NodeRuntime._agent`. `context` is empty for this package:
            # it has no `skills/`, no classifier upstream, and the advisor
            # catalogue is the editor's, not a run's.
            tier = agent_family.agent_node_for_tier(_text(data, "tier"))
            built = tier(
                name=f"agent_{node_id}",
                model=None,
                tools=[],
                rules=_text(data, "systemPrompt"),
                skill="",
                replace_rules=_replaces_rules(data),
                context="",
            )
        prompt = built.system_prompt()
        out[node_id] = {
            "title": node.get("title") or node_id,
            "type": node["type"],
            "built_by": type(built).__name__,
            "describe": prompt.describe(),
            "render": prompt.render(),
        }
    return out


# --- rendering to HTML ------------------------------------------------------ #


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


def json_html(value: object) -> str:
    """`json.dumps` with the site's three code colours applied.

    A tokeniser, not a parser: the input is `json.dumps` output, so a quote is a
    delimiter and nothing else, and the alternative — shipping a highlighter to
    the page — would be a network request the gallery's rule forbids.
    """
    text = json.dumps(value, indent=2)
    out: list[str] = []
    for line in text.split("\n"):
        match = re.match(r'^(\s*)"([^"]*)":\s?(.*)$', line)
        if match:
            indent, key, rest = match.groups()
            out.append(f'{indent}<span class="f">"{esc(key)}"</span>: {_json_value(rest)}')
        else:
            out.append(_json_value(line))
    return "\n".join(out)


def _json_value(fragment: str) -> str:
    def paint(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.startswith('"'):
            return f'<span class="s">{esc(token)}</span>'
        if token in ("true", "false", "null"):
            return f'<span class="k">{esc(token)}</span>'
        return f'<span class="k">{esc(token)}</span>'

    parts: list[str] = []
    last = 0
    for match in re.finditer(r'"(?:[^"\\]|\\.)*"|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?', fragment):
        parts.append(esc(fragment[last : match.start()]))
        parts.append(paint(match))
        last = match.end()
    parts.append(esc(fragment[last:]))
    return "".join(parts)


#: What each `describe()` key is, in the page's own words. The order is
#: `SystemPrompt.render()`'s order — the substance of the design — not the
#: dataclass's field order, which the type itself says is a construction
#: contract rather than a statement about prompts.
LAYERS: tuple[tuple[str, str, str], ...] = (
    ("preamble", "locked", "What this node <em>is</em>. Written by the base class."),
    ("context", "generated", "Situational detail the machinery resolves — a branch table, a rubric, a schema."),
    ("default_rules", "locked", "The domain rules this node type ships with, so it works before anyone configures it."),
    ("rules", "yours", "The one field on the card. This is the sentence you wrote."),
    ("skill", "wired", "The body of a skill file wired to the node&rsquo;s <code>skill</code> port. A rules layer, above your text."),
    ("output_contract", "locked", "The shape of the answer. Rendered <strong>last</strong>, so nothing above can countermand it."),
)


def layers_html(entry: dict) -> str:
    described = entry["describe"]
    rows: list[str] = []
    for key, kind, blurb in LAYERS:
        value = described[key]
        body = "\n\n".join(value) if isinstance(value, list) else str(value)
        empty = not body.strip()
        rows.append(
            f'<div class="layer layer--{kind}{" is-empty" if empty else ""}">'
            f'<div class="layer-bar">'
            f'<code class="layer-key">{esc(key)}</code>'
            f'<span class="layer-kind">{esc(kind)}</span>'
            f"</div>"
            f'<p class="layer-what">{blurb}</p>'
            + (
                '<p class="layer-empty">empty for this node</p>'
                if empty
                else f'<pre class="layer-body">{esc(body)}</pre>'
            )
            + "</div>"
        )
    return "\n".join(rows)


def tidy_svg(svg: str) -> str:
    """The same trim `build_gallery_diagrams.tidy` applies, and for the reasons
    documented there: mermaid inlines a ~9 KB stylesheet and twelve markers into
    every diagram, and the page carries one shared block in its own tokens."""
    svg = re.sub(r"<style>.*?</style>", "", svg, flags=re.DOTALL)
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
    svg = re.sub(r'\sstyle="max-width:[^"]*"', "", svg, count=1)
    svg = svg.replace("<svg ", '<svg role="img" ', 1)
    return svg.strip()


def render_svg(source: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["node", str(RENDERER)],
        input=json.dumps({"evaluator-optimizer": source}),
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"mermaid renderer failed:\n{result.stderr}")
    return tidy_svg(json.loads(result.stdout)["evaluator-optimizer"])


# --- assembly --------------------------------------------------------------- #


def regions() -> dict[str, str]:
    sys.path.insert(0, str(BACKEND))
    prompts = prompt_sections()
    mermaid = mermaid_text()
    blocks = {
        "document": json_html(document()),
        "plan": esc(plan_text()),
        "mermaid-src": esc(mermaid),
        "mermaid": render_svg(mermaid),
    }
    for node_id, entry in prompts.items():
        blocks[f"layers-{node_id}"] = layers_html(entry)
        blocks[f"rendered-{node_id}"] = esc(entry["render"])
        blocks[f"builder-{node_id}"] = esc(entry["built_by"])
        # The return value itself, unreshaped. `layers-*` above is the readable
        # form and reads better; this is the one that can be checked against the
        # source, and it carries the three keys the readable form drops —
        # `replace_defaults`, `effective_rules` and `editable`, which is the
        # only place the page's claim about what a developer may edit is
        # actually stated by the code rather than by the prose around it.
        blocks[f"describe-{node_id}"] = json_html(entry["describe"])
    return blocks


def inject(page: str, blocks: dict[str, str]) -> str:
    wanted = set(re.findall(r"<!--bts:([a-z0-9-]+)-->", page))
    missing = wanted - set(blocks)
    if missing:
        raise SystemExit(f"page asks for regions nothing produces: {sorted(missing)}")
    unused = set(blocks) - wanted
    if unused:
        print(f"note: no placeholder on the page for {sorted(unused)}", file=sys.stderr)

    for name, body in blocks.items():
        if name not in wanted:
            continue
        page = re.sub(
            f"(<!--bts:{name}-->).*?(<!--/bts:{name}-->)",
            lambda m, body=body: m.group(1) + body + m.group(2),
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

    blocks = regions()
    before = PAGE.read_text()
    after = inject(before, blocks)

    if args.check:
        if before != after:
            print(
                "site/behind-the-scenes.html is out of date — "
                "run python3 scripts/build_behind_the_scenes.py",
                file=sys.stderr,
            )
            return 1
        print(f"{PAGE.relative_to(REPO)} is current ({len(blocks)} regions)")
        return 0

    PAGE.write_text(after)
    print(f"wrote {len(blocks)} regions into {PAGE.relative_to(REPO)} ({len(after):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
