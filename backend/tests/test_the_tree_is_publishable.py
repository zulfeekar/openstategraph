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

## Why it is red today, and when it goes green

`publishable/03` is the pass over the files this gate names. The gate is
written *first*, on purpose: a pass with nothing to prove itself against is a
pass that reports its own success, and this repository has found a dozen
instances of that shape. `test_no_tracked_file_names_an_engagement` fails on
today's tree — **that failure is the worklist**, and it is the definition of
done for `03`. Every other test in this module passes today and is what proves
the failing one means something.

## `publishable/01` — which words identify an engagement, and which are English

The measured inventory (tracked files, 2026-08-29, re-measured 2026-08-30 and
unchanged) offered eleven candidates. They fall into three classes and only one
of them is obvious.

**Identifying.** `cpl`, `Equinor`, `Bouvet`, `dark_fleet`, `cargoflow`,
`area_counts`, `zee-lab`. Each names the engagement, the company, an object
invented inside their warehouse, or a directory inside their lab. Nothing
generic uses any of them. These are `REFUSED`, and each carries its argument.

**Domain words that are ordinary English.** `vessel`, `geofence`, `IMO`. A
maritime example in a public workflow tool is not a disclosure, and `vessel` is
the largest count on the inventory at 288 lines — so a blanket ban would be
simultaneously the most expensive rule and the least justified one. These are
`PERMITTED`, explicitly, so that a future reader does not "tidy" them in.

**A public product name.** `Databricks`. Naming a warehouse vendor discloses
nothing; thousands of public repositories do it. The phrase that *does*
disclose — *"the CPL lens on Databricks"* — contains `cpl` and is refused for
that. Also `Chinook`, which the ticket required be excluded by name: it is the
canonical public sample database, it is what `workflows/chinook-assistant`
demonstrates, and a gate that refused on it would refuse the best thing the
public repository has.

### Per-term, not per-combination

`vessel` alone is nothing; `vessel` beside `dark_fleet` is an engagement, so a
co-occurrence rule would be more accurate. It was considered and rejected. A
co-occurrence rule has to answer *within what window* — the line, the
paragraph, the file? — and every answer is arbitrary, which makes the gate's
behaviour unpredictable. This repository has written down what happens next: an
instrument that fails wrongly, or unpredictably, gets suppressed and then
measures nothing. The accuracy is not worth a rule nobody can predict.

The measurement that settles it: of the tracked files carrying a permitted
domain word, exactly eight carry **no** refused term, and all eight were read.
They are fixtures using the noun `vessel`, one `IMO` in a tool message, and
three documents naming Databricks as a vendor or `DATABRICKS_TOKEN` as a
credential *variable*. None of them discloses an engagement. The per-term rule
loses nothing here.

### The boundary is alphanumeric, not `\\b`

Substring matching cries wolf and word-boundary matching misses, and the
inventory contains both proofs:

- `_McpLoop`, `_NarratingAsyncPlanner`, `_SlowSyncPlanner` all contain `cpl`
  case-insensitively. Under a substring rule this gate would refuse three of
  our own class names.
- `package-lock.json` carries an npm integrity hash containing `CPL` between
  two digits. Same failure, on a file nobody will ever scrub.
- `ms_cpl_app_prod` is the client's warehouse catalogue and the single most
  identifying string in the tree. Python's `\\b` does **not** fire inside it,
  because `_` is a word character. A `\\b` rule would miss it.

So a term matches when it is not flanked by a letter or a digit. `_` and `-`
and `.` are separators, because this tree writes identifiers in `snake_case`,
`kebab-case` and dotted SQL paths, and the engagement's name is a segment of
all three. Matching is case-insensitive: `cpl`/`CPL` are one term, not two.

## The corpus, and every exclusion

**Tracked files, from `git ls-files`.** Not a filesystem walk, because a walk
needs its own ignore list and that is two spellings of one thing — the defect
`CLAUDE.md` names repeatedly. It also gets `.scratch/` right for free:
`.scratch/` is gitignored, is never published, and its tickets name the client
constantly (including the two that specified this gate), so it must be out of
the corpus. It is out because it is untracked, not because anything here
mentions it.

Four exclusions, and each one costs something visible:

1. **This file.** It has to spell the refused terms out to look for them. The
   exclusion is exactly one path and `test_the_only_content_exclusion_is_this_file`
   asserts that, so widening it is a diff somebody reads.
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
   content grep never sees a filename. `docs/decisions/an-agent-that-reaches-
   cpl-through-mcp.md` is refused for its path as well as its body.

`backend/tests/test_a_row_count_is_not_a_vessel_count.py` was recorded on the
map as the *other* offending filename. Under `01`'s decision it is not one:
`vessel` is permitted English, in a path exactly as in a body. That file is
refused here for its **contents**, which name `cpl`, `area_counts` and
`dark_fleet`; whether `03` also renames it is a style call, not a gate call.

## Two things this gate cannot see, stated rather than implied

**A residue.** It refuses on *names*. After `03` removes `cpl` from a document,
a column called `eq_vessel_class`, a ship called `LYRIC CAMELLIA` and a table
called `plant_tracker` would all survive and the gate would go green. Those
were measured; every file carrying one is already refused for a name, so the
gap costs nothing today, and it is written down here because `03` has to look
for them by eye. Adding them as terms was rejected: `plant_tracker`,
`idle_events`, `ais_sampled` and `dim_vessel_latest` are generic industry
naming that any maritime schema produces, and banning them would refuse a
public maritime example — the false failure this whole decision is built to
avoid.

**Unverifiable evidence.** A docstring citing *"1,454,449 dark vessels"* names
nobody and passes. It is still evidence no reader outside one engagement could
check, and `01`'s style rule covers it: **replace a client fact with its
chinook analogue, not with an abstraction** — *"a run answered 3,503 artists"*
reaches the same defect and anyone who clones the repository can reproduce it.
Where no analogue exists, delete the number; never invent one. The gate cannot
tell a client number from any number, and is not asked to.

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

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve().relative_to(REPO).as_posix()


@dataclass(frozen=True)
class Term:
    """A word, and the argument for the class it was put in."""

    word: str
    reason: str


REFUSED: tuple[Term, ...] = (
    Term(
        "cpl",
        "The engagement's own short name, and the widest of the identifying "
        "terms at 61 files. It is the client's abbreviation, the prefix of "
        "their warehouse catalogue `ms_cpl_app_prod`, the name of both demo "
        "repositories that live outside this tree (`cpl-nl2sql`, `cpl-mcp`) "
        "and of their intelligence repository. Nothing generic spells those "
        "three letters as a standalone segment: the only things in this tree "
        "that contain them otherwise are our own `_McpLoop` and "
        "`_NarratingAsyncPlanner`, which the alphanumeric boundary excludes, "
        "and an npm integrity hash, which it excludes too. Case-insensitive "
        "because `CPL` and `cpl` are one name written twice.",
    ),
    Term(
        "equinor",
        "The client company, named outright in five lines across four "
        "documents. There is no reading of this word that is not the company: "
        "it is a proper noun with one referent, it is the single term on the "
        "inventory whose presence would be a disclosure even with every other "
        "word removed, and no public example this repository would ever want "
        "to ship has a reason to say it. It is also the one term where a "
        "reader could plausibly argue for leaving a mention in place — a "
        "credit, an acknowledgement — which is exactly why it is refused "
        "rather than left to judgement in seventy separate places.",
    ),
    Term(
        "bouvet",
        "The employer through whom the engagement runs. Zero occurrences "
        "today, and it is on the list precisely because of that: a term the "
        "gate has never fired on is a term nobody has had a chance to "
        "normalise, and the cheapest moment to forbid a word is before it "
        "appears. The standing instruction is that `~/Bouvet/` is a different "
        "employer's codebase from which nothing is ever copied, so a mention "
        "arriving in this tree would mean something had been. It costs one "
        "line and one regex to make that arrival loud instead of silent.",
    ),
    Term(
        "dark_fleet",
        "A lens in the client's deployment, carrying its own `SCHEMA.yaml` "
        "and its own declared grain. The underscore is the whole argument: "
        "'dark fleet' as two English words is ordinary maritime industry "
        "vocabulary and is not refused, while `dark_fleet` is the snake_case "
        "identifier of one named object in one private deployment. The rule "
        "matches the identifier and leaves the English alone, which is the "
        "same distinction the boundary rule draws everywhere else in this "
        "table.",
    ),
    Term(
        "cargoflow",
        "`sm.cargoflow_latest` — a table invented inside the client's "
        "warehouse, and the name of the lens over it. It is a coined "
        "compound: no dictionary, no public schema and no other project in "
        "this tree uses it, so a match is never ambiguous. It reaches 26 "
        "files here almost entirely as fixture data in tests that needed a "
        "realistic table name, which is how a private identifier ends up in "
        "a public tree without anybody deciding it should.",
    ),
    Term(
        "area_counts",
        "`sm.area_counts_dark_v1r0` — the client's geofence x day x IMO fact "
        "table, and the object behind the counted-rows defect this repository "
        "documents at length. Like `cargoflow` it is a coined compound with "
        "one referent. It is worth refusing separately rather than leaning on "
        "`cpl` because the defect it illustrates is genuinely valuable "
        "writing: `03` should reach the chinook analogue for it rather than "
        "delete the lesson, and a term that fires by itself is what makes "
        "that file appear on the worklist in its own right.",
    ),
    Term(
        "zee-lab",
        "A research directory inside the employer's own repository, read "
        "read-only and written up in two documents here. Not on the map's "
        "measured inventory — it was found while checking whether the seven "
        "measured terms were sufficient, and it is the answer to that check "
        "being 'almost'. It is a coined kebab-case name with no English "
        "reading, it names a place inside somebody else's codebase, and it "
        "adds no files to the worklist because both documents are already "
        "refused for `cpl` — which is the argument for adding it: it costs "
        "nothing now and stops the name outliving the pass.",
    ),
)

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
        "every mapping and logistics product there is. `geofences_latest` is "
        "a client table and is refused through its catalogue prefix when it "
        "appears fully qualified; the word itself identifies nothing. 20 "
        "files, and refusing them would mean a public workflow tool could not "
        "carry a worked spatial example, which is a real cost paid for no "
        "protection at all.",
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
        "The phrase that does disclose is the stack — 'the CPL lens on "
        "Databricks' — and that contains a refused term and is refused for "
        "it, which is the per-term rule doing exactly the work a "
        "co-occurrence rule was proposed for. The three files carrying it "
        "with no refused term were read: two name the vendor, one names "
        "`DATABRICKS_TOKEN`, which is a credential variable and not a value, "
        "and naming the variable is the standing rule rather than a breach "
        "of it.",
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


def _pattern(word: str) -> re.Pattern[str]:
    """A term matches where it is not flanked by a letter or a digit.

    Not `\\b`: `_` is a word character, so `\\b` would miss `ms_cpl_app_prod`,
    which is the most identifying string in the tree. Not a substring either,
    which would refuse `_McpLoop` and an npm integrity hash.
    """
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", re.IGNORECASE)


REFUSED_PATTERNS = {term.word: _pattern(term.word) for term in REFUSED}


def refused_terms_in(text: str) -> list[str]:
    """Every refused term appearing in `text`, sorted. The whole matcher."""
    return sorted(word for word, pattern in REFUSED_PATTERNS.items() if pattern.search(text))


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

    Contents and path both, against one list. Commit messages are not checked
    and never will be — see this module's docstring.
    """
    found: dict[str, list[str]] = {}
    for relative in tracked_files():
        if relative == THIS_FILE:
            continue
        absolute = REPO / relative
        if not absolute.is_file():
            continue
        terms = sorted(set(refused_terms_in(relative)) | set(refused_terms_in(_read(absolute))))
        if terms:
            found[relative] = terms
    return found


def test_no_tracked_file_names_an_engagement() -> None:
    """The gate. It refuses; it does not rewrite.

    Red today by design — `publishable/03` is the pass, and this failure is
    its worklist and its definition of done.
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
        "analogue, not an abstraction. `1,454,449 dark vessels` becomes "
        "`3,503 artists` — the same defect, reproducible by anyone who clones "
        "the repository. Where no analogue exists, delete the number rather "
        "than blur it, and never invent one. A whole document about the "
        "client's warehouse is usually deleted, not scrubbed.\n"
        "What is NOT a defect: `vessel`, `geofence`, `IMO`, `Databricks` and "
        "`chinook` are permitted by name, with the argument, in this file's "
        "`PERMITTED` table. If one of them is what you came here to add to "
        "`REFUSED`, read its paragraph first."
    )


class TestTheBoundaryIsAlphanumericAndNotWordBoundary:
    """Both halves are load-bearing, and both were found in the real tree."""

    def test_a_bare_term_is_refused(self) -> None:
        assert refused_terms_in("the cpl lens") == ["cpl"]

    def test_case_does_not_matter(self) -> None:
        assert refused_terms_in("CPL") == ["cpl"]

    def test_a_snake_case_segment_is_refused(self) -> None:
        # `\b` does not fire here, because `_` is a word character. This is
        # the client's warehouse catalogue and the reason for the lookarounds.
        assert refused_terms_in("ms_cpl_app_prod.shipping.dim_vessel_latest") == ["cpl"]

    def test_a_kebab_case_segment_is_refused(self) -> None:
        assert refused_terms_in("cpl-nl2sql") == ["cpl"]

    def test_our_own_class_names_are_not_refused(self) -> None:
        # A substring rule refuses all three of these, in our own source.
        assert refused_terms_in("_McpLoop _NarratingAsyncPlanner _SlowSyncPlanner") == []

    def test_a_lockfile_hash_is_not_refused(self) -> None:
        # Real, from `package-lock.json`: `CPL` between two digits.
        assert refused_terms_in("sha512-1quofZ2RQ9EWdeN34S79+KExV1764+wCUGop5CPL1WG") == []

    def test_the_english_phrase_survives_the_identifier_ban(self) -> None:
        assert refused_terms_in("the dark fleet sails") == []
        assert refused_terms_in("lens `dark_fleet`") == ["dark_fleet"]


class TestThePermittedWordsArePermitted:
    """`01`'s second class, asserted rather than merely absent from the first."""

    @pytest.mark.parametrize("term", PERMITTED, ids=lambda term: term.word)
    def test_a_permitted_word_alone_passes(self, term: Term) -> None:
        assert refused_terms_in(f"a sentence about {term.word} and nothing else") == []

    def test_chinook_is_what_the_public_repository_exists_to_demonstrate(self) -> None:
        # The exclusion the ticket asked for by name. A gate that refused here
        # would refuse `workflows/chinook-assistant`, the best thing we ship.
        assert refused_terms_in("workflows/chinook-assistant/data/Chinook_Sqlite.sqlite") == []

    def test_a_maritime_example_is_not_a_disclosure(self) -> None:
        assert refused_terms_in("count the vessels inside each geofence by IMO") == []

    def test_naming_a_vendor_is_not_a_disclosure(self) -> None:
        assert refused_terms_in("answered against Databricks using DATABRICKS_TOKEN") == []

    def test_no_word_is_in_both_tables(self) -> None:
        assert not {term.word.lower() for term in PERMITTED} & {
            term.word.lower() for term in REFUSED
        }


class TestTheGateCoversWhatTheInventoryFound:
    """Four kinds of hiding place, because the inventory found all four."""

    def test_it_reads_file_contents(self) -> None:
        assert "CHANGELOG.md" in unpublishable_files()

    def test_it_reads_paths_a_content_grep_never_sees(self) -> None:
        path = "docs/decisions/an-agent-that-reaches-cpl-through-mcp.md"
        assert "cpl" in refused_terms_in(path)

    def test_it_reads_the_changelog_whose_job_is_to_recount_history(self) -> None:
        # The likeliest place for a client name to survive a prose pass.
        assert "CHANGELOG.md" in unpublishable_files()

    def test_it_reads_bytes_so_fixture_data_cannot_hide(self) -> None:
        # "No fixture data carries client rows" was measured, and "none today"
        # is not a rule. Binaries are decoded latin-1 and scanned, which costs
        # nothing: zero of the seven tracked binaries match.
        assert refused_terms_in(b"\x00\x01cargoflow\xff".decode("latin-1")) == ["cargoflow"]

    def test_the_corpus_is_tracked_files_so_scratch_is_out(self) -> None:
        assert not any(path.startswith(".scratch/") for path in tracked_files())


class TestTheExclusionsCostSomethingVisible:
    """An exemption that costs nothing gets taken, and then the gate is furniture."""

    def test_the_only_content_exclusion_is_this_file(self) -> None:
        # Widening this is a diff somebody reads, which is the whole mechanism.
        assert THIS_FILE == "backend/tests/test_the_tree_is_publishable.py"

    def test_every_refused_term_is_actually_spelled_out_here(self) -> None:
        # The price of the self-exclusion: the declaration has to be real.
        source = Path(__file__).read_text(encoding="utf-8")
        for term in REFUSED:
            assert term.word in source

    @pytest.mark.parametrize("term", REFUSED + PERMITTED, ids=lambda term: term.word)
    def test_every_term_carries_its_argument(self, term: Term) -> None:
        # Length is a crude proxy for "somebody actually thought about this",
        # and a crude proxy beats none. Same threshold as the censuses.
        assert len(term.reason.strip()) > 400
