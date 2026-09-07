"""Four ways to start this stack, and every page presented its own as *the* way.

`docs-onramp/06`. Counted across the entry documents on 2026-09-05:

| Path | Where | For whom |
| --- | --- | --- |
| `uv tool install …` → `init .` → `openstategraph .` | `README.md` | the stranger — the only one that works from nothing |
| `pip install "openstategraph[…]"` into an existing service | `backend/README.md`, `docs/adding-…`, `docs/adoption.md` | the developer |
| `git clone` → `npm install` → `./start dev` | `docs/getting-started.md` | the contributor |
| `npm install && npm run dev` + a second terminal | `CONTRIBUTING.md`, `openwiki/quickstart.md` | the contributor, spelled differently |

Four right instructions with no label saying who each belongs to. The sharpest
instance: **`docs/getting-started.md` — the page a stranger opens on that title
alone — opened with "You cloned the repository."** The best-named page in the
set was addressed to the reader least likely to have arrived at it, and the
stranger's path was a block-quote aside inside it.

So each entry document declares its reader **before its first command**, in one
line, in a fixed shape this file can read.

## Why a fixed marker rather than "the first paragraph mentions a reader"

Because the failure being prevented is a page that reads *plausibly* to
everybody. `docs/getting-started.md` said "You cloned the repository" in its
second line and still misrouted people, because a sentence about the reader and
a *declaration* of the reader are different things — the first is prose the eye
skims, the second is a labelled row. A test that accepted any mention would
have passed over the defect.

`docs/README.md` is the recorded exception and the exception is structural: it
is the router, not a path. Its whole content is one row per reader, so a single
audience line would be a claim it exists to contradict.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: The declaration, immediately under the page's `# ` title.
MARKER = "> **Who this page is for:**"

#: The four readers, and the clause each page uses to name itself. The clause
#: is the assertion: a page may word the rest of its line as it likes, but the
#: reader it claims has to be one of these four, spelled one way.
READERS = {
    "stranger": "you have installed nothing yet",
    "developer": "you are adding OpenStateGraph to a project you already have",
    "contributor": "you cloned this repository",
    "agent": "you are a coding agent",
}

#: Every document that hands somebody a spin-up path. `docs/README.md` is
#: excluded on the argument in this module's docstring.
ENTRY_DOCS = {
    "README.md": "stranger",
    "backend/README.md": "developer",
    "CONTRIBUTING.md": "contributor",
    "docs/getting-started.md": "contributor",
    "docs/adoption.md": "developer",
    "docs/adding-openstategraph-to-your-project.md": "developer",
}

#: How far into a page the declaration may sit. Far enough to clear a title,
#: badges and a blank line; not far enough to sit under a heading.
DECLARED_BY_LINE = 12

#: A pasteable `pip install` of a package that answers 404 today. Each has to
#: carry a hedge on its own line or the one after it — this is not prose, it is
#: a command somebody copies.
#: A pasteable `pip install openstategraph[...]` with **no version**.
#: `stable-beta-public/37` narrowed this from "any bare pip install": until
#: `0.3.0rc18` the package was on no index a reader could reach, so every such
#: line 404'd and every one of them needed a hedge. It is on PyPI now, and a
#: *pinned* line resolves — what still does not is an unpinned one, because
#: pip excludes pre-releases from an unpinned requirement and reports the
#: result as a package it cannot find rather than a candidate it skipped.
UNPINNED_PIP = re.compile(r'^\s*pip install [\'"]?openstategraph\[[a-z0-9,\-]+\][\'"]?\s*(?:#.*)?$')
HEDGES = (
    "once published",
    "after the first release",
    "does not work yet",
    "not on PyPI",
    "final release",
)


def read(relative: str) -> list[str]:
    return (REPO / relative).read_text(encoding="utf-8").splitlines()


def test_the_pages_were_actually_found() -> None:
    """A sweep over nothing passes."""
    assert all((REPO / page).is_file() for page in ENTRY_DOCS)
    assert len(set(ENTRY_DOCS.values())) >= 3, "the taxonomy collapsed to one reader"


class TestEveryEntryDocumentDeclaresItsReader:
    def test_each_one_carries_the_marker_near_the_top(self) -> None:
        missing = [
            page
            for page in ENTRY_DOCS
            if not any(line.startswith(MARKER) for line in read(page)[:DECLARED_BY_LINE])
        ]
        assert missing == [], (
            f"these pages hand a reader a spin-up path without saying whose it is, "
            f"in the first {DECLARED_BY_LINE} lines: {missing}. The line is "
            f"{MARKER!r} plus one of {sorted(READERS.values())}."
        )

    def test_each_one_names_the_reader_it_is_written_for(self) -> None:
        wrong = {}
        for page, reader in ENTRY_DOCS.items():
            head = "\n".join(read(page)[:DECLARED_BY_LINE])
            if READERS[reader] not in head:
                wrong[page] = reader
        assert wrong == {}, (
            "these pages carry an audience line that does not name the reader "
            f"this taxonomy says they are for: {wrong}"
        )

    def test_no_page_claims_two_readers(self) -> None:
        """A page for everybody is the defect, not the fix."""
        overloaded = {}
        for page in ENTRY_DOCS:
            head = "\n".join(read(page)[:DECLARED_BY_LINE])
            claimed = sorted(name for name, clause in READERS.items() if clause in head)
            if len(claimed) > 1:
                overloaded[page] = claimed
        assert overloaded == {}, f"these pages declare more than one reader: {overloaded}"


class TestTheClonePhraseStaysWithTheCloneReader:
    def test_only_a_contributor_page_says_you_cloned_the_repository(self) -> None:
        """The one measured misroute, pinned so it cannot come back.

        `docs/getting-started.md` opened on this sentence while being the page
        a stranger opens on its title. It is still the right sentence there —
        it is now under a line that says the page is the contributor's.
        """
        offenders = []
        for page, reader in ENTRY_DOCS.items():
            if reader == "contributor":
                continue
            for number, line in enumerate(read(page), start=1):
                if "You cloned the repository" in line or "you cloned the repository" in line:
                    offenders.append(f"{page}:{number}")
        assert offenders == [], (
            "a page not written for the contributor opens on the contributor's "
            f"premise: {offenders}"
        )


class TestACommandThatAnswers404IsNeverUnhedged:
    def test_every_unpinned_pip_install_carries_a_hedge(self) -> None:
        """A pasteable line that resolves to nothing must say so.

        The reason moved with the facts (`stable-beta-public/37`). It used to
        be that `openstategraph` was not on PyPI at all, so every pasteable
        `pip install openstategraph[...]` returned a 404 that reads like the
        reader's typo. `0.3.0rc18` is published, and a line naming the version
        works — but an *unpinned* one still resolves to nothing while every
        published version is a release candidate, and pip reports that
        identically. The pages that show the unpinned shape show it because it
        is the shape the command takes once a final release exists, which is
        exactly what the hedge has to say.
        """
        offenders = []
        for page in sorted(REPO.glob("docs/*.md")) + [
            REPO / "README.md",
            REPO / "backend" / "README.md",
            REPO / "CONTRIBUTING.md",
        ]:
            lines = page.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines):
                if not UNPINNED_PIP.match(line):
                    continue
                window = "\n".join(lines[max(0, number - 1) : number + 6])
                if not any(hedge in window for hedge in HEDGES):
                    offenders.append(f"{page.relative_to(REPO)}:{number + 1}")
        assert offenders == [], (
            "these pasteable commands install a package that answers 404 today "
            f"and nothing near them says so: {offenders}"
        )
