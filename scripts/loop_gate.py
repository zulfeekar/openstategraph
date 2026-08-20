#!/usr/bin/env python3
"""Is it safe to start the next ticket?

A chained ticket loop — one session hands to the next with no human between —
fails in one specific way: a fix that is wrong lands, and the session after it
builds on top. Nobody notices until something much later goes strange. So the
chain gets a gate, and the gate is a script rather than a list in a skill,
because a list says *check these* and a script *fails*.

    python3 scripts/loop_gate.py

Five checks, all of them cheap next to the session they guard:

1. **HEAD carries a `Ticket:` trailer.** A ticket-loop session that committed
   without one is invisible to `ticket_ledger.py` in both directions — the
   drift class demonstrated on 2026-08-20, when `organisms-first-class/10` read
   `open` for work that had fully shipped in three untrailered commits.
2. **The ledger agrees with git.** This subsumes "did the session close its
   ticket": a trailer whose ticket still says open is exactly what check 1 of
   the ledger reports.
3. **`session_guard.py verify`**, against the files HEAD actually changed.
   Running the product writes files; this is what catches the ones nobody
   meant.
4. **Both suites.** Not one. A backend fix with a green pytest and an unrun
   vitest has been shipped here more than once.
5. **The handoff moved.** Checked by mtime against the *previous* commit,
   because `.scratch/` is gitignored and a diff cannot see it. A ticket closed
   without a handoff entry is a ticket the next session does not know is
   closed.

What it cannot check, stated so nobody reads a green run as more than it is:
whether the fix is *right*. Only a person, or the browser pass, does that.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, **kw)


def _report(ok: bool, label: str, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    print("loop gate")
    ok = True

    body = _run(["git", "log", "-1", "--format=%B"]).stdout
    subject = _run(["git", "log", "-1", "--format=%s"]).stdout.strip()
    trailers = [ln for ln in body.splitlines() if ln.startswith("Ticket:")]
    ok &= _report(bool(trailers), "HEAD carries a Ticket: trailer", subject if trailers else "none")
    for line in trailers:
        print(f"        {line}")

    ledger = _run([sys.executable, "scripts/ticket_ledger.py"])
    agrees = "The ledger and git agree" in ledger.stdout
    ok &= _report(agrees, "ledger agrees with git", ledger.stdout.strip().splitlines()[0])

    changed = [f for f in _run(["git", "show", "--name-only", "--format=", "HEAD"]).stdout.split() if f]
    guard = _run([sys.executable, "scripts/session_guard.py", "verify", *changed])
    ok &= _report(
        guard.returncode == 0,
        f"nothing moved outside HEAD's {len(changed)} file(s)",
        "" if guard.returncode == 0 else guard.stdout.strip().splitlines()[0],
    )

    py = _run([sys.executable, "-m", "pytest", "-q"])
    ok &= _report(py.returncode == 0, "pytest", (py.stdout.strip().splitlines() or [""])[-1])

    ts = _run(["npx", "vitest", "run"])
    ok &= _report(ts.returncode == 0, "vitest", "green" if ts.returncode == 0 else "red")

    handoffs = sorted((REPO / ".scratch").glob("HANDOFF-*.md"))
    if not handoffs:
        ok &= _report(False, "a handoff exists")
    else:
        newest = handoffs[-1]
        previous = int(_run(["git", "log", "-1", "--format=%ct", "HEAD~1"]).stdout.strip() or 0)
        ok &= _report(
            newest.stat().st_mtime > previous,
            f"{newest.name} written since the previous commit",
        )

    print()
    print("gate: PASS — the next ticket may start" if ok else "gate: FAIL — stop the chain")
    print("(a green gate says nothing about whether the fix is right)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
