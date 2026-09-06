"""Every repo path an OpenWiki page links to must exist.

These pages are model-written, and the failure mode they actually have is a
link to a file that was deleted or renamed — not a paragraph of nonsense. The
2026-08-21 regeneration (production-ready 34) found exactly one:
`how-to/extending.md` pointed at `src/nodes/compose/TeamNode.ts`, a node type
schema v3 collapsed into `workflow.subgraph`. A reader following that link
learns the wiki is stale; nothing else in the repository was going to say so.

A link is checkable and a claim is not, so this pins the checkable half.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI = REPO_ROOT / "openwiki"

#: `[text](path)` — the path half only, no title, no angle brackets.
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _pages() -> list[Path]:
    return sorted(WIKI.rglob("*.md"))


def _repo_links(page: Path) -> list[str]:
    """Links that name a path in this repository.

    Skips external URLs, in-page anchors, and mailto: — none of them is a
    file this test can look for.
    """
    out = []
    for target in LINK.findall(page.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        out.append(target.split("#", 1)[0])
    return [t for t in out if t]


def test_there_are_pages_to_check() -> None:
    """A glob that silently matches nothing would make this suite green and
    empty, which is the one result it must never be able to give."""
    assert len(_pages()) >= 10


@pytest.mark.parametrize("page", _pages(), ids=lambda p: str(p.relative_to(WIKI)))
def test_every_repo_link_resolves(page: Path) -> None:
    missing = [
        target
        for target in _repo_links(page)
        if not (page.parent / target).exists()
    ]
    assert not missing, (
        f"{page.relative_to(REPO_ROOT)} links to paths that do not exist: "
        f"{missing}. The page is describing code that has moved or gone — "
        f"regenerate it with `openwiki code --update` rather than hand-editing."
    )
