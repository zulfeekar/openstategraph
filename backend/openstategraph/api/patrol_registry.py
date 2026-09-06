"""The patrol job registry — `kanban-patrol/07`'s other missing half.

**The defect this closes, in the ticket's own words.** *"There is no general
job registry. A patrol outliving the request that started it needs one, and
it needs to answer: what is running, for which project, how far along, and
what happened if it failed. A task nobody can query is a task that fails
silently."*

**Why "for which project" has a one-word answer.** `openstategraph.deployment
.check_worker_count` refuses a second `--workers`, and an exclusive `flock` on
the state directory enforces one process per project state directory — the
same fact `catalogue_events.py` cites for its own in-process fan-out. So this
registry tracks exactly one patrol, for the one project this process serves,
because there is exactly one project this process ever serves. A registry
keyed by `project_id` would be answering a question this deployment shape
cannot ask.

**Why this is not `openstategraph.async_tasks.InProcessTaskDesk`.** That desk
already exists and already tracks status/result/error for a task — but for a
different, narrower thing: one `start_async_task` tool call, made by a model
mid-run, cancellable, followed-up, keyed by a task id a conversation continues
to name. A patrol is none of those — it is not started by a model, is not
cancellable mid-run, and there is only ever one, never a set keyed by id. A
registry built to answer "which of these many tasks" for one task that is
never plural would be the wrong shape wearing the right name.

**Single-worker, stated where a reader will meet it** (`07`'s own last "done
when"): this registry's state lives in one Python object in one process's
memory. Lifting the worker ceiling without also replacing this registry (the
same two-halves argument `catalogue_events.py` makes about its own fan-out —
Redis or Postgres behind the same three methods) would let two workers each
believe no patrol is running and start one apiece.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PatrolJobState:
    """What a caller can learn about the one patrol this process runs.

    `status` is one of `idle` (never run since this process started),
    `running`, `finished` (its last run filed/skipped whatever it found) or
    `failed` (its last run raised). `idle` and a fresh restart look the same
    on purpose — there is no durable record across a restart, the same
    honesty `async_tasks.TaskRecord` already carries about its own rows: this
    is what the running process knows, not a history.
    """

    status: str = "idle"
    started_at: str = ""
    finished_at: str = ""
    #: The plain reason, when `status == "failed"` — `07`'s own words: *"a
    #: patrol that dies silently is worse than one that never started"*.
    error: str = ""
    filed: int = 0
    skipped: int = 0
    total_findings: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "filed": self.filed,
            "skipped": self.skipped,
            "total_findings": self.total_findings,
        }


class PatrolJobRegistry:
    """One patrol's whole life, queryable from any request.

    `try_start` is the one method a caller must get right, and it is made
    hard to get wrong: it is the single place that reads *and* writes
    `_state` under the lock, so "is one running" and "mark one running" are
    one atomic step. Two requests racing `POST /api/kanban/patrol/run` cannot
    both see `idle` and both proceed — exactly the race the 409 refusal
    exists to make impossible rather than merely unlikely.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = PatrolJobState()

    def snapshot(self) -> PatrolJobState:
        """The current state, safe to read from any thread at any time."""
        with self._lock:
            return self._state

    def try_start(self) -> bool:
        """Claim the one slot. `False` means a patrol is already running —
        the caller's cue to answer `409`, not to queue anything: `07`
        refuses cleanly rather than building a queue nobody asked for."""
        with self._lock:
            if self._state.status == "running":
                return False
            self._state = PatrolJobState(status="running", started_at=_now())
            return True

    def finished(self, *, filed: int, skipped: int, total_findings: int) -> None:
        """The run completed without raising."""
        with self._lock:
            self._state = replace(
                self._state,
                status="finished",
                finished_at=_now(),
                filed=filed,
                skipped=skipped,
                total_findings=total_findings,
                error="",
            )

    def failed(self, reason: str) -> None:
        """The run raised. `reason` is the plain exception text — this
        registry does not classify or soften it, it reports it."""
        with self._lock:
            self._state = replace(
                self._state,
                status="failed",
                finished_at=_now(),
                error=reason,
            )


# No `__all__` here on purpose — Tier 3, same as `catalogue_events.py`; see
# `openstategraph/api/__init__.py`.
