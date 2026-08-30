"""No tracked file carries the absolute home directory of whoever wrote it.

A sibling of `test_the_tree_is_publishable.py` and deliberately **not** a row
in it. That gate refuses *words that identify an engagement*, and its whole
design is a hand-argued term table: every entry carries a paragraph saying why
that word has one referent. A machine path is the opposite kind of thing —
there is no word to argue about, only a **shape**, and the shape is the same
whoever the person is. Folding it in would have meant either an argument
paragraph for a person's login name (which dates the moment they get a new
laptop) or a second matcher inside a module whose one job is the first one.

## What it is, and why it is worth a census of its own

`publishable/04` retired `.coverage` for exactly this defect one layer down —
"a build artifact with no reader, carrying the absolute paths of whichever
machine produced it". The rule was written into `.gitignore` for that one
file and nothing looked for the same thing in prose. It was there:

    docs/decisions/stranger-install-2026-08-24-run4.md:10

recorded an isolation step as `cp /Users/<the author>/dyflow/.env …`, which
publishes a login name, a machine layout, and the fact that a real `.env` sat
at that path — none of which the reproduction needs, since the line means
"copy your own credentials in" and reads better saying so.

`CLAUDE.md` names the same defect from the other end, in "Worktree economy":
an absolute path written into a document went stale when the checkout moved,
the copy-pasted command failed obscurely, and the recovery was the `npm
install` that section exists to prevent. So a home path in a tracked file is
both a small disclosure and a small trap, and one census catches both.

## The shapes, and the one exemption

Three, because a repository read on three platforms can acquire any of them:
`/Users/<name>` (macOS), `/home/<name>` (Linux), `C:\\Users\\<name>` (Windows).
Zero of the second and third exist today, and they are here for the reason
the other gate's table carries the terms it does: the cheapest moment to
forbid a shape is before anything has had a chance to normalise it.

This file deliberately names **no** engagement term. It ran red on the
publishable gate the moment it landed, for quoting one as an illustration —
which is the gate working, and is why the sentence above now points at that
table rather than reproducing a row from it (`publishable/05`).

**Placeholders are permitted by name**, because a document that writes
`/Users/you/project` in an example is doing the right thing and an instrument
that fails on it would be routed around within a week. The list is short and
each entry is a word no real account is likely to be called.

**The only file exempt from the scan is this one**, which has to spell the
shapes out to look for them — the same mechanism, and the same price, as the
gate next door: widening the exemption is a diff somebody reads.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve().relative_to(REPO).as_posix()

#: Home-directory prefixes, one per platform this tree is read on.
HOME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/Users/([A-Za-z0-9][A-Za-z0-9._-]*)"),
    re.compile(r"/home/([A-Za-z0-9][A-Za-z0-9._-]*)"),
    re.compile(r"[Cc]:\\Users\\([A-Za-z0-9][A-Za-z0-9._-]*)"),
)

#: Names that are obviously a stand-in rather than an account. An example
#: showing where a home directory goes is good documentation; refusing it
#: would make this census the kind of instrument people suppress.
PLACEHOLDERS: frozenset[str] = frozenset(
    {"you", "user", "username", "me", "name", "someone", "your-name", "youruser"}
)


def home_paths_in(text: str) -> list[str]:
    """Every non-placeholder home directory named in `text`, sorted."""
    found: set[str] = set()
    for pattern in HOME_PATTERNS:
        for match in pattern.finditer(text):
            if match.group(1).lower() not in PLACEHOLDERS:
                found.add(match.group(0))
    return sorted(found)


def tracked_files() -> list[str]:
    """The corpus: `git ls-files`, so `.scratch/` is out because it is untracked."""
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("The corpus is `git ls-files`, and this checkout has no git.")
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return [path for path in listing.split("\0") if path]


def _read(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def files_naming_a_machine() -> dict[str, list[str]]:
    """Every tracked file carrying somebody's home directory, and which."""
    found: dict[str, list[str]] = {}
    for relative in tracked_files():
        if relative == THIS_FILE:
            continue
        absolute = REPO / relative
        if not absolute.is_file():
            continue
        paths = home_paths_in(_read(absolute))
        if paths:
            found[relative] = paths
    return found


def test_no_tracked_file_names_a_machine() -> None:
    """The census. Like its sibling it refuses; there is no autofix here."""
    offenders = files_naming_a_machine()

    assert not offenders, (
        f"{len(offenders)} tracked files carry the home directory of the "
        "machine that wrote them.\n\n"
        + "\n".join(f"  {path}  ->  {', '.join(hits)}" for path, hits in sorted(offenders.items()))
        + "\n\nA home path in a document publishes a login name and a machine "
        "layout the reader does not need, and it goes stale the moment the "
        "checkout moves — `CLAUDE.md`'s 'Worktree economy' records what that "
        "costs. Write what the step means instead: 'copy your own .env in', "
        "or a placeholder from `PLACEHOLDERS`."
    )


class TestTheShapeIsWhatMatchesAndNotAName:
    def test_a_macos_home_is_refused(self) -> None:
        assert home_paths_in("cp /Users/ada.lovelace/proj/.env /tmp/x") == ["/Users/ada.lovelace"]

    def test_a_linux_home_is_refused(self) -> None:
        assert home_paths_in("PYTHONPATH=/home/ada/src") == ["/home/ada"]

    def test_a_windows_home_is_refused(self) -> None:
        assert home_paths_in(r"C:\Users\Ada\Desktop") == [r"C:\Users\Ada"]

    def test_a_placeholder_is_documentation_and_passes(self) -> None:
        assert home_paths_in("put it in /Users/you/projects and /home/user/bin") == []

    def test_a_path_that_is_not_a_home_directory_is_left_alone(self) -> None:
        # `/tmp`, `/var/lib`, `/usr/local` name no person and are ordinary
        # documentation; the census is about the per-user directory only.
        assert home_paths_in("export OPENSTATEGRAPH_STATE_DIR=/var/lib/openstategraph") == []
        assert home_paths_in("mkdir -p /tmp/stranger4 && cd /usr/local/bin") == []


class TestTheExemptionCostsSomethingVisible:
    def test_the_only_exclusion_is_this_file(self) -> None:
        assert THIS_FILE == "backend/tests/test_no_tracked_file_names_a_machine.py"

    def test_every_placeholder_is_a_word_and_not_a_pattern(self) -> None:
        # A placeholder is compared as a whole segment, lowercased. A regex
        # here would be a second matcher nobody asked for.
        for word in PLACEHOLDERS:
            assert word == word.lower() and " " not in word
