"""A retracted sentence must not survive in a second document.

Widened from `test_wiki_does_not_claim_ci_never_ran.py`, which held these
rules over `openwiki/**` only (production-ready/86). The case for the wider
corpus is `docs-and-gaps/28`: `df8ce54` deleted one line of `ci.yml` — the
`if: github.event_name == 'pull_request'` on `docs-freshness` — and four
documents outside the yaml went false in the same instant. The commit knew,
and corrected the two comments *inside* the file. Nothing could see the other
four, because a "did this code change touch a doc" gate cannot notice drift
that is about its own configuration. A human sweep found them four hours
later.

Two rules of construction, both learned from gates that got suppressed:

- **Derive the fact, do not literalise it.** The `docs-freshness` rule reads
  `ci.yml` and only then judges the prose, so restoring the `if:` makes the
  old sentences legal again rather than making this file wrong.
- **Forbid distinctive phrasings, never ordinary English.** Every literal
  below is a sentence somebody actually wrote and somebody else retracted.
  A gate that fires on a paraphrase is a gate with a `# noqa` in its future.

Retracted-phrase rules cannot see a *number* going stale — that is what the
census and ceiling tests are for. This file covers the other half: a claim
that was corrected in one place and left standing in another.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: Every hand-written document a reader treats as authoritative. `.scratch/`
#: is deliberately absent: a ticket describing the behaviour that was
#: retracted is the record of the retraction, not a repetition of it.
CORPUS = (
    [REPO_ROOT / "CLAUDE.md", REPO_ROOT / "README.md", REPO_ROOT / "backend" / "README.md"]
    + sorted((REPO_ROOT / "docs").rglob("*.md"))
    + sorted((REPO_ROOT / "openwiki").rglob("*.md"))
)

#: Case-sensitive substrings, each a sentence this repository has retracted.
RETRACTED_CLAIMS = (
    # production-ready/86 — a `beta` remote exists and CI does run.
    "no CI run has ever happened",
    "No GitHub Actions workflow in this repository has ever executed",
    "zero git remotes",
    # docs-and-gaps/25 — `backend/pyproject.toml` names this line as the place
    # the wrong sense of "package" kept being copied to. `package` is
    # `workflows/<slug>/` here; the install footprint is four *dependencies*.
    "core is four packages",
)


def test_the_corpus_was_actually_found() -> None:
    """The guard every doc gate written this way needs: if the paths move, the
    rules below start passing over nothing."""
    assert len(CORPUS) > 20
    assert all(page.is_file() for page in CORPUS)


def test_no_document_repeats_a_retracted_claim() -> None:
    offenders = {}
    for page in CORPUS:
        hits = [claim for claim in RETRACTED_CLAIMS if claim in page.read_text(encoding="utf-8")]
        if hits:
            offenders[str(page.relative_to(REPO_ROOT))] = hits
    assert not offenders, (
        "these documents repeat a sentence this repository has retracted "
        f"elsewhere: {offenders}"
    )


def _docs_freshness_is_conditional() -> bool:
    """Does `docs-freshness` still carry an event condition in `ci.yml`?

    Read rather than assumed, so that restoring the `if:` restores the prose
    with it. The job's own block is everything indented under its key up to
    the next job.
    """
    yaml = CI_YAML.read_text(encoding="utf-8")
    block = yaml.split("\n  docs-freshness:\n", 1)[1]
    block = re.split(r"\n  [a-z][\w-]*:\n", block, maxsplit=1)[0]
    return bool(re.search(r"^    if:", block, re.MULTILINE))


#: Phrasings that assert `docs-freshness` declines to run. Each is a sentence
#: that stood in a shipped document at 2026-08-30.
SKIP_CLAIMS = (
    "PR-only",
    "only runs on pull requests",
    "skips on nearly every run",
    "skipped on push",
    "github.event_name == 'pull_request'",
)


def test_the_docs_freshness_job_is_still_named_that() -> None:
    """Without this, a rename turns both assertions below into no-ops."""
    assert "\n  docs-freshness:\n" in CI_YAML.read_text(encoding="utf-8")


def test_no_document_says_docs_freshness_skips_while_it_does_not() -> None:
    """The rule is per *sentence*, not per file, so a page may still explain
    what the job used to do — as `docs/releasing.md` and `CLAUDE.md` now
    both do — as long as the explanation is in the past tense and does not
    put the claim and the job's name in one breath.
    """
    if _docs_freshness_is_conditional():
        return

    offenders = {}
    for page in CORPUS:
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if "docs-freshness" not in line:
                continue
            # A past-tense sentence is the correction, not the claim.
            if re.search(r"\b(was|used to|until|no longer|had been)\b", line):
                continue
            hits = [claim for claim in SKIP_CLAIMS if claim in line]
            if hits:
                offenders[f"{page.relative_to(REPO_ROOT)}:{number}"] = hits
    assert not offenders, (
        "`ci.yml` carries no event condition on `docs-freshness` — it runs on "
        "pushes to main as well as pull requests — and these lines still say "
        f"it skips: {offenders}"
    )
