"""The go-public checklist's secret census is derived, in both directions.

`team-board-and-gap-reports/06`. A repository setting leaves no diff, so the
only record of one is a document — and a document's list of secrets is the part
that rots first, because a workflow gains a `secrets.X` reference in a commit
nobody reads as a settings change. This repository already has the failure on
tape: `openwiki-update.yml` fires on a schedule and dies in about 40 seconds
for want of `secrets.OPENWIKI_API_KEY`, a secret no checklist ever named.

So the checklist's table is asserted **against `.github/workflows/`**, both
ways:

* every `secrets.*` / `vars.*` a workflow references is named on the page — a
  workflow cannot start needing something nobody was told to set;
* every name the page lists is referenced by some workflow — the page cannot
  ask a maintainer to configure a secret that nothing reads, which is the other
  way a checklist stops being trustworthy.

The census is fenced by HTML comments rather than located by heading, because a
heading is prose somebody will reword and the fence is not. Names elsewhere on
the page (`GITHUB_TOKEN` in the fork-secrets paragraph, for one) are deliberately
outside it: the census is the table a maintainer works down, not every mention.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "maintainers" / "public-repository-settings.md"
WORKFLOWS = REPO / ".github" / "workflows"

START = "<!-- secret-census:start -->"
END = "<!-- secret-census:end -->"

#: `secrets.NAME` / `vars.NAME` anywhere in a workflow — including the comment
#: blocks, which is deliberate: `openwiki-update.yml` documents its own three
#: names in a comment above the job that reads them, and a name explained there
#: is a name a maintainer has to set.
REFERENCE = re.compile(r"\b(?:secrets|vars)\.([A-Za-z_][A-Za-z_0-9]*)")

#: The first cell of a table row in the fenced census: `| \`NAME\` | … |`.
ROW = re.compile(r"^\|\s*`([A-Z][A-Z_0-9]*)`\s*\|")


def referenced() -> set[str]:
    found: set[str] = set()
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        found |= set(REFERENCE.findall(workflow.read_text(encoding="utf-8")))
    return found


def listed() -> set[str]:
    text = PAGE.read_text(encoding="utf-8")
    body = text.split(START, 1)[1].split(END, 1)[0]
    return {match.group(1) for line in body.splitlines() if (match := ROW.match(line))}


def test_the_census_was_actually_found() -> None:
    """A sweep over nothing passes, so prove both ends exist first."""
    assert PAGE.is_file(), f"{PAGE.relative_to(REPO)} is the checklist and it is gone"
    text = PAGE.read_text(encoding="utf-8")
    assert START in text and END in text, "the census fence is gone from the checklist"
    assert len(referenced()) >= 4, "no workflow references a secret; this test is measuring nothing"
    assert listed(), "the fenced census has no rows"


def test_every_secret_a_workflow_reads_is_on_the_checklist() -> None:
    unnamed = sorted(referenced() - listed())
    assert unnamed == [], (
        "these names are read by a workflow under .github/workflows/ and the "
        f"go-public checklist does not name them: {unnamed}. A workflow that "
        "needs a secret nobody was told to set fires and fails on a schedule — "
        "which is what openwiki-update.yml does."
    )


def test_the_checklist_asks_for_nothing_no_workflow_reads() -> None:
    orphans = sorted(listed() - referenced())
    assert orphans == [], (
        "the checklist tells a maintainer to configure these, and no workflow "
        f"reads any of them: {orphans}. Either a workflow was removed and the "
        "row outlived it, or the row is for work that has not shipped — in "
        "which case it belongs in prose, not in the census a maintainer ticks."
    )


def test_the_page_holds_no_value_that_looks_like_a_key() -> None:
    """Names only. The checklist is public; the credential map is not."""
    text = PAGE.read_text(encoding="utf-8")
    leaks = re.findall(r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|pypi-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9]{16,})", text)
    assert leaks == [], "the checklist appears to contain a credential value"
