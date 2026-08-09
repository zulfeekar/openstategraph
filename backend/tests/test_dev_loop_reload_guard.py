"""Pins the dev loop against the "the run never ends" wedge (ticket 11).

Diagnosed live, end to end:

1. The store-analytics report branch's happy path calls the email tool, which
   writes `workflows/_outbox/<stamp>.eml` — **inside** `--reload-dir workflows`.
   Mounting a workflow package writes `workflows/<slug>/__pycache__/*.pyc`
   there too.
2. uvicorn's reloader reacted with "Shutting down / Waiting for connections to
   close." An SSE response never closes on its own, so the graceful wait never
   returned and no replacement server child was ever spawned.
3. The reloader parent kept the :8000 listener, so every subsequent request
   hung forever — the live run, the next run, and `/api/health` alike.

Two independent guards, so neither alone has to be perfect: the runtime's own
output paths are excluded from the watcher, and the graceful shutdown is
bounded so a *genuine* source edit restarts the server rather than wedging it.

This is a source-level pin in the same spirit as the 2026-08 audit's
single-writer pin on `question`: the thing being protected is a fact about the
process topology, and the cheapest honest way to keep it true is to fail the
moment the invocation stops saying it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEV_SH = ROOT / "scripts" / "dev.sh"


@pytest.fixture(scope="module")
def uvicorn_invocation() -> str:
    """The `supervise backend ... uvicorn ...` command, line continuations joined."""
    text = DEV_SH.read_text()
    joined = re.sub(r"\\\n\s*", " ", text)
    for line in joined.splitlines():
        if "supervise backend" in line and "uvicorn" in line:
            return line
    raise AssertionError("scripts/dev.sh no longer starts uvicorn via `supervise backend`")


class TestReloadExcludesTheRuntimesOwnOutput:
    """A tree the app writes to at runtime must not also be a reload trigger."""

    def test_the_email_outbox_lives_inside_a_reload_dir(self) -> None:
        """The premise of the whole guard — if this ever stops being true the
        exclusions below are dead weight and should be re-argued, not kept."""
        from openstategraph.prebuilt_email import OUTBOX

        assert OUTBOX.is_relative_to(ROOT / "workflows"), (
            "prebuilt_email.OUTBOX moved; re-derive which --reload-dir it now "
            "sits under (or whether it needs excluding at all)"
        )

    @pytest.mark.parametrize(
        "pattern",
        [
            "'*/_outbox/*'",  # the email tool's dry-run drop
            "'*.eml'",
            "'*/__pycache__/*'",  # mounting a workflow package compiles it
            "'*.pyc'",
            "'*.sqlite'",  # the Chinook database and its sidecars
        ],
    )
    def test_runtime_written_paths_are_excluded(
        self, uvicorn_invocation: str, pattern: str
    ) -> None:
        assert f"--reload-exclude {pattern}" in uvicorn_invocation, (
            f"{pattern} is written by the running app inside a --reload-dir; "
            "without the exclusion a normal run reloads the server mid-stream"
        )


class TestGracefulShutdownIsBounded:
    """The second guard: a real source edit must restart, never wedge.

    Without a cap, uvicorn waits for open connections to close, an SSE stream
    never closes, and the reloader parent holds :8000 while answering nothing.
    """

    def test_a_graceful_shutdown_timeout_is_set(self, uvicorn_invocation: str) -> None:
        match = re.search(r"--timeout-graceful-shutdown\s+(\d+)", uvicorn_invocation)
        assert match, (
            "no --timeout-graceful-shutdown: a reload during a live SSE run "
            "hangs in 'Waiting for connections to close' forever"
        )
        assert 0 < int(match.group(1)) <= 30, "the cap must actually bound the wait"

    def test_the_reload_dirs_are_still_scoped(self, uvicorn_invocation: str) -> None:
        assert "--reload-dir backend" in uvicorn_invocation
        assert "--reload-dir workflows" in uvicorn_invocation
