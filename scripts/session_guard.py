#!/usr/bin/env python3
"""Did this session change anything it did not mean to?

A ticket-loop session runs the product, and running the product **writes
files**. Disk autosave rewrites `workflows/<slug>/workflow.json` on every edit
the editor makes; a browser tab left on a package writes it again on the next
change. That is correct behaviour and it is also how, on 2026-08-20, a
thirteen-node example was replaced by a one-node blank document and another
session's uncommitted work was lost — twice, in one day, both times noticed by
accident rather than by any check.

So: fingerprint before, verify after, and name every file that moved.

    python3 scripts/session_guard.py snapshot          # at the start
    python3 scripts/session_guard.py verify a/b.py …   # at the end, naming
                                                       # the files you meant
                                                       # to change

`verify` exits 1 when a tracked file changed that you did not name, and prints
the `git checkout --` line that puts it back. It is deliberately dumber than a
hook: it reports, it never reverts, because a file this session legitimately
rewrote and a file it destroyed look identical to a script and only differ to
the person who knows what they were doing.

Untracked files are listed but never failed on: other sessions leave them here
constantly, and this repository's rule is stage by path, never `git add -A`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / ".scratch" / ".session-guard.json"


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def _digest(path: Path) -> str | None:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return None  # deleted, or unreadable — both are "not what it was"


def snapshot() -> int:
    marks = {}
    for rel in _tracked():
        digest = _digest(REPO / rel)
        if digest is not None:
            marks[rel] = digest
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(marks))
    print(f"snapshot: {len(marks)} tracked files fingerprinted")
    return 0


def verify(intended: list[str]) -> int:
    if not STATE.exists():
        print("no snapshot — run `session_guard.py snapshot` at the start of a session")
        return 2
    before = json.loads(STATE.read_text())
    allowed = set(intended)

    moved, gone = [], []
    for rel, was in before.items():
        now = _digest(REPO / rel)
        if now == was or rel in allowed:
            continue
        (gone if now is None else moved).append(rel)

    added = [rel for rel in _tracked() if rel not in before and rel not in allowed]

    for label, rows in (("CHANGED", moved), ("DELETED", gone), ("NEW", added)):
        for rel in rows:
            print(f"{label:8} {rel}")

    if not (moved or gone):
        print(f"clean — nothing moved outside the {len(allowed)} file(s) you named")
        return 0

    print()
    print("If any of those were not yours, put them back one at a time:")
    for rel in moved + gone:
        print(f"  git checkout -- {rel}")
    print()
    print("A workflow.json here is usually the editor's disk autosave, which is")
    print("only correct when the canvas held that package's real document.")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "snapshot":
        return snapshot()
    if len(argv) >= 2 and argv[1] == "verify":
        return verify(argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
