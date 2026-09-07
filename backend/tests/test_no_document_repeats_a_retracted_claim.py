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

**One class of number is the exception, and it is here because it is not
really a number** (`docs-and-gaps/29`). A GitHub Actions *run count* is not a
property of this tree at all: it changes when somebody pushes, so no literal
written into a document stays true, and no test in this repository can check
one without network and credentials. Measured 2026-08-30, every count on
`docs/releasing.md`'s status table had drifted — `openwiki-update.yml` was
written "zero runs, ever" the week after its first run, `pages.yml` said six
here and four in `CLAUDE.md` and was neither, `release-pr.yml`'s two had
become three — and two of those figures had already been corrected once. So
the rule below is not "assert the right number", which would be a test edited
on every push; it is **state the state, never the count**, which is
`docs-and-gaps/17`'s answer to a figure with no mechanical referent.

The matcher deliberately requires a *workflow filename* or a multi-word
workflow name in the same paragraph. A bare `CI`, `Release` or `Triage` is ordinary
English in a repository that ships workflows by those names, and the third
rule of construction is the one this file already keeps: forbid distinctive
phrasings, never ordinary English. A count beside `Release` alone therefore
goes uncaught, and that is priced rather than papered over.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: Every hand-written document a reader treats as authoritative. `.scratch/`
#: is deliberately absent: a ticket describing the behaviour that was
#: retracted is the record of the retraction, not a repetition of it.
#:
#: `CONTRIBUTING.md` and `SECURITY.md` joined on `stable-beta-public/04`: the
#: sweep found a retracted claim living in `CONTRIBUTING.md` — the collection
#: gap described as "the entire `workflows/` half" when `pytest.ini` sweeps one
#: package of it — and the file that exists to catch exactly that could not see
#: the page, because the corpus was `docs/**` and three READMEs.
CORPUS = (
    [
        REPO_ROOT / "CLAUDE.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "backend" / "README.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / "SECURITY.md",
    ]
    + sorted((REPO_ROOT / "docs").rglob("*.md"))
    + sorted((REPO_ROOT / "openwiki").rglob("*.md"))
    # `docs-onramp/03`: the published landing page repeated the `Mock · Offline`
    # claim in HTML. A reader who has not installed anything reads it *before*
    # any markdown page, so a corpus that stops at markdown stops one document
    # short of the front of the funnel.
    + [REPO_ROOT / "site" / "index.html"]
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
    # docs-and-gaps/29 — `openwiki-update.yml` had already run and failed when
    # `docs/releasing.md` wrote this row, and said so forty lines further down.
    "zero runs, ever",
    # stable-beta-public/04 — three counts of a registered surface, each true
    # when written and each falsified by the commit that registered one more.
    # The pages they stood on are pinned by name now
    # (`test_documented_mcp_tool_surface.py`, `test_documented_stream_surface.py`),
    # which is the instrument that catches the *next* one; these rows catch a
    # copy of the retracted sentence landing in a second document, which is
    # what this file is for and what a per-page pin cannot see.
    "The nine exposed tools",
    "The other eight stay fully functional",
    "The three event streams",
    # stable-beta-public/04 — `pytest.ini` declares
    # `testpaths = backend workflows/chinook-assistant`, one package rather
    # than the tree; `workflows/` as a whole is deliberately unswept and
    # `test_collection_policy.py` pins that. `CONTRIBUTING.md` said this while
    # `README.md`, forty lines of argument later, said the opposite.
    "the entire `workflows/` half",
    # docs-onramp/03 — measured on a fresh 0.3.0rc14 install, 2026-09-05:
    # selecting `mock/mock-offline` on the agent and pressing Run produced
    # three `POST /api/runs/stream → 503`. It is not a way to a first answer
    # and it is not the default — `WORKFLOW_DEFAULT_MODEL` is the empty string
    # (`src/nodes/modelField.ts`, which records why the mock default was
    # removed), and `NodeRuntime._resolve_model` reads `mock` as *no override*
    # exactly as it reads empty. The client-side engine that owned the mock has
    # had no caller outside a test since the Run button was rewired to stream a
    # real backend run, which `src/view/overlays/OnboardingHint.tsx` already
    # recorded and no page had caught up with.
    "The canvas preview still answers with no credential",
    "canvas preview defaults to `Mock · Offline` and answers with no credential",
    "the canvas preview's default model\nis `Mock · Offline`",
    "The canvas preview defaults\n            to <code>Mock · Offline</code>",
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


WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: A count of executions, in the shapes this repository has actually written.
RUN_COUNT = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d+)"
    r"\s+(?:green |failed |successful |scheduled )?(?:runs?|failures?|times)\b"
    r"|\b(?:run|ran|fired|failed)\s+(?:once|twice)\b",
    re.IGNORECASE,
)

#: A sentence in the past tense is the correction, not the claim — the same
#: escape hatch the `docs-freshness` rule above uses, and for the same reason:
#: a page must be able to record that it once carried a wrong number.
PAST_TENSE = re.compile(r"\b(was|were|used to|until|no longer|had|counted|said|claimed)\b")


def _workflow_mentions() -> tuple[str, ...]:
    """Filenames, plus workflow `name:`s of more than one word.

    Derived from `.github/workflows/` rather than listed, so adding a workflow
    extends the rule. Single-word names are excluded on purpose — see the
    module docstring.
    """
    mentions = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        mentions.append(path.name)
        match = re.search(r"^name:\s*(.+?)\s*$", path.read_text(encoding="utf-8"), re.M)
        if match:
            name = match.group(1).strip("\"'")
            if " " in name:
                mentions.append(name)
    return tuple(mentions)


def _paragraphs(text: str) -> list[tuple[int, list[str]]]:
    """`[(first line number, lines)]`, split on blank lines."""
    blocks: list[tuple[int, list[str]]] = []
    current: list[str] = []
    first = 1
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip():
            if not current:
                first = number
            current.append(line)
        elif current:
            blocks.append((first, current))
            current = []
    if current:
        blocks.append((first, current))
    return blocks


def test_paragraphs_are_split_on_blank_lines() -> None:
    assert _paragraphs("a\nb\n\n\nc\n") == [(1, ["a", "b"]), (5, ["c"])]


def test_there_are_workflow_names_to_match_on() -> None:
    """Without this, an empty `.github/workflows/` makes the rule vacuous."""
    mentions = _workflow_mentions()
    assert len(mentions) >= 6
    assert "pages.yml" in mentions


def test_no_document_puts_a_run_count_beside_a_workflow() -> None:
    """`docs-and-gaps/29`: state the state, never the count.

    Every figure this rule now forbids was wrong when it was read back, two of
    them after having been corrected once already. The number is a `gh run
    list` away for anyone who needs today's; a document's job is to say which
    halves of the machinery have never worked, which is a fact that survives
    the next push.
    """
    mentions = _workflow_mentions()
    offenders = {}
    for page in CORPUS:
        for first, block in _paragraphs(page.read_text(encoding="utf-8")):
            # The workflow's name and the count are rarely on one line: a table
            # row wraps, a blockquote breaks. So the *paragraph* decides whether
            # a workflow is under discussion, and the line decides whether it
            # carries a count. Line-scoped, this rule missed both CLAUDE.md
            # figures it was written to catch.
            if not any(mention in "\n".join(block) for mention in mentions):
                continue
            for offset, line in enumerate(block):
                if PAST_TENSE.search(line):
                    continue
                hit = RUN_COUNT.search(line)
                if hit:
                    offenders[f"{page.relative_to(REPO_ROOT)}:{first + offset}"] = hit.group(0)
    assert not offenders, (
        "these lines put a count of GitHub Actions runs next to a workflow's "
        f"name: {offenders}. A run count changes on the next push and nothing "
        "here can check it, so say what has never succeeded and leave the "
        "number to `gh run list` (docs-and-gaps/29)."
    )


#: A distance between two trees, stated as a figure. `178 commits behind
#: `main`` is the instance; the shape is the same for `ahead`.
COMMIT_DISTANCE = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
    r"\s+commits?\s+(?:behind|ahead)\b",
    re.IGNORECASE,
)


def test_no_document_counts_how_far_behind_a_branch_is() -> None:
    """`docs-and-gaps/30`, and `CLAUDE.md` already said so about the wiki stamp.

    `docs/releasing.md` carried a paragraph asserting that the last CI run was
    `2026-08-16T08:23Z`, that nothing had been pushed since, and that every
    gate on the page described a checkout **178 commits behind `main`**. All
    three were false when `29` read them back, and the third could not have
    been anything else: a commit distance is a difference between a moving tree
    and a moving remote, so it is stale in the direction of *understating* the
    gap the moment anybody commits.

    This is the sibling of the run-count rule above, from the same root
    (`docs-and-gaps/17`: a number in prose has no way to fail), and the answer
    is the one `scripts/stamp_wiki_freshness.py` already ships — *"nothing in
    the stamp counts days or commits behind: it names the commit and hands the
    reader `git log <sha>..HEAD`"*. That sentence was a rule stated in
    `CLAUDE.md` and enforced on exactly one generated stamp; this makes it
    reach the pages a reader treats as authoritative.

    **It is a separate rule rather than a widening**, and the distinction is
    the finding `30` asks for: the run-count rule is paragraph-scoped on a
    *workflow name*, and this paragraph named `ci.yml`, so the scoping was not
    what missed it. `178 commits` is not a count of runs, and stretching
    `RUN_COUNT` until it were would have made a rule nobody could state.
    """
    offenders = {}
    for page in CORPUS:
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if PAST_TENSE.search(line):
                continue
            hit = COMMIT_DISTANCE.search(line)
            if hit:
                offenders[f"{page.relative_to(REPO_ROOT)}:{number}"] = hit.group(0)
    assert not offenders, (
        "these lines put a figure on how far one tree is from another: "
        f"{offenders}. That distance changes on the next commit and on the "
        "next push, so name the commit and hand the reader `git log "
        "<sha>..HEAD` instead (docs-and-gaps/30)."
    )
