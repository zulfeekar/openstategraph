"""Every tracked binary is here by a decision somebody wrote down.

`publishable/04`. The engagement gate next door
(`test_the_tree_is_publishable.py`) refuses **words**, and its corpus walk was
the first full enumeration of the tracked tree in a while. It found two files
that should not reach a public repository for reasons that have nothing to do
with a client's name:

- **`.coverage`** — a coverage run's sqlite database. A build artifact with no
  reader, rewritten by whichever machine ran the suite last, carrying that
  machine's absolute paths.
- **a third party's Substack article, committed at the repository root as a
  PDF** — somebody else's copyrighted work, redistributed verbatim. That is
  the reason it had to go, and it is a stronger reason than tidiness: a
  private beta holding a downloaded article is one thing, and a public
  repository republishing it is a licence question nobody asked the author.

Neither carries a refused term, so the word gate is green on both **forever**.
That is the gap this file closes, and the shape of the closure is the whole
design question.

## Why this is a census and not a second phrase gate

The tempting rule is "refuse things nobody meant to commit". It cannot be
written. *Meant* is not a property of a file, so any approximation — a size
threshold, an extension blocklist, a name that looks like an artifact — fires
on files that are genuinely wanted, and this repository has recorded what
happens next: an instrument that fails wrongly gets suppressed, and then it
measures nothing. `test_the_tree_is_publishable.py` rejected a co-occurrence
rule for exactly this reason and said so at length.

What *is* a property of a file is whether it is text. Both offenders were
binary, and so is every future instance of this class worth catching: a
database, a downloaded document, a screenshot, a vendored wheel. Adding a
binary to a repository is rare, deliberate and visible in review — so a census
over them can be **ceiling zero with recorded exceptions**, which is the shape
this repository already uses for module size, public surface and dispatch
targets. It never fires on prose. It fires exactly once per new binary, at the
moment somebody adds one, and the fix is to write the argument down.

So the rule is not "no binaries". It is **no binary without a paragraph**, and
the paragraph is the review.

## Binary means what the word gate already means by it

`test_the_tree_is_publishable._read` decodes UTF-8 and falls back to latin-1;
a file is binary here when that first decode fails. Reusing the discriminator
rather than inventing one matters more than it looks: git's own heuristic is
"a NUL byte in the first 8000", and under *that* rule two of our TypeScript
sources are binary — `src/canvas/features/portAffordance.ts` and
`src/core/serialization/UnknownNode.ts` both use a literal `\\x00` as a key
separator, with a comment explaining why. A census that listed two hand-written
`.ts` files among the binaries would be asking for an argument nobody should
have to write. UTF-8 decodability draws the line where a reader would.

## What the census cannot see, stated rather than implied

A text file that nobody meant to commit is invisible here — a stray log, a
pasted transcript, a `.env.example` with a real value in it. The last of those
has its own gate; the others do not, and no rule proposed for them survived the
false-failure test above. Recorded as a gap, in the manner this repository
records gaps, rather than papered over with a rule that would be suppressed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from test_the_tree_is_publishable import tracked_files

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Binary:
    """A tracked file that is not text, and the argument for keeping it."""

    path: str
    reason: str


ALLOWED: tuple[Binary, ...] = (
    Binary(
        "backend/openstategraph/examples/sql-qa/data/Chinook_Sqlite.sqlite",
        "The canonical public sample database, shipped so the SQL example runs "
        "the moment somebody clones the repository. It is data a reader is "
        "meant to query rather than an artifact a machine produced: it has a "
        "documented schema, it is byte-stable across runs, and the whole "
        "`sql-qa` example is unreproducible without it. `scripts/fetch_chinook.sh` "
        "exists and downloading at first run was considered — it was rejected "
        "because it makes the example depend on a network and on somebody "
        "else's hosting, which is the failure mode a bundled fixture exists to "
        "avoid. A megabyte, once, in exchange for an example that works "
        "offline and forever.",
    ),
    Binary(
        "workflows/chinook-assistant/data/Chinook_Sqlite.sqlite",
        "The same database, beside the workflow package that queries it. The "
        "duplication is deliberate and is the package contract doing its job: "
        "a `workflows/<slug>/` directory is the portable unit — copied, "
        "mounted, run from anywhere Python runs — so a package reaching "
        "sideways into `backend/openstategraph/examples/` for its data would "
        "make it portable in name only. `chinook-assistant` is also the public "
        "analogue the publishable map is built around, the one worked example "
        "any reader can reproduce, so of all the files in the tree this is the "
        "one least worth trading for a megabyte.",
    ),
    Binary(
        "docs/decisions/images/edge-legibility-before.png",
        "A screenshot in a decision record, and the before of a before/after "
        "pair about edge legibility on the canvas. A decision about whether "
        "lines are readable cannot be recorded in prose: the evidence *is* the "
        "picture, and a reader asked to accept 'the edges were hard to follow' "
        "on our word has been given an assertion instead of a record. It is "
        "also the class of binary that never changes again — a decision record "
        "is history, so this file is written once and then only read, which is "
        "the opposite of the artifact this census exists to catch.",
    ),
    Binary(
        "docs/decisions/images/edge-legibility-after.png",
        "The after of that pair, and the half that carries the claim. The "
        "decision record argues that a particular routing change made edges "
        "followable; this image is what makes that argument checkable rather "
        "than asserted, and a reader who disagrees with it can say so from the "
        "same evidence the author had. Kept beside its before for the same "
        "reason both were committed at once: either alone is a picture, and "
        "only the pair is an argument.",
    ),
    Binary(
        "docs/decisions/images/edge-legibility-remaining.png",
        "The third of the set, and the most valuable one: what the change did "
        "*not* fix. A decision record that ships only its success is "
        "marketing, and this repository's standing habit is to write down the "
        "residue — the gate that cannot see something, the ticket left "
        "`partially` resolved, the number that is a gap rather than a list. "
        "This image is that habit in a directory where the medium happens to "
        "be a screenshot, and dropping it would leave the record claiming more "
        "than the work earned.",
    ),
)

ALLOWED_PATHS = frozenset(entry.path for entry in ALLOWED)


def _is_text(path: Path) -> bool:
    """The word gate's own discriminator: does this decode as UTF-8?

    Not git's NUL heuristic — see this module's docstring for the two
    TypeScript files that would fail it.
    """
    try:
        path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def tracked_binaries() -> list[str]:
    """Every tracked file that is not text, sorted. The whole census."""
    found = []
    for relative in tracked_files():
        absolute = REPO / relative
        if absolute.is_file() and not _is_text(absolute):
            found.append(relative)
    return sorted(found)


def test_the_census_found_something_to_count() -> None:
    """A discriminator that silently matches nothing makes this file green and
    empty, which is the one answer it must never be able to give."""
    assert tracked_binaries()


def test_no_tracked_binary_is_here_without_an_argument() -> None:
    """Ceiling zero, exceptions recorded with their reasons above."""
    undeclared = [path for path in tracked_binaries() if path not in ALLOWED_PATHS]

    assert not undeclared, (
        "these binary files are tracked and nothing in the repository says "
        f"why: {undeclared}\n\n"
        "A binary reaches a public repository as a whole file, so the question "
        "is not whether it is tidy but whether we may republish it. Two "
        "answers are legitimate: add it to `ALLOWED` above with the paragraph "
        "that makes the case, or take it out of the index with "
        "`git rm --cached` and add a `.gitignore` rule so the next careless "
        "`git add` does not bring it back. Deleting from the index is not "
        "deleting from history; if the file was a secret, rotating it is a "
        "separate job this test cannot do for you."
    )


def test_every_declared_binary_is_still_tracked() -> None:
    """The other direction. A stale allowance is an argument for a file that
    is no longer there, and it would quietly re-permit the path if one ever
    came back under the same name."""
    census = set(tracked_binaries())
    assert not [entry.path for entry in ALLOWED if entry.path not in census]


@pytest.mark.parametrize("entry", ALLOWED, ids=lambda entry: entry.path)
def test_every_declared_binary_carries_its_argument(entry: Binary) -> None:
    """Length is a crude proxy for 'somebody actually thought about this', and
    a crude proxy beats none. Same threshold as the censuses next door."""
    assert len(entry.reason.strip()) > 400


def test_a_source_file_that_holds_a_nul_byte_is_not_a_binary() -> None:
    """The discriminator's boundary, pinned against the two real files that
    make git call our own TypeScript binary."""
    for relative in (
        "src/canvas/features/portAffordance.ts",
        "src/core/serialization/UnknownNode.ts",
    ):
        source = REPO / relative
        assert b"\x00" in source.read_bytes()
        assert _is_text(source)
