#!/usr/bin/env python3
"""Put the repository's own name and its own install line on the landing page.

    python3 scripts/build_site.py [--check | --write]

`site/index.html` is the GitHub Pages landing page. Read on 2026-09-06, before
the public roll-out, it hard-coded `github.com/zulfeekar/openstategraph-beta`
in twenty-odd links — the **private** repository's name, which 404s for a
stranger and will keep 404ing under whatever name the public repository takes —
and its install section still showed `pip install -e "backend[ollama]"`, the
clone route, while the README's front door is a pinned install from TestPyPI.
Two spellings of one first step, and `test_site_pages.py` pinned the page's
structure rather than either fact, so both drifted for two weeks in silence
(stable-beta-public/34).

Two derivations, and neither of them is a copy:

1. **The repository URL is `[project.urls]`'s `Homepage`** in
   `backend/pyproject.toml`, and nothing else. This script rewrites every
   `github.com/<owner>/<repo>` on the three site pages to it — and the *other*
   `[project.urls]` entries too, which is what makes the public rename a
   one-line change followed by `--write` rather than thirty-five edits somebody
   has to find.
2. **The install block is the README's install block**, the same source
   `backend/tests/test_documented_install.py` reads, rendered into the page's
   terminal styling. So the version pin, the two index flags and the
   `--index-strategy` all move when the README moves, once.

Like `build_gallery_diagrams.py` and `build_behind_the_scenes.py`, the install
block is written into a marked region

    <!--site:NAME--> … <!--/site:NAME-->

and every word of prose is left alone. The link rewrite is not a region: the
links are spread through the whole page and marking each one would be the
hard-coding this script exists to remove.

``--check`` is the drift gate — `.github/workflows/ci.yml`'s
`gallery-diagrams-check` job runs it beside the other three, and
`test_site_pages.py` asserts the same comparison. It needs neither node, nor a
browser, nor the network.

**A known narrowness, stated rather than discovered later.** `REPO_URL` reads a
repository name as `[A-Za-z0-9_-]+`, so a repository with a dot in its name
would be matched short. Ours has none, and the alternative — a pattern that
also has to guess where `.git` ends — trades a name nobody uses for an
ambiguity on the one URL that matters, the clone line.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "backend" / "pyproject.toml"
README = ROOT / "README.md"
SITE = ROOT / "site"

#: `github.com/<owner>/<repo>`, with the clone line's `.git` kept apart so a
#: rewrite does not eat it. See the narrowness noted in the module docstring.
REPO_URL = re.compile(
    r"github\.com/(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<repo>[A-Za-z0-9][A-Za-z0-9_-]*)(?P<git>\.git)?"
)

#: The README's install command: the first fenced block after `## Install` that
#: installs this package. Anchored on the heading rather than on "the first
#: fence in the file", because the file's first fence is a Python snippet.
INSTALL_FENCE = re.compile(r"^## Install\b.*?```[a-z]*\n(?P<block>.*?)```", re.DOTALL | re.MULTILINE)


def pages() -> list[Path]:
    """The three committed pages, in the order a reader meets them."""
    return [SITE / name for name in ("index.html", "gallery.html", "behind-the-scenes.html")]


def declared_repository() -> tuple[str, str]:
    """`(owner, repo)` from `[project.urls] Homepage` — the one source."""
    urls = tomllib.loads(PYPROJECT.read_text())["project"]["urls"]
    homepage = urls.get("Homepage", "")
    found = REPO_URL.search(homepage)
    if found is None:
        raise SystemExit(
            f"[project.urls] Homepage is {homepage!r}, which names no GitHub "
            "repository — this script has nothing to derive the page's links from"
        )
    return found.group("owner"), found.group("repo")


def retarget(text: str, owner: str, repo: str) -> str:
    """Every `github.com/<o>/<r>` in `text`, pointed at this repository."""
    return REPO_URL.sub(
        lambda m: f"github.com/{owner}/{repo}" + (m.group("git") or ""),
        text,
    )


def install_block() -> str:
    """The README's install command, exactly as a reader would copy it."""
    found = INSTALL_FENCE.search(README.read_text())
    if found is None:
        raise SystemExit("README.md has no install block under `## Install`")
    return found.group("block").rstrip("\n")


def rendered_install() -> str:
    """The install block in the page's terminal styling.

    `quote=False` on purpose: the page's own install lines are what
    `test_documented_install.py` scans for `openstategraph[...]`, and an
    escaped quote would leave that gate reading a line no reader ever sees.
    """
    lines = install_block().splitlines()
    escaped = [html.escape(line, quote=False) for line in lines]
    first = f'<span class="p">$</span> {escaped[0]}'
    return "\n".join([first, *escaped[1:]])


def rendered_install_text() -> str:
    """What the rendered region says once the prompt and the escaping are undone.

    The byte-for-byte claim in `test_site_pages.py` is checked through this, so
    "the same block" means the same command and not the same markup.
    """
    return html.unescape(rendered_install()).replace('<span class="p">$</span> ', "", 1)


def inject(page: str, blocks: dict[str, str]) -> str:
    wanted = set(re.findall(r"<!--site:([a-z0-9-]+)-->", page))
    missing = wanted - set(blocks)
    if missing:
        raise SystemExit(f"page asks for regions nothing produces: {sorted(missing)}")
    for name, body in blocks.items():
        if name not in wanted:
            continue
        page = re.sub(
            f"(<!--site:{name}-->).*?(<!--/site:{name}-->)",
            lambda m, body=body: m.group(1) + body + m.group(2),
            page,
            flags=re.DOTALL,
        )
    return page


def rendered(path: Path, owner: str, repo: str) -> str:
    """What `path` should contain, from the sources named at the top."""
    text = retarget(path.read_text(), owner, repo)
    return inject(text, {"install": rendered_install()})


def rendered_pyproject(owner: str, repo: str) -> str:
    """`[project.urls]`, with every entry pointed at `Homepage`'s repository.

    The table stays four literal keys — PyPI reads them out of the built
    metadata and cannot interpolate — but only one of them is a decision.
    """
    text = PYPROJECT.read_text()
    start = text.index("[project.urls]")
    end = text.find("\n[", start + 1)
    end = len(text) if end == -1 else end
    return text[:start] + retarget(text[start:end], owner, repo) + text[end:]


def check() -> int:
    owner, repo = declared_repository()
    stale = [path.name for path in pages() if path.read_text() != rendered(path, owner, repo)]
    if PYPROJECT.read_text() != rendered_pyproject(owner, repo):
        stale.append("backend/pyproject.toml")
    if stale:
        print(
            f"these no longer agree with [project.urls] Homepage or the README's "
            f"install block: {', '.join(stale)}\n"
            "run python3 scripts/build_site.py --write",
            file=sys.stderr,
        )
        return 1
    print(f"site/ is current — {len(pages())} pages on github.com/{owner}/{repo}")
    return 0


def write() -> int:
    owner, repo = declared_repository()
    touched = []
    for path in pages():
        after = rendered(path, owner, repo)
        if after != path.read_text():
            path.write_text(after)
            touched.append(path.name)
    after = rendered_pyproject(owner, repo)
    if after != PYPROJECT.read_text():
        PYPROJECT.write_text(after)
        touched.append("backend/pyproject.toml")
    print(f"github.com/{owner}/{repo}: " + (", ".join(touched) if touched else "nothing to do"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the pages are stale")
    parser.add_argument("--write", action="store_true", help="rewrite the pages (the default)")
    args = parser.parse_args()
    return check() if args.check else write()


if __name__ == "__main__":
    raise SystemExit(main())
