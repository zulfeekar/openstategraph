#!/usr/bin/env python3
"""Is it safe to start the next ticket?

A chained ticket loop — one session hands to the next with no human between —
fails in one specific way: a fix that is wrong lands, and the session after it
builds on top. Nobody notices until something much later goes strange. So the
chain gets a gate, and the gate is a script rather than a list in a skill,
because a list says *check these* and a script *fails*.

    python3 scripts/loop_gate.py

Checks, all of them cheap next to the session they guard:

1. **HEAD carries a `Ticket:` trailer.** A ticket-loop session that committed
   without one is invisible to `ticket_ledger.py` in both directions — the
   drift class demonstrated on 2026-08-20, when `organisms-first-class/10` read
   `open` for work that had fully shipped in three untrailered commits.
2. **The ledger agrees with git.** This subsumes "did the session close its
   ticket": a trailer whose ticket still says open is exactly what check 1 of
   the ledger reports.
3. **The working tree grew nothing new.** Running the product writes files —
   disk autosave rewrites a package on every edit the editor makes — and the
   ones that matter are the ones nobody committed and nobody meant. The first
   run records what is already dirty (other sessions leave modified and
   untracked files here constantly, and staging by path is this repository's
   rule); every run after fails on anything that was not there before.

   This deliberately does **not** use `session_guard.py`'s fingerprint.
   That tool answers *"what did **my** session move"* from a snapshot taken at
   its start, and in a chain the snapshot belongs to whichever session ran
   last — so by the time the gate asks, every earlier session's legitimate
   commit looks like an intruder. Asked at the wrong moment it fails a clean
   chain, which is worse than not asking: a gate that cries wolf gets
   disabled. `session_guard` stays the in-session tool; the gate uses git.
4. **Both suites.** Not one. A backend fix with a green pytest and an unrun
   vitest has been shipped here more than once.
5. **The handoff moved.** Checked by mtime against the *previous* commit,
   because `.scratch/` is gitignored and a diff cannot see it. A ticket closed
   without a handoff entry is a ticket the next session does not know is
   closed.

6. **The three CI jobs that broke on 2026-08-23 while this gate said PASS**
   (launch-readiness 13): `frontend`'s static checks (typecheck/lint/format —
   not the duplicate vitest, already run above), `gallery-diagrams-check`'s
   two `--check` scripts, and `clean-install`'s wheel-build-and-serve proof.

What it still does not check — printed by name at the end of every run
(`CI_COVERAGE`, checked against `.github/workflows/ci.yml` by
`backend/tests/test_loop_gate_ci_coverage.py` so the list cannot drift silently):
`generated-port-specs`, `generated-openapi`, `e2e`, and `docs-freshness`
(PR-only). A green gate says which of CI's jobs it did **not** run — never
silently, which was the actual defect, not merely narrowness.

What no check here can tell you, CI included: whether the fix is *right*.
Only a person, or the browser pass, does that.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class _JobCoverage:
    run: bool
    reason: str


#: launch-readiness 13. `loop_gate.py` answers a narrower question than CI
#: does; this table is the honest statement of the gap, checked against
#: `.github/workflows/ci.yml` by `backend/tests/test_loop_gate_ci_coverage.py`
#: so a job CI grows and this table has never heard of is a red test rather
#: than a silent hole. `ci-success` is the aggregator and is deliberately
#: absent — it runs none of its own work.
CI_COVERAGE = {
    "frontend": _JobCoverage(True, "typecheck + lint + format:check below (not the duplicate vitest — already run)"),
    "clean-install": _JobCoverage(True, "scripts/clean_install_proof.sh below (~40s with a warm dist/)"),
    "gallery-diagrams-check": _JobCoverage(True, "the two diagram --check scripts below; CI also runs build_module_index and build_site --check, which are cheap and not repeated here"),
    "backend": _JobCoverage(True, "pytest below covers it; ruff/mypy run separately (see docs/building-an-atom.md)"),
    "generated-port-specs": _JobCoverage(False, "regenerates port_specs.json and diffs it — not run here"),
    "generated-openapi": _JobCoverage(False, "regenerates docs/openapi.json and diffs it — not run here"),
    "e2e": _JobCoverage(False, "Playwright — not run here, too slow for every session"),
    "docs-freshness": _JobCoverage(False, "PR-only (if: pull_request); this repo pushes straight to main"),
}


def ci_coverage_report() -> str:
    lines = ["  what CI runs that this gate does not:"]
    not_run = [name for name, cov in CI_COVERAGE.items() if not cov.run]
    if not not_run:
        lines.append("        (nothing — every CI job is covered)")
    for name in sorted(not_run):
        lines.append(f"        {name} — {CI_COVERAGE[name].reason}")
    return "\n".join(lines)


#: Seconds a gate step may take before it is reported rather than waited on.
#: The suites take 85–95s and ~10s respectively, measured five times, so these
#: are large multiples: a slow machine must never trip them, and a hang must
#: never be indistinguishable from patience. `workflow-gallery` 60 is why they
#: exist — a nested `pytest` with no deadline stalled this gate through four
#: attempts, and a gate that hangs teaches whoever runs the loop to stop
#: trusting it, which is worse than one that fails.
DEADLINES = {"pytest": 600, "vitest": 300, "default": 180}


class _TimedOut(Exception):
    """A step that ran out of time. Distinct from a step that failed."""


def _run(cmd: list[str], *, deadline: int | None = None, **kw) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=deadline or DEADLINES["default"],
            **kw,
        )
    except subprocess.TimeoutExpired as expired:
        raise _TimedOut(f"no answer in {expired.timeout:.0f}s") from expired


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
    print(f"        HEAD touched {len(changed)} file(s) — read them, no script can")

    dirty = {ln[3:] for ln in _run(["git", "status", "--short"]).stdout.splitlines() if ln[3:]}
    baseline_file = REPO / ".scratch" / ".loop-gate-baseline"
    if not baseline_file.exists():
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text("\n".join(sorted(dirty)))
        _report(True, "working tree baseline recorded", f"{len(dirty)} path(s) already dirty")
    else:
        known = {ln for ln in baseline_file.read_text().splitlines() if ln}
        new_dirty = sorted(dirty - known)
        ok &= _report(
            not new_dirty,
            "the working tree grew nothing new",
            ", ".join(new_dirty[:3]) if new_dirty else "",
        )

    try:
        py = _run([sys.executable, "-m", "pytest", "-q"], deadline=DEADLINES["pytest"])
        ok &= _report(py.returncode == 0, "pytest", (py.stdout.strip().splitlines() or [""])[-1])
    except _TimedOut as timed_out:
        ok &= _report(False, "pytest TIMED OUT", f"{timed_out} — see workflow-gallery 60")

    try:
        ts = _run(["npx", "vitest", "run"], deadline=DEADLINES["vitest"])
        ok &= _report(ts.returncode == 0, "vitest", "green" if ts.returncode == 0 else "red")
    except _TimedOut as timed_out:
        ok &= _report(False, "vitest TIMED OUT", str(timed_out))

    # The three checks below close launch-readiness 13: 2026-08-23's push
    # failed exactly these three CI jobs while every one of twenty sessions
    # had ended on this gate saying PASS. All three are seconds-to-tens-of-
    # seconds, measured on this machine (frontend static checks ~9s,
    # gallery-diagrams-check ~7s, clean-install ~40s with a warm dist/) —
    # cheap next to the ~100s pytest+vitest above already pay.
    try:
        fe = _run(["npm", "run", "typecheck"], deadline=120)
        fe_ok = fe.returncode == 0
        if fe_ok:
            fe = _run(["npm", "run", "lint"], deadline=120)
            fe_ok = fe.returncode == 0
        if fe_ok:
            fe = _run(["npm", "run", "format:check"], deadline=60)
            fe_ok = fe.returncode == 0
        ok &= _report(fe_ok, "frontend static checks (typecheck + lint + format:check)", (fe.stdout.strip().splitlines() or [""])[-1] if not fe_ok else "")
    except _TimedOut as timed_out:
        ok &= _report(False, "frontend static checks TIMED OUT", str(timed_out))

    try:
        gallery = _run([sys.executable, "scripts/build_gallery_diagrams.py", "--check"], deadline=90)
        g_ok = gallery.returncode == 0
        if g_ok:
            bts = _run([sys.executable, "scripts/build_behind_the_scenes.py", "--check"], deadline=90)
            g_ok = bts.returncode == 0
        ok &= _report(g_ok, "gallery-diagrams-check (both --check scripts)")
    except _TimedOut as timed_out:
        ok &= _report(False, "gallery-diagrams-check TIMED OUT", str(timed_out))

    try:
        ci_proof = _run(["bash", "scripts/clean_install_proof.sh"], deadline=300)
        ok &= _report(
            ci_proof.returncode == 0,
            "clean-install proof",
            (ci_proof.stdout.strip().splitlines() or [""])[-1] if ci_proof.returncode != 0 else "",
        )
    except _TimedOut as timed_out:
        ok &= _report(False, "clean-install proof TIMED OUT", str(timed_out))

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
    print(ci_coverage_report())
    print()
    print("gate: PASS — the next ticket may start" if ok else "gate: FAIL — stop the chain")
    print("(a green gate says nothing about whether the fix is right)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
