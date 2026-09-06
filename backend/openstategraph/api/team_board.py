"""The app's one door to the card store, and the sentence for why it is not
the shared one.

`team-board-and-gap-reports/18`. `OPENSTATEGRAPH_KANBAN_URL` is read by
`open_kanban_store`, which opens the shared board or refuses **by raising** —
correct for a CLI, where the person who typed the command is standing there to
read it. A server is the other case: the same refusal reached the owner as a
two-hundred-line traceback per SSE reconnect, a 500 for the tab, and nothing
at all on `/api/health`, which had just said a team board was configured.

So a server asks **once, at startup**, and keeps the answer:

- **the shared board opens** — nothing is recorded, and every door opens it,
  exactly as before this module existed;
- **it does not** — the sentence is recorded rather than raised, one line is
  logged, `/api/health` publishes it, the tab prints it, and the process goes
  on serving the **local** board.

That last clause is the one that needs defending, because
`kanban_store.open_kanban_store` refuses a fallback on purpose: a board that
quietly became a local file is two people disagreeing about what the board
says. The difference here is *quietly*. This fallback is published on the
health endpoint and rendered in the tab as the reason that tab has no cards,
so nobody reads local rows believing they are the team's. What it buys is that
a missing driver costs the shared board and nothing else — not the editor's
own Workflows board, not the live stream every tab holds open.

**Recorded once, not re-tried.** A board that was unreachable at startup stays
unreachable to this process until it is restarted, which is what the recorded
sentence tells the reader to do. Re-probing per request would put a socket
timeout on the health endpoint, and re-probing per poll would put one on a
one-second loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - types only
    from openstategraph.abc.kanban_store import IKanbanStore

logger = logging.getLogger(__name__)


class TeamBoard:
    """Three public members: `probe`, `error`, `open`.

    A collaborator on `WorkflowServices` rather than two methods on it, for the
    reason that class's own exception in `test_public_surface_ceiling.py`
    gives: its width is one collaborator per kind of shared state. "Which card
    store this process actually has, and why it is not the one that was asked
    for" is one such kind, and it is read by three unrelated doors — the health
    endpoint, the card routes and the live stream's watcher.

    Every collaborator is injected, so a test drives all three outcomes without
    a database, a driver or an environment variable.
    """

    def __init__(
        self,
        open_configured: Callable[[], "IKanbanStore"],
        open_local: Callable[[], "IKanbanStore"],
        *,
        is_configured: Callable[[], bool],
    ) -> None:
        self._open_configured = open_configured
        self._open_local = open_local
        self._is_configured = is_configured
        self._error: str | None = None
        self._probed = False

    @property
    def error(self) -> str | None:
        """Why this process is not on the shared board, or `None`.

        Read by `GET /api/health`, which must never probe: a health endpoint
        that opened a database connection would answer at the speed of the
        slowest thing it asks about.
        """
        return self._error

    def probe(self) -> str | None:
        """Open the configured board once and remember what happened.

        Called at startup by `create_app`, beside `services.checkpointer`,
        which resolves at startup for the same reason: the one line it logs
        has to reach the operator before anybody can be surprised by it.

        Never raises. Every exception is a sentence — `ImportError` for a
        missing driver, `PostgresUnavailable` for a database nobody can reach,
        `ValueError` for a scheme nothing is registered for — and each of them
        already names the variable and what to do, because the doors that
        raise them were written to be read by a person.
        """
        if self._probed:
            return self._error
        self._probed = True
        if not self._is_configured():
            return None
        try:
            store = self._open_configured()
        except Exception as exc:
            self._error = str(exc)
            # One line, at startup, never per request. `warning` rather than
            # `exception`: the sentence is the whole of what a reader can act
            # on, and a stack trace here is what the ticket was filed about.
            logger.warning("team board unavailable, keeping the local board: %s", self._error)
            return self._error
        close = getattr(store, "close", None)
        if callable(close):
            # The probe owns what it opened. A Postgres store holds a pool
            # with worker threads, and leaking one per process start is how
            # `team-board-and-gap-reports/13` found a five-second shutdown.
            close()
        logger.info("team board: the shared board opened; cards are read from it")
        return None

    def open(self) -> "IKanbanStore":
        """The board this process actually has.

        The shared one when it opened, the local one when it did not. Probes
        first if nothing has — the safety net under "asked once at startup":
        a transport that never calls `probe()` must still not hand an
        `ImportError` to a stream that is already answering `200`.
        """
        if not self._probed:
            self.probe()
        return self._open_local() if self._error is not None else self._open_configured()


# No `__all__` — Tier 3, like every other module under `api/`.
