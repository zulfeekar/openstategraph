"""Pins production-ready/86: the wiki must not assert CI has never run.

`openwiki/quickstart.md` and `openwiki/testing.md` both carried a stale claim
("no CI run has ever happened here" / a blockquote saying no GitHub Actions
workflow has ever executed) left over from before this repository had a git
remote. `CLAUDE.md` records the corrected, dated, sourced account: a `beta`
remote exists and CI does run and does pass. A number in prose has no way to
fail, so this pins the checkable half — that the retracted phrasing does not
reappear — rather than re-asserting a run count that can only drift.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WIKI = REPO_ROOT / "openwiki"

#: Phrases retracted by CLAUDE.md's OpenWiki correction block. Case-sensitive
#: substrings are enough — these are distinctive, not generic English.
RETRACTED_CLAIMS = (
    "no CI run has ever happened",
    "No GitHub Actions workflow in this repository has ever executed",
    "zero git remotes",
)


def test_quickstart_and_testing_pages_exist() -> None:
    assert (WIKI / "quickstart.md").is_file()
    assert (WIKI / "testing.md").is_file()


def test_wiki_pages_do_not_claim_ci_never_ran() -> None:
    offenders = {}
    for page in sorted(WIKI.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        hits = [claim for claim in RETRACTED_CLAIMS if claim in text]
        if hits:
            offenders[str(page.relative_to(REPO_ROOT))] = hits
    assert not offenders, (
        "these wiki pages still assert CI has never run, which CLAUDE.md's "
        f"OpenWiki correction block retracts: {offenders}"
    )
