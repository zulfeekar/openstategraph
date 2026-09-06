#!/usr/bin/env python3
"""Print every open ticket across every map, newest-first by map then number.

Exists because a handoff's ticket list is a snapshot and goes stale within
hours, while this reads the tickets themselves. Orienting sessions ran a
copy-pasted version of this loop; a pasted script has no way to fail, so it
lives here instead, next to the ledger it complements.

The division of labour: `ticket_ledger.py` answers *do the tickets and git
agree*, and this answers *what is left*. Both read the same files and must
agree about what "open" means, which is why `CLOSED_WORDS` is defined once.

A `partially` ticket is open. That word means the shipped work is real but the
reported symptom survives, so the ticket still has a claim on somebody's time —
treating it as closed is the drift the ledger spends its whole run catching.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

SCRATCH = pathlib.Path(__file__).resolve().parent.parent / ".scratch"

# A header may carry other fields before Status on the same line.
STATUS = re.compile(r"^(?:Labels:.*?)?Status:\s*(.+?)(?:·|$)", re.M)
LABELS = re.compile(r"^Labels:\s*(.+)$", re.M)
SIZE = re.compile(r"Size:\s*([A-Z]+)")
KIND = re.compile(r"wayfinder:([a-z-]+)")

CLOSED_WORDS = (
    "resolved", "closed", "done", "superseded",
    "withdrawn", "rejected", "moved to", "merged into", "backlog",
)

# Ranked by what the defect costs, not by how big it is. A wrong answer
# presented as right is first because a user cannot detect it.
KIND_RANK = {
    "bug": 0, "blocker": 0, "regression": 0,
    "gap": 1, "enhancement": 2, "chore": 3,
    # These end in a judgement and belong to the owner, never to an
    # unattended session. Ranked last so they sort out of the way.
    "question": 9, "grilling": 9, "design": 9, "decision": 9,
}
OWNER_KINDS = {k for k, v in KIND_RANK.items() if v == 9}


def _status_of(text: str) -> str:
    m = STATUS.search(text)
    return m.group(1).strip().lower() if m else "(none)"


def is_open(status: str) -> bool:
    """A ticket is open unless its status says otherwise — `partially` included.

    Note the ordering: `partially resolved` contains "resolved", so the
    prefix check has to win. That is the same trap `ticket_ledger.py` guards,
    and the reason a header carries one status word rather than a phrase.
    """
    if status.startswith("partially"):
        return True
    return not any(w in status for w in CLOSED_WORDS)


def census(root: pathlib.Path = SCRATCH):
    rows = []
    for f in sorted(root.glob("*/tickets/*.md")):
        text = f.read_text(errors="ignore")
        status = _status_of(text)
        if not is_open(status):
            continue
        labels = LABELS.search(text)
        kind = (KIND.findall(labels.group(1)) if labels else []) or ["?"]
        size = SIZE.search(text)
        title = next((l for l in text.splitlines() if l.strip()), "").lstrip("# ").strip()
        num = f.name.split("-")[0]
        rows.append({
            "map": f.parent.parent.name,
            "num": int(num) if num.isdigit() else 0,
            "kind": kind[0],
            "size": size.group(1) if size else "?",
            "status": status,
            "title": title,
            "path": f,
        })
    rows.sort(key=lambda r: (KIND_RANK.get(r["kind"], 5), r["map"], r["num"]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", help="only this map")
    ap.add_argument("--unattended", action="store_true",
                    help="hide tickets that end in a judgement the owner owns")
    args = ap.parse_args()

    rows = census()
    if args.map:
        rows = [r for r in rows if r["map"] == args.map]
    if args.unattended:
        rows = [r for r in rows if r["kind"] not in OWNER_KINDS]

    if not rows:
        print("No open tickets match.")
        return 0

    for r in rows:
        print(f"{r['map']}/{r['num']:<4} {r['kind']:<11} {r['size']:<2} "
              f"{r['status'][:12]:<12} {r['title'][:58]}")

    owner = [r for r in rows if r["kind"] in OWNER_KINDS]
    print(f"\n{len(rows)} open"
          + (f", of which {len(owner)} need the owner's judgement" if owner else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
