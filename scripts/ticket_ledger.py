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
CLOSED_WORDS = ("resolved", "closed", "done", "backlog", "superseded", "declined")

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
        *expected* — it describes the half that landed."""
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


def resolving_commits() -> dict[str, list[str]]:
    """Ticket id → the commits whose trailer names it."""
    log = subprocess.run(
        ["git", "log", "--format=%H%x1f%B%x1e"],
        cwd=REPO,
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


def commit_exists(sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=REPO,
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

    shipped_but_open: list[tuple[Ticket, list[str]]] = []
    body_says_done: list[Ticket] = []
    phantom_commits: list[tuple[Ticket, str]] = []

    for ticket in all_tickets:
        commits = claimed.get(ticket.id, [])
        if ticket.is_open and commits:
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
        [f"{t.id} {t.path.name} ← {', '.join(c)}" for t, c in shipped_but_open],
    )
    report(
        "Says open, but the file carries a resolution section",
        [f"{t.id} {t.path.name}" for t in body_says_done],
    )
    report(
        "Cites a commit this repository does not have",
        [f"{t.id} {t.path.name} → {sha}" for t, sha in phantom_commits],
    )

    disagreements = len(shipped_but_open) + len(body_says_done) + len(phantom_commits)
    if disagreements == 0:
        print("\nThe ledger and git agree.")
    return 1 if (args.strict and disagreements) else 0


if __name__ == "__main__":
    raise SystemExit(main())
