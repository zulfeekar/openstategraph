"""The tracked tree is publishable, or this test names every file that is not.

`publishable/MAP.md` states the destination in one sentence — *the tracked tree
is already publishable, so a release is a copy and never a transformation* —
and the correction inside it is the whole design of this file:

    **A gate that refuses is safe. A gate that rewrites is not.**

Stripping client references *at export* would run an unreviewed transformation
over seventy-odd files on every release, and the artifact published would not
be the artifact tested. Doing the pass once, in beta, makes the two trees
identical and leaves this gate with nothing to do but say yes or no. So there
is no autofix here, no `--fix`, and no sed pass. It refuses.

## Why it was red, and what it means now that it is green

`publishable/03` was the pass over the files this gate named. The gate was
written *first*, on purpose: a pass with nothing to prove itself against is a
pass that reports its own success, and this repository has found a dozen
instances of that shape. `test_no_tracked_file_names_an_engagement` failed on
the tree of 2026-08-30 naming **76 files** — that failure was the worklist and
the definition of done — and `03` cleared it: seventeen documents whose subject
*was* the engagement were deleted, and the rest moved to their chinook
analogues.

**Two tests in this module changed shape when that happened, and the change is
recorded rather than quiet.** `test_it_reads_file_contents` and
`test_it_reads_the_changelog_whose_job_is_to_recount_history` both asserted
`"CHANGELOG.md" in unpublishable_files()`. That was the strongest
demonstration available while the tree was dirty, and it expires by
construction the moment the pass succeeds — so each now pins the property it
was standing for (a body is read as well as a path; the changelog is in the
corpus) against something that does not depend on the tree being dirty.
Nothing about what the gate refuses moved.

## The term table is not in this file, and that is `publishable/06`

This module used to carry the refused words themselves, spelled out, each with
an argued paragraph naming its referent. A pre-publication sweep measured the
consequence and it is the finding the whole map turns on: **the gate was the
largest single disclosure in the tree.** Every other file *mentioned* a term;
this one **defined** each term and stated what it named — a client company, an
employer, an engagement's short name, a warehouse catalogue identifier, three
object names from inside that warehouse, a research directory. It is tracked,
so it would have landed in the public commit; and the sdist ships
`backend/tests/` whole, so it would have left in the distribution too.

So the words live in a file this repository does not track, and this module
loads them. What is published is the **mechanism** — the boundary rule, the
corpus, the exclusions, the refusal — demonstrated against fabricated terms
that name nobody, plus the `PERMITTED` table, which names only domain
vocabulary a public repository exists to demonstrate.

### Where the table is, and the precedence

1. `$OPENSTATEGRAPH_ENGAGEMENT_TERMS`, if set to a non-empty value, is the
   path to the table. It exists for worktrees, for CI, and for anybody whose
   checkout is not where the default looks.
2. Otherwise `.engagement-terms.json` beside the **main** checkout's `.git`.
   Not this checkout's root: `git rev-parse --git-common-dir` answers with the
   main checkout's `.git` from inside any worktree, so one table serves every
   worktree of the repository and a new worktree inherits a working gate
   instead of a silently skipped one. In an ordinary checkout the two answers
   are the same directory, so this costs nothing and buys the worktree case.
   Where git cannot be reached at all, this checkout's root is the fallback.

The path is gitignored, and it is outside `backend/` on purpose: the sdist is
built from `backend/`, so a table under the repository root cannot reach a
distribution even by accident. Belt and braces, since hatchling honours the
ignore file too.

### An absent table skips. It never passes

**This is the part that matters, and it is asserted rather than trusted.** A
gate whose data is missing and which reports green is worse than no gate: it
publishes a check that did not run. The matcher cannot even be *called* without
a table — `refused_terms_in` takes its patterns as a required argument, so
there is no empty-table default to fall through — and
`test_no_tracked_file_names_an_engagement` calls `refused_terms_or_skip()`,
which raises `pytest.skip` naming what it could not check and both places it
looked. `TestAnAbsentTableSkipsRatherThanPasses` is that distinction as a test.

The cost is real and is stated: a gate that is inert for anyone who clones is a
gate that runs on one machine. That is the trade `06` bought — the alternative
was publishing the list, and a public repository announcing the engagement it
was scrubbed to protect is not a trade at all.

## `publishable/01` — which words identify an engagement, and which are English

The measured inventory (tracked files, 2026-08-29, re-measured 2026-08-30 and
unchanged) offered eleven candidates. They fall into three classes and only one
of them is obvious.

**Identifying.** Seven entries, and each is one of four kinds, described here
by kind because naming them here is what `06` was about:

- **A company name.** A proper noun with exactly one referent. There is no
  reading of such a word that is not the company, it is the one class whose
  presence is a disclosure even with every other word removed, and no public
  example this repository would ever want to ship has a reason to say it. It
  is also the class where a reader could plausibly argue for leaving a mention
  in place — a credit, an acknowledgement — which is exactly why it is refused
  rather than left to judgement in seventy separate places. Two entries are of
  this kind, one of which has **zero occurrences** and is listed precisely
  because of that: a term the gate has never fired on is a term nobody has had
  a chance to normalise, and the cheapest moment to forbid a word is before it
  appears.
- **An engagement's short name.** The widest of the terms, and the one that is
  also a prefix — of a warehouse catalogue, of repositories living outside this
  tree, of directories. Short abbreviations are where the boundary rule earns
  itself: three letters occur inside ordinary identifiers, and the rule below
  is what keeps our own class names out of the refusal list.
- **A warehouse identifier.** The catalogue an engagement's data sits in, and
  the single most identifying string a tree of this shape carries. It is a
  `snake_case` compound, which is why `\\b` is not the boundary (see below).
- **An internal object name.** A table, a lens, a fact table, a research
  directory — coined compounds invented inside somebody else's deployment. No
  dictionary, no public schema and no other project spells them, so a match is
  never ambiguous. They are refused *separately* rather than left to the
  engagement prefix, because a term that fires by itself is what puts a file on
  the worklist in its own right — and some of those files carry genuinely
  valuable writing that should reach a chinook analogue rather than be deleted.
  Four entries are of this kind.

Each entry carries its own argument in the table file, where it can name its
subject. The kinds are here, where it cannot.

**Domain words that are ordinary English.** `vessel`, `geofence`, `IMO`. A
maritime example in a public workflow tool is not a disclosure, and `vessel` is
the largest count on the inventory at 288 lines — so a blanket ban would be
simultaneously the most expensive rule and the least justified one. These are
`PERMITTED`, explicitly, so that a future reader does not "tidy" them in.

**A public product name.** `Databricks`. Naming a warehouse vendor discloses
nothing; thousands of public repositories do it. The phrase that *does*
disclose is the whole stack — a private lens named on a public vendor — and it
contains a refused term and is refused for that. Also `Chinook`, which the
ticket required be excluded by name: it is the canonical public sample
database, it is what `workflows/chinook-assistant` demonstrates, and a gate
that refused on it would refuse the best thing the public repository has.

**`PERMITTED` stays tracked, and that was checked entry by entry rather than
assumed** (`publishable/08`). Every one of these five words is either ordinary
English, a public standard, a public product or a public dataset; none has a
private referent; and the whole point of the table is that a future reader
finds the argument *before* reaching for the obvious rule. Publishing a list of
words that are fine to say discloses nothing. Two of the five reasons named a
private object to make their point and have been rewritten to make it by kind.

### Per-term, not per-combination

`vessel` alone is nothing; `vessel` beside a private object name is an
engagement, so a co-occurrence rule would be more accurate. It was considered
and rejected. A co-occurrence rule has to answer *within what window* — the
line, the paragraph, the file? — and every answer is arbitrary, which makes the
gate's behaviour unpredictable. This repository has written down what happens
next: an instrument that fails wrongly, or unpredictably, gets suppressed and
then measures nothing. The accuracy is not worth a rule nobody can predict.

The measurement that settles it: of the tracked files carrying a permitted
domain word, exactly eight carry **no** refused term, and all eight were read.
They are fixtures using the noun `vessel`, one `IMO` in a tool message, and
three documents naming Databricks as a vendor or `DATABRICKS_TOKEN` as a
credential *variable*. None of them discloses an engagement. The per-term rule
loses nothing here.

### The boundary is alphanumeric, not `\\b`

Substring matching cries wolf and word-boundary matching misses, and the
inventory contained both proofs. Both are demonstrated below against
`DEMONSTRATION_TERMS` — fabricated words with the same *shapes* as the real
ones, so the rule is provable in public:

- Our own class names contain a short refused abbreviation, case-insensitively.
  Under a substring rule this gate would refuse three of them, in our own
  source.
- `package-lock.json` carries npm integrity hashes, and one of them contains a
  short term between two digits. Same failure, on a file nobody will ever
  scrub.
- A warehouse catalogue is `snake_case`, and Python's `\\b` does **not** fire
  inside `snake_case`, because `_` is a word character. A `\\b` rule would miss
  the most identifying string in the tree.

So a term matches when it is not flanked by a letter or a digit. `_` and `-`
and `.` are separators, because this tree writes identifiers in `snake_case`,
`kebab-case` and dotted SQL paths, and an engagement's name is a segment of all
three. Matching is case-insensitive: a word and its uppercase spelling are one
term, not two.

## The corpus, and every exclusion

**Tracked files, from `git ls-files`.** Not a filesystem walk, because a walk
needs its own ignore list and that is two spellings of one thing — the defect
`CLAUDE.md` names repeatedly. It also gets `.scratch/` right for free:
`.scratch/` is gitignored, is never published, and its tickets name the client
constantly (including the two that specified this gate), so it must be out of
the corpus. It is out because it is untracked, not because anything here
mentions it.

**There are now three exclusions where there were four, and the one that went
is the interesting one.**

1. ~~**This file.**~~ **Gone.** It excluded itself because it had to spell the
   refused terms out to look for them — a correct argument for a file that held
   the table, and a dead one for a file that does not. This module is now an
   ordinary member of its own corpus, scanned like everything else, and
   `test_the_gate_is_subject_to_itself` asserts that there is **no content
   exclusion at all**. An exemption that costs nothing gets taken and then the
   gate is furniture; the cheapest exemption is the one that no longer exists.
2. **Commit messages are not checked, deliberately.** Seventy of them mention
   the engagement and they stay in beta, where they belong: stable receives a
   tree, not a history. Said here so nobody adds the check and makes the gate
   permanently red for something that is not a defect.
3. **Nothing else.** Binary files are *not* excluded — they are decoded as
   latin-1 and scanned as bytes. That is deliberate: the inventory recorded
   "no fixture data carries client rows" and "none today" is not a rule, so a
   `.sqlite` of client rows is exactly the failure this covers. It costs
   nothing today — zero of the seven tracked binaries match — and the
   alphanumeric boundary makes a byte-coincidence in a compressed stream
   implausible rather than merely unlikely.
4. **Paths are scanned as well as contents**, with the same list, because a
   content grep never sees a filename. A document whose *title* named the
   engagement was refused for its path as well as its body, and `03` deleted
   it; the property survives here as `test_it_reads_paths_a_content_grep_never_sees`,
   which builds its example out of a demonstration term rather than quoting the
   real filename.

`backend/tests/test_a_row_count_is_not_a_vessel_count.py` was recorded on the
map as an offending filename. Under `01`'s decision it is not one: `vessel` is
permitted English, in a path exactly as in a body. It was refused for its
**contents**, which `03` cleaned; whether it is also renamed is a style call,
not a gate call.

## Two things this gate cannot see, stated rather than implied

**A residue.** It refuses on *names*. After `03` removes an engagement's short
name from a document, a column, a ship and a table whose names are ordinary
industry vocabulary all survive and the gate goes green. Those were measured;
every file carrying one was already refused for a name, so the gap cost nothing
at the time, and it is written down here because the by-eye half is real work.
Adding them as terms was rejected: generic maritime schema naming is what any
maritime schema produces, and banning it would refuse a public maritime example
— the false failure this whole decision is built to avoid.
`publishable/07` is that residue, measured.

**Unverifiable evidence.** A docstring citing a large count of something names
nobody and passes. It is still evidence no reader outside one engagement could
check, and `01`'s style rule covers it: **replace a client fact with its
chinook analogue, not with an abstraction** — a run that answered `3,503
artists` reaches the same defect and anyone who clones the repository can
reproduce it. Where no analogue exists, delete the number; never invent one.
The gate cannot tell a client number from any number, and is not asked to.

## Where it runs

Here, in `backend/tests`, and nowhere else. A release-time check in
`.github/workflows/` was the obvious second home and would today be decorative:
CI has started no job since 2026-08-29 21:43Z — every run fails in seconds with
zero steps on a billing failure that only the owner can clear
(`docs-and-gaps/22`). A gate that exists only in a workflow file is a gate that
does not exist. And two homes would mean two spellings of one list unless the
workflow shelled into pytest, at which point the workflow adds nothing this
file does not already do.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

TERM_TABLE_ENV = "OPENSTATEGRAPH_ENGAGEMENT_TERMS"
TERM_TABLE_NAME = ".engagement-terms.json"


@dataclass(frozen=True)
class Term:
    """A word, and the argument for the class it was put in."""

    word: str
    reason: str


def _main_checkout() -> Path:
    """The main checkout's root, so one table serves every worktree.

    `git rev-parse --git-common-dir` answers with the *main* checkout's `.git`
    from inside any worktree, which is the idiom `CLAUDE.md` already teaches
    for linking `node_modules`. In an ordinary checkout it answers this
    checkout's own `.git`, so the two cases are one line of code. Where git
    cannot be reached, this checkout's root is the honest fallback.
    """
    if shutil.which("git") is None:
        return REPO
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return REPO
    if not common:
        return REPO
    return (REPO / common).resolve().parent


def term_table_path() -> Path:
    """Where the refused-term table is, by the precedence in the docstring."""
    named = os.environ.get(TERM_TABLE_ENV, "").strip()
    if named:
        return Path(named).expanduser()
    return _main_checkout() / TERM_TABLE_NAME


def load_refused_terms(path: Path | None = None) -> tuple[Term, ...] | None:
    """The table, or `None` when there is no file to read.

    `None` rather than an empty tuple, and that distinction is the whole
    safety property: an empty tuple is a table that refuses nothing, which is
    indistinguishable from a clean tree. Callers must decide what to do with a
    missing table, and the only correct answer is to skip.
    """
    table = path or term_table_path()
    if not table.is_file():
        return None
    data = json.loads(table.read_text(encoding="utf-8"))
    return tuple(Term(entry["word"], entry["reason"]) for entry in data["refused"])


def refused_terms_or_skip() -> tuple[Term, ...]:
    """The table, or a skip that says what went unchecked and where to look."""
    terms = load_refused_terms()
    if terms is None:
        pytest.skip(
            "The refused-term table is absent, so NO TRACKED FILE WAS CHECKED "
            "for client-engagement names. This is a skip and not a pass on "
            f"purpose. Expected at {term_table_path()}, or at a path named by "
            f"${TERM_TABLE_ENV}. The table is untracked by construction — see "
            "this module's docstring and `publishable/06`."
        )
    return terms


DEMONSTRATION_TERMS: tuple[str, ...] = ("nda", "night_shift", "orbitwave")
"""Fabricated terms with the shapes of the real ones, so the rule is provable.

A short abbreviation that hides inside ordinary identifiers, a `snake_case`
compound whose spaced spelling is ordinary English, and a coined compound. The
boundary tests below run against these and never against the table, so they
pass in a clone that has no table and they disclose nothing in one that does.
"""


def _pattern(word: str) -> re.Pattern[str]:
    """A term matches where it is not flanked by a letter or a digit.

    Not `\\b`: `_` is a word character, so `\\b` would miss a `snake_case`
    warehouse catalogue, which is the most identifying string in the tree. Not
    a substring either, which would refuse our own class names and an npm
    integrity hash.
    """
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", re.IGNORECASE)


def patterns_for(words: tuple[str, ...]) -> dict[str, re.Pattern[str]]:
    """Compile a term list. Separate from the matcher so a table is passed in."""
    return {word: _pattern(word) for word in words}


DEMONSTRATION_PATTERNS = patterns_for(DEMONSTRATION_TERMS)


def refused_terms_in(text: str, patterns: dict[str, re.Pattern[str]]) -> list[str]:
    """Every refused term appearing in `text`, sorted. The whole matcher.

    `patterns` is required and has no default. A default would be an empty
    table that matches nothing, and a matcher that quietly matches nothing is
    the failure mode this module is built to make impossible.
    """
    return sorted(word for word, pattern in patterns.items() if pattern.search(text))


def tracked_files() -> list[str]:
    """The corpus: paths `git` tracks, so `.scratch/` is out for free."""
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip(
            "The corpus is `git ls-files`, and this checkout has no git. "
            "The gate's home is a developer checkout or CI, where it does."
        )
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [path for path in listing.split("\0") if path]


def _read(path: Path) -> str:
    """Text if it is text, bytes-as-latin-1 if it is not. Binaries are scanned."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def unpublishable_files() -> dict[str, list[str]]:
    """Every tracked file that names an engagement, and which terms it names.

    Contents and path both, against one list, with no file excluded. Commit
    messages are not checked and never will be — see this module's docstring.
    """
    patterns = patterns_for(tuple(term.word for term in refused_terms_or_skip()))
    found: dict[str, list[str]] = {}
    for relative in tracked_files():
        absolute = REPO / relative
        if not absolute.is_file():
            continue
        terms = sorted(
            set(refused_terms_in(relative, patterns))
            | set(refused_terms_in(_read(absolute), patterns))
        )
        if terms:
            found[relative] = terms
    return found


PERMITTED: tuple[Term, ...] = (
    Term(
        "vessel",
        "Ordinary English and ordinary maritime vocabulary, and the largest "
        "count on the inventory at 38 files and 288 lines — so a ban would be "
        "the most expensive rule here and the least justified. A maritime "
        "example in a public workflow tool discloses nothing; ships are not a "
        "trade secret. The five files that carry it with no refused term "
        "beside it were read: they are test fixtures using the noun. Recorded "
        "explicitly rather than merely absent, because the next reader to "
        "look at the inventory will see 288 lines against the biggest number "
        "on the list and reach for the obvious rule.",
    ),
    Term(
        "geofence",
        "Ordinary geospatial English, shipped in the public documentation of "
        "every mapping and logistics product there is. A fully qualified "
        "table name of the form `<catalogue>.<schema>.geofences_latest` is "
        "refused through its catalogue prefix, which is a refused term; the "
        "word `geofence` by itself identifies nothing and nobody. 20 files, "
        "and refusing them would mean a public workflow tool could not carry "
        "a worked spatial example, which is a real cost paid for no "
        "protection at all. The reason used to make that point by naming the "
        "private table; it makes it by shape now (`publishable/06`).",
    ),
    Term(
        "IMO",
        "The International Maritime Organization's public ship identifier — a "
        "standard number in the same class as an ISBN or a VIN, printed on "
        "hulls and published in open registries. Naming the identifier "
        "discloses nothing about who was asking about which ships. It is also "
        "the one candidate where a case rule would have been argued: three "
        "letters, uppercase, that could collide with English. They do not "
        "here, and it is permitted anyway, so the question is moot rather "
        "than answered by luck.",
    ),
    Term(
        "Databricks",
        "A public product name. Thousands of public repositories name their "
        "warehouse vendor and none of them discloses a customer by doing it. "
        "The phrase that does disclose is the whole stack — a named private "
        "lens running on a named public vendor — and that phrase contains a "
        "refused term and is refused for it, which is the per-term rule doing "
        "exactly the work a co-occurrence rule was proposed for. The three "
        "files carrying this word with no refused term were read: two name "
        "the vendor, one names `DATABRICKS_TOKEN`, which is a credential "
        "variable and not a value, and naming the variable is the standing "
        "rule rather than a breach of it.",
    ),
    Term(
        "chinook",
        "The canonical public sample database, and the reason this exclusion "
        "is written down instead of left implicit. `workflows/chinook-"
        "assistant` is the public analogue of the client demo: same shapes, "
        "same defects reachable, public data anyone can clone. A gate that "
        "refused on it would refuse the best thing the public repository has, "
        "and 267 files carry the word. It is also the destination of `01`'s "
        "style rule — a client fact becomes a chinook fact, not an "
        "abstraction — so `03` will make this word *more* common, not less. "
        "Recorded here so a future reader tidying the term table does not "
        "read the absence as an oversight.",
    ),
)


def test_no_tracked_file_names_an_engagement() -> None:
    """The gate. It refuses; it does not rewrite.

    Skips — loudly, naming both places it looked — when the term table is
    absent, because a gate with no data reporting green is worse than no gate.
    """
    offenders = unpublishable_files()

    assert not offenders, (
        f"{len(offenders)} tracked files name a client engagement, so the tree "
        "is not publishable as it stands.\n\n"
        + "\n".join(f"  {path}  ->  {', '.join(terms)}" for path, terms in sorted(offenders.items()))
        + "\n\n"
        "This gate refuses; it does not rewrite. There is no autofix, and "
        "adding one would mean the artifact published is not the artifact "
        "tested — which is the reason the pass happens once, here, in beta.\n"
        "What to do with each one: a client fact becomes its chinook "
        "analogue, not an abstraction. A client row count becomes `3,503 "
        "artists` — the same defect, reproducible by anyone who clones the "
        "repository. Where no analogue exists, delete the number rather than "
        "blur it, and never invent one. A whole document about the client's "
        "warehouse is usually deleted, not scrubbed.\n"
        "What is NOT a defect: `vessel`, `geofence`, `IMO`, `Databricks` and "
        "`chinook` are permitted by name, with the argument, in this file's "
        "`PERMITTED` table. If one of them is what you came here to add to "
        "the refused table, read its paragraph first."
    )


class TestAnAbsentTableSkipsRatherThanPasses:
    """The property `06` bought the untracked table with. Green is a claim."""

    def test_a_missing_table_loads_as_none_not_as_empty(self, tmp_path: Path) -> None:
        # `None` and `()` are the whole distinction: an empty table refuses
        # nothing, which reads exactly like a clean tree.
        assert load_refused_terms(tmp_path / "absent.json") is None

    def test_the_gate_skips_when_the_table_is_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TERM_TABLE_ENV, str(tmp_path / "absent.json"))
        with pytest.raises(BaseException) as raised:
            test_no_tracked_file_names_an_engagement()
        assert raised.typename == "Skipped"
        assert "NO TRACKED FILE WAS CHECKED" in str(raised.value)
        assert str(tmp_path / "absent.json") in str(raised.value)

    def test_the_matcher_cannot_be_called_without_a_table(self) -> None:
        # No default argument, so there is no way to run the matcher against
        # nothing and read the silence as a pass.
        with pytest.raises(TypeError):
            refused_terms_in("anything at all")  # type: ignore[call-arg]

    def test_the_environment_variable_wins_over_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TERM_TABLE_ENV, str(tmp_path / "elsewhere.json"))
        assert term_table_path() == tmp_path / "elsewhere.json"

    def test_an_empty_variable_falls_through_to_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TERM_TABLE_ENV, "  ")
        assert term_table_path().name == TERM_TABLE_NAME

    def test_the_default_is_beside_the_main_checkout_so_worktrees_share_it(
        self,
    ) -> None:
        # A worktree's own root would give each worktree its own table, and a
        # new worktree would start with a gate that skips.
        assert (_main_checkout() / ".git").exists()

    def test_the_table_is_never_tracked(self) -> None:
        assert TERM_TABLE_NAME not in tracked_files()
        assert not any(path.endswith(TERM_TABLE_NAME) for path in tracked_files())


class TestTheBoundaryIsAlphanumericAndNotWordBoundary:
    """Both halves are load-bearing, and both were found in the real tree.

    Demonstrated against `DEMONSTRATION_TERMS`, which have the shapes of the
    real entries and name nobody.
    """

    def test_a_bare_term_is_refused(self) -> None:
        assert refused_terms_in("the nda lens", DEMONSTRATION_PATTERNS) == ["nda"]

    def test_case_does_not_matter(self) -> None:
        assert refused_terms_in("NDA", DEMONSTRATION_PATTERNS) == ["nda"]

    def test_a_snake_case_segment_is_refused(self) -> None:
        # `\b` does not fire here, because `_` is a word character. A warehouse
        # catalogue is spelled exactly like this, and it is the reason for the
        # lookarounds rather than a word boundary.
        assert refused_terms_in(
            "ml_nda_app_prod.shipping.dim_widget_latest", DEMONSTRATION_PATTERNS
        ) == ["nda"]

    def test_a_kebab_case_segment_is_refused(self) -> None:
        assert refused_terms_in("nda-toolkit", DEMONSTRATION_PATTERNS) == ["nda"]

    def test_our_own_class_names_are_not_refused(self) -> None:
        # A substring rule refuses identifiers of this shape in our own source.
        assert refused_terms_in("_PandaCache _AgendaWorker _CalendarLoop", DEMONSTRATION_PATTERNS) == []

    def test_a_lockfile_hash_is_not_refused(self) -> None:
        # The shape from `package-lock.json`: a short term between two digits.
        assert refused_terms_in(
            "sha512-1quofZ2RQ9EWdeN34S79+KE7ndA1WGxV", DEMONSTRATION_PATTERNS
        ) == []

    def test_the_english_phrase_survives_the_identifier_ban(self) -> None:
        assert refused_terms_in("the night shift ends", DEMONSTRATION_PATTERNS) == []
        assert refused_terms_in("lens `night_shift`", DEMONSTRATION_PATTERNS) == ["night_shift"]

    def test_the_real_table_obeys_the_same_rule(self) -> None:
        # The demonstration proves the matcher; this proves the matcher is what
        # the real terms are run through. No term is printed.
        terms = refused_terms_or_skip()
        patterns = patterns_for(tuple(term.word for term in terms))
        for word in patterns:
            assert refused_terms_in(f"a segment_{word}_here", patterns) == [word]
            assert refused_terms_in(f"x{word}x", patterns) == []


class TestThePermittedWordsArePermitted:
    """`01`'s second class, asserted rather than merely absent from the first.

    This table stays tracked. Every entry is ordinary English, a public
    standard, a public product or a public dataset — publishing a list of words
    that are safe to say discloses nothing, and the list exists so a future
    reader finds the argument before reaching for the obvious rule.
    """

    @pytest.mark.parametrize("term", PERMITTED, ids=lambda term: term.word)
    def test_a_permitted_word_alone_passes(self, term: Term) -> None:
        patterns = patterns_for(tuple(t.word for t in refused_terms_or_skip()))
        assert refused_terms_in(f"a sentence about {term.word} and nothing else", patterns) == []

    def test_chinook_is_what_the_public_repository_exists_to_demonstrate(self) -> None:
        # The exclusion the ticket asked for by name. A gate that refused here
        # would refuse `workflows/chinook-assistant`, the best thing we ship.
        patterns = patterns_for(tuple(t.word for t in refused_terms_or_skip()))
        assert refused_terms_in(
            "workflows/chinook-assistant/data/Chinook_Sqlite.sqlite", patterns
        ) == []

    def test_a_maritime_example_is_not_a_disclosure(self) -> None:
        patterns = patterns_for(tuple(t.word for t in refused_terms_or_skip()))
        assert refused_terms_in("count the vessels inside each geofence by IMO", patterns) == []

    def test_naming_a_vendor_is_not_a_disclosure(self) -> None:
        patterns = patterns_for(tuple(t.word for t in refused_terms_or_skip()))
        assert refused_terms_in("answered against Databricks using DATABRICKS_TOKEN", patterns) == []

    def test_no_word_is_in_both_tables(self) -> None:
        refused = {term.word.lower() for term in refused_terms_or_skip()}
        assert not {term.word.lower() for term in PERMITTED} & refused


class TestTheGateCoversWhatTheInventoryFound:
    """Four kinds of hiding place, because the inventory found all four."""

    def test_it_reads_file_contents(self, tmp_path: Path) -> None:
        # Until `publishable/03` this asserted `"CHANGELOG.md" in
        # unpublishable_files()`, which was the strongest demonstration
        # available while the tree was dirty and expires the moment the pass
        # succeeds. The claim it was making — *a body is read, not only a
        # path* — is made here against a file written for the purpose, so it
        # survives the tree being clean and would survive the tree going
        # dirty again.
        planted = tmp_path / "innocent-name.md"
        planted.write_text("a paragraph that names orbitwave in passing\n")
        assert refused_terms_in(_read(planted), DEMONSTRATION_PATTERNS) == ["orbitwave"]

    def test_it_reads_paths_a_content_grep_never_sees(self) -> None:
        path = "docs/decisions/an-agent-that-reaches-nda-through-mcp.md"
        assert "nda" in refused_terms_in(path, DEMONSTRATION_PATTERNS)

    def test_it_reads_the_changelog_whose_job_is_to_recount_history(self) -> None:
        # The likeliest place for a client name to survive a prose pass, so
        # the property worth pinning is that it is **in the corpus** — which
        # stays true and stays checkable now that its contents are clean.
        assert "CHANGELOG.md" in tracked_files()

    def test_it_reads_bytes_so_fixture_data_cannot_hide(self) -> None:
        # "No fixture data carries client rows" was measured, and "none today"
        # is not a rule. Binaries are decoded latin-1 and scanned, which costs
        # nothing: zero of the seven tracked binaries match.
        assert refused_terms_in(
            b"\x00\x01orbitwave\xff".decode("latin-1"), DEMONSTRATION_PATTERNS
        ) == ["orbitwave"]

    def test_the_corpus_is_tracked_files_so_scratch_is_out(self) -> None:
        assert not any(path.startswith(".scratch/") for path in tracked_files())


class TestTheExclusionsCostSomethingVisible:
    """An exemption that costs nothing gets taken, and then the gate is furniture."""

    def test_the_gate_is_subject_to_itself(self) -> None:
        # There is no content exclusion any more. The self-exclusion existed
        # because this file held the term table; it does not, so the file is an
        # ordinary member of its own corpus and this assertion is the proof.
        this_file = Path(__file__).resolve().relative_to(REPO).as_posix()
        assert this_file in tracked_files()
        assert this_file not in unpublishable_files()

    def test_no_term_is_spelled_out_in_this_file(self) -> None:
        # The inverse of the test this replaces. That one demanded the terms be
        # spelled out here, as the price of the self-exclusion; this one
        # forbids it, which is what `06` decided.
        source = Path(__file__).read_text(encoding="utf-8")
        for term in refused_terms_or_skip():
            assert term.word.lower() not in source.lower()

    @pytest.mark.parametrize("term", PERMITTED, ids=lambda term: term.word)
    def test_every_permitted_term_carries_its_argument(self, term: Term) -> None:
        # Length is a crude proxy for "somebody actually thought about this",
        # and a crude proxy beats none. Same threshold as the censuses.
        assert len(term.reason.strip()) > 400

    def test_every_refused_term_carries_its_argument(self) -> None:
        # Same threshold, applied to the table wherever it lives. The arguments
        # moved out of this file with their terms; they did not stop existing.
        for term in refused_terms_or_skip():
            assert len(term.reason.strip()) > 400
