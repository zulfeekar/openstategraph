"""`docs/modules.md`, held against the vocabulary it claims to index.

`docs-onramp/04`. The briefs for this product's built-in modules have existed
and been maintained for months — `backend/openstategraph/compile/port_specs.json`
carries **43** node types and every one of them has a `label` and a
`description`. What did not exist was a *page*: on 2026-09-05, thirteen of the
forty-three were named — by type id *or* display label — in no file under
`docs/`, and thirty were named in neither form in `docs/on-the-canvas.md`, the
page `docs/README.md` routes a reader to for *"understand what I am drawing"*.
The only complete list a stranger could reach was `openstategraph nodes`, a CLI
verb they have to already know to run.

So the page is **generated**, not typed, and this file is why that is not merely
a preference. A hand-kept second copy of forty-three descriptions is the
duplication rule broken (`CLAUDE.md` §DRY: node configuration is declared once
and everything derives from it), and it would be stale within the week — the
vocabulary moved by four types in the month before the page existed.

## What this pins

One assertion does the work the ticket asks for in three parts, because all
three are the same defect and a byte comparison catches all three:

- a type in `port_specs.json` with **no row** on the page;
- a row naming a type that **no longer exists**;
- a description on the page that **disagrees** with the one in the data.

The counts are pinned the same way, and deliberately not restated here: the
generator prints them from the data it just read, so the page's own
"agent 10 · tools 22 · …" line has no way to drift from the file it came from.
A number in prose has no way to fail; a number a generator emits does.

**What is not pinned** is the prose. The per-family paragraphs are an author's
words and live in the generator beside the table they introduce. A test
demanding particular sentences would be a test of the wording rather than of
the software — the rule `test_documented_cli_surface.py` states and this file
follows.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "modules.md"
SCRIPT = REPO / "scripts" / "build_module_index.py"


def _generator():
    spec = importlib.util.spec_from_file_location("build_module_index", SCRIPT)
    assert spec and spec.loader, SCRIPT
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_module_index_page_exists() -> None:
    assert PAGE.exists(), (
        "docs/modules.md is the only complete list of this install's built-in "
        "modules a reader can reach without knowing a CLI verb (docs-onramp/04)"
    )
    assert SCRIPT.exists(), "the page is generated, never typed — docs-onramp/04"


def test_documented_modules_match_the_vocabulary() -> None:
    """The committed page is byte-for-byte what the vocabulary renders to."""
    generator = _generator()
    rendered = generator.render()
    committed = PAGE.read_text(encoding="utf-8")
    if rendered != committed:
        pytest.fail(
            "docs/modules.md disagrees with the vocabulary it indexes — a node "
            "type was added, removed or re-described and the page did not "
            "follow. Run: python3 scripts/build_module_index.py --write\n"
            + generator.first_difference(committed, rendered)
        )


def test_every_type_in_the_data_has_a_row() -> None:
    """Stated separately from the byte check so the failure names the type.

    The byte comparison above catches this, and reports it as "these two
    documents differ" — which is the row nobody opens (`CLAUDE.md`). This one
    prints the id.
    """
    generator = _generator()
    page = PAGE.read_text(encoding="utf-8")
    missing = [n["type"] for n in generator.node_types() if f"`{n['type']}`" not in page]
    assert not missing, f"named in no row of docs/modules.md: {missing}"


def test_every_deeper_link_points_at_a_page_that_exists() -> None:
    """The link table is the one hand-written thing here, so it is checked."""
    generator = _generator()
    dangling = [
        target
        for target in generator.deeper_link_targets()
        if not (REPO / "docs" / target).exists()
    ]
    assert not dangling, f"docs/modules.md would link nothing: {dangling}"


def _prose(page: pathlib.Path) -> str:
    """The page with every fenced block removed.

    `docs-onramp/11`. Grep is the wrong instrument for *"does this page tell
    a reader anything about this module"*, and the row that proved it is
    `tool.platform-read-file`: `docs/mcp.md` carried its type id inside a
    comment in an example document, enumerating ids the model may use. The id
    was on the page and nothing on the page said what the tool reads or where
    its jail root is. A fenced block is example input and output; prose is the
    only part written *to* the reader, so it is the only part that counts as
    naming.
    """
    kept, fenced = [], False
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            kept.append(line)
    return "\n".join(kept)


def test_every_deeper_link_lands_on_a_page_that_names_the_module() -> None:
    """A "Read more" is a promise, and the second half of `docs-onramp/04`.

    Measured on the second fresh-user walk (`docs-onramp/00b`): 31 of the 43
    rows linked to a page that names the module in neither form outside a
    code block, and three of the five targets were written for a different
    reader entirely — `declaring-a-table.md` opens *"for whoever owns a data
    source"* and eight rows about running a query pointed at it.

    The property, not the list: a row either links to a page that names its
    module, or it carries no link at all. `openstategraph nodes <type>` is an
    honest cell — it prints the fields and the ports, and it is never stale.
    A link to the wrong reader's page is not.
    """
    generator = _generator()
    misrouted = []
    for node in generator.node_types():
        cell = generator.deeper_for(node["type"])
        match = re.fullmatch(r"\[.+\]\((.+)\)", cell)
        if not match:
            continue
        target = REPO / "docs" / match.group(1)
        assert target.exists(), f"{node['type']} links to a missing {match.group(1)}"
        prose = _prose(target)
        if node["type"] not in prose and node["label"] not in prose:
            misrouted.append(f"{node['type']} ({node['label']}) → {match.group(1)}")
    assert not misrouted, (
        "docs/modules.md sends a reader to a page that never names the module "
        "they clicked — re-route the row in DEEPER, unlink it, or add the "
        "sentence to the target page:\n  " + "\n  ".join(misrouted)
    )
