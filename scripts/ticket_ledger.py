#!/usr/bin/env python3
"""Does the ticket ledger agree with git? — production-ready ticket 57.

Twenty tickets were fixed, committed, pushed and CI-verified while their files
still read ``Status: open`` with no resolution — including a data-loss blocker.
The maps *are* this project's memory across sessions: a ledger that says
``open`` for shipped work makes the next session redo it, and one that says
``resolved`` for unshipped work is worse.

Two things made it possible, and both are structural rather than careless:

* ``.scratch/`` is gitignored, so no diff ever shows a missing resolution;
* an agent reporting "ticket resolved" is *testimony*. A resolution written by
  the session that did the work is evidence, and only if it survives.

So this script never asks an agent. It reads the ticket files and ``git log``
and reports where the two disagree, in three directions:

1. **shipped-but-open** — a commit carries ``Ticket: <map>/<id>`` and that
   ticket's header still says open. This is the twenty, prevented.
2. **resolved-in-body-but-open-in-header** — the file contains a resolution
   section while the header says open. Two of the three drifts found by hand on
   2026-08-18 were exactly this, and it needs no git at all. A header that says
   *partially* resolved is exempt: its resolution section describes the half
   that shipped, which is the honest way to record one.
3. **names a commit git does not have** — a header citing a hash that is not in
   this repository. A resolution reconstructed from a report that was wrong, or
   work that was reverted under a concurrent session (observed live).

**The convention this depends on**, and the whole durable half of the fix: a
commit that resolves a ticket carries a trailer naming it.

    Ticket: production-ready/46

Ticket ids are not globally unique — every map numbers from 01 — so the map
name is part of the id. A commit may carry several trailers. Nothing enforces
the trailer (a hook would fire on every commit in a repository where most
commits resolve nothing); what enforces it is this script being run, which is
why it prints a summary rather than only failing.

Usage::

    python3 scripts/ticket_ledger.py            # report
    python3 scripts/ticket_ledger.py --strict   # exit 1 if anything disagrees
    python3 scripts/ticket_ledger.py --map production-ready
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRATCH = REPO / ".scratch"

#: The trailer a resolving commit carries. `Ticket: production-ready/46`.
TRAILER = re.compile(r"^\s*Ticket:\s*([a-z0-9-]+)/(\d+)\s*$", re.MULTILINE)

#: The header line every ticket opens with — in **either** shape.
#:
#: Two are in use across the maps and this knew one (`production-ready` 62):
#:
#:     Labels: wayfinder:bug · Status: open · Size: M · Map: …
#:     Status: resolved 2026-08-19
#:
#: A standalone line yielded no match, so the status read `(no Status line)`,
#: which carries no closed word — so every ticket written in that style was
#: open forever whatever it said, and twenty-five clean ones were reported as
#: drift. `Labels:` is now the optional prefix it always was.
#:
#: Anchored to the start of a line and **not** `DOTALL`: a sentence in the body
#: that happens to say "Status: resolved" must not be able to close a ticket,
#: and a lazy `.*?` that crossed newlines could pair one ticket's `Labels:`
#: with another line's `Status:`.
STATUS = re.compile(r"^(?:Labels:.*?)?Status:\s*(.+?)(?:·|$)", re.MULTILINE)

#: A 7-40 char hex run in a header, i.e. a cited commit.
HASH = re.compile(r"\b([0-9a-f]{7,40})\b")

#: Words a header uses for "this is finished". `partially resolved` is
#: deliberately *not* here — a partial is open work with a note.
#: `withdrawn` is here because a ticket can end by being *wrong* rather than by
#: being fixed, and that ending needs a word. `launch-readiness/80` reported a
#: product defect that turned out to be a broken test harness — the finding was
#: retracted, the ticket carries the retraction and the lesson, and no commit
#: will ever "resolve" it. Without the word it read as shipped-but-open drift
#: forever, which teaches the two dishonest moves this file exists to prevent:
#: mark it resolved, or quietly drop the trailer.
CLOSED_WORDS = (
    "resolved", "closed", "done", "backlog", "superseded", "declined", "withdrawn",
)

#: A section heading that only a finished ticket would carry.
RESOLUTION_HEADING = re.compile(r"^##+\s*(resolution|what was done|outcome)\b", re.MULTILINE | re.IGNORECASE)


@dataclass(frozen=True)
class Ticket:
    map_name: str
    number: str
    path: Path
    status: str
    body: str

    @property
    def id(self) -> str:
        return f"{self.map_name}/{self.number}"

    @property
    def is_partial(self) -> bool:
        """Half-shipped, and says so. Open work, but a resolution section is
        *expected* — it describes the half that landed.

        **It carries a second meaning, learned by sweeping ten of these on
        2026-08-20, and it is the one that will not be guessed.** A commit's
        trailer says *this commit's work belongs to that ticket*. It does not
        say the ticket is finished, and twice in that sweep it emphatically was
        not: `9be5b53` fixed an impure toast updater under
        `every-workflow-green/26` and the commit message says in its own words
        that the symptom survives; `9dcd90d` shipped the selection and centring
        `31` asked for and the browser check *after* it still read
        `inView: false`.

        There is no fourth report for that, and there should not be — the
        script cannot read a commit message. `partially` is its spelling. An
        `open` header against a trailer is a drift row every run forever, which
        teaches the two dishonest moves this file exists to prevent: mark it
        resolved, or leave the trailer off.

        So the word means *a commit landed under this ticket and the ticket is
        not closed* — whether the half that landed was half the fix or a
        different defect found on the way. What it must never be read as is a
        claim that any part of the reported symptom is gone; that belongs in
        the header sentence, and on 26 and 31 it says so."""
        lowered = self.status.lower()
        # `partial` and `partly` only. "half" was in this list and matched a
        # status whose prose happened to say *"the half the correction names
        # went to ticket 21"* — a resolved ticket reported as open by a word in
        # its own explanation, which is the failure this script exists to
        # prevent, produced by the script.
        return "partial" in lowered or "partly" in lowered

    @property
    def is_open(self) -> bool:
        lowered = self.status.lower()
        if self.is_partial:
            return True
        # `open — the "package" half is resolved` is open, and says so first.
        if lowered.lstrip("* ").startswith("open"):
            return True
        return not any(word in lowered for word in CLOSED_WORDS)


def tickets(map_filter: str | None = None) -> list[Ticket]:
    found: list[Ticket] = []
    for path in sorted(SCRATCH.glob("*/tickets/*.md")):
        map_name = path.parent.parent.name
        if map_filter and map_name != map_filter:
            continue
        number = path.name.split("-", 1)[0]
        body = path.read_text(encoding="utf-8", errors="replace")
        match = STATUS.search(body)
        status = match.group(1).strip() if match else "(no Status line)"
        found.append(Ticket(map_name, number, path, status, body))
    return found


def is_trailer_drift(ticket: Ticket, commits: list[str]) -> bool:
    """Does a commit claim to have resolved a ticket whose header says open?

    **A partial is exempt**, and this function exists so that exemption is
    stated once. It was a comment on the resolution-section check and a silence
    here, so a half-shipped ticket — open by design, carrying trailers by
    design, which is what a partial *is* — was reported as drift for being
    recorded honestly (`production-ready` 65). A rule that punishes the honest
    spelling teaches the dishonest one: mark it resolved, or leave the trailer
    off.
    """
    return ticket.is_open and not ticket.is_partial and bool(commits)


def resolving_commits(repo: Path = REPO) -> dict[str, list[str]]:
    """Ticket id → the commits whose trailer names it.

    ``repo`` is the one seam every git call in this module goes through, and it
    exists so a test can build a history instead of asserting about ours —
    `stable-beta-public/35`. It defaults to this checkout, which is what the
    report wants and what every caller in `main` passes.
    """
    log = subprocess.run(
        ["git", "log", "--format=%H%x1f%B%x1e"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    claimed: dict[str, list[str]] = {}
    for entry in log.stdout.split("\x1e"):
        if "\x1f" not in entry:
            continue
        sha, message = entry.split("\x1f", 1)
        for map_name, number in TRAILER.findall(message):
            claimed.setdefault(f"{map_name}/{number}", []).append(sha.strip()[:7])
    return claimed


def missing_ticket_files(
    claimed: dict[str, list[str]], known_ids: set[str], map_filter: str | None = None
) -> list[tuple[str, list[str]]]:
    """The reverse of ``is_trailer_drift`` — production-ready ticket 104.

    Every other check starts from a ticket *file* and asks what git says about
    it. Nothing asked the other direction: a commit's trailer can name a
    ticket id with no file at all, which is exactly what happened to
    `production-ready/100`, `/101` and `/102` — three commits landed, `.scratch/`
    ate the ticket files that recorded them (gitignored, so no diff ever showed
    it), and the next session numbering its ticket from `ls tickets/ | tail -1`
    silently collided with a commit that already claimed the number.

    ``known_ids`` must be the full universe of ticket ids the repository has
    files for, **not** filtered to ``map_filter`` — a trailer naming a real
    ticket in another map is not drift, and checking it against a narrowed set
    would report it as missing. ``map_filter`` narrows only which *rows get
    printed*, exactly as the rest of the report is scoped by ``--map``.
    """
    missing: list[tuple[str, list[str]]] = []
    for ticket_id in sorted(claimed):
        if ticket_id in known_ids:
            continue
        if map_filter and not ticket_id.startswith(f"{map_filter}/"):
            continue
        missing.append((ticket_id, claimed[ticket_id]))
    return missing


def commit_subject(sha: str, repo: Path = REPO) -> str:
    """The commit's own first line, or a placeholder if it is not here.

    Never raises: this is report text, and the "cites a commit this repository
    does not have" check is where a missing commit is *judged*.
    """
    result = subprocess.run(
        ["git", "log", "-1", "--format=%s", sha],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "(no such commit here)"
    return result.stdout.strip() or "(no such commit here)"


def drift_row(ticket: Ticket, commits: list[str], repo: Path = REPO) -> str:
    """One shipped-but-open row, carrying the evidence a reader needs — `21`.

    For five days the ledger printed ``launch-readiness/94  ← 7c776f3`` on
    every run. The row was true and nobody read it: an id and a seven-character
    hash are two opaque tokens, so noticing that a commit about the *step
    budget* had been filed against a ticket about *a skill with two sources*
    cost a deliberate ``git show`` -- and six handoffs paid the cheaper price
    instead and wrote "pre-existing, unchanged".

    So the row prints the commit's own subject line. Nothing new is reported
    and nothing is suppressed: the row already existed and was already correct,
    and the false-positive rate stays zero. What changes is that reading it is
    no longer a separate act, which is the only part of that failure this
    script can own.

    The two heuristics `21` floated -- a trailer whose ticket file was last
    modified long before the commit, a diff touching nothing the ticket names
    -- are deliberately not here. Both would print rows that are usually
    nothing, and a row that is usually nothing is how this one came to be
    skipped.
    """
    lines = [f"{ticket.id} {ticket.path.name}"]
    lines.extend(f"    ← {sha}  {commit_subject(sha, repo)}" for sha in commits)
    return "\n  ".join(lines)


def commit_exists(sha: str, repo: Path = REPO) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=repo,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--map", dest="map_name", help="only this map")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any disagreement")
    args = parser.parse_args(argv)

    if not SCRATCH.is_dir():
        print("no .scratch/ here — nothing to check", file=sys.stderr)
        return 0

    all_tickets = tickets(args.map_name)
    claimed = resolving_commits()
    # The full universe, regardless of --map: a trailer naming a real ticket in
    # another map must not be reported as missing just because this run is
    # scoped to one map's rows.
    known_ids = {t.id for t in tickets(None)}

    shipped_but_open: list[tuple[Ticket, list[str]]] = []
    body_says_done: list[Ticket] = []
    phantom_commits: list[tuple[Ticket, str]] = []

    for ticket in all_tickets:
        commits = claimed.get(ticket.id, [])
        if is_trailer_drift(ticket, commits):
            shipped_but_open.append((ticket, commits))
        # A partial is exempt: its resolution section describes the half that
        # shipped, which is the honest way to record one.
        if ticket.is_open and not ticket.is_partial and RESOLUTION_HEADING.search(ticket.body):
            body_says_done.append(ticket)
        if not ticket.is_open:
            for sha in HASH.findall(ticket.status):
                if not commit_exists(sha):
                    phantom_commits.append((ticket, sha))

    def report(title: str, rows: list[str]) -> None:
        print(f"\n{title} — {len(rows)}")
        for row in rows:
            print(f"  {row}")

    open_count = sum(1 for t in all_tickets if t.is_open)
    scope = args.map_name or "all maps"
    print(f"{len(all_tickets)} tickets in {scope}: {open_count} open, {len(all_tickets) - open_count} not")

    report(
        "Says open, but a commit's trailer resolves it",
        [drift_row(t, c) for t, c in shipped_but_open],
    )
    report(
        "Says open, but the file carries a resolution section",
        [f"{t.id} {t.path.name}" for t in body_says_done],
    )
    report(
        "Cites a commit this repository does not have",
        [f"{t.id} {t.path.name} → {sha}" for t, sha in phantom_commits],
    )
    orphan_trailers = missing_ticket_files(claimed, known_ids, args.map_name)
    report(
        "A commit's trailer names a ticket that has no file",
        [
            "\n  ".join([tid] + [f"    ← {sha}  {commit_subject(sha)}" for sha in commits])
            for tid, commits in orphan_trailers
        ],
    )

    disagreements = (
        len(shipped_but_open) + len(body_says_done) + len(phantom_commits) + len(orphan_trailers)
    )
    if disagreements == 0:
        print("\nThe ledger and git agree.")
    else:
        # `docs-and-gaps/21`. Every row above now carries the commit's own
        # subject, so a row is answerable where it is printed. The one thing
        # that must not happen to it is what happened to the row that stood
        # from 2026-08-26: carried into six handoffs as "pre-existing,
        # unchanged", never opened, hiding a live defect the whole time.
        print(
            "\nA row is opened, not carried. Each one prints the commit that"
            " claims the ticket;\nif the subject and the filename are about"
            " different things, the trailer is wrong\nand the ticket is still"
            " open."
        )
    return 1 if (args.strict and disagreements) else 0


if __name__ == "__main__":
    raise SystemExit(main())
