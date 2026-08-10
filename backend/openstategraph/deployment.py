"""One process serves one deployment — and this is the module that says no.

**The decision (scale-and-adopt ticket 06): multi-worker is refused, not
supported.** It was a written caveat in five places
(`docs/decisions/memory-architecture.md`, `docs/decisions/mcp-layer.md`,
`README.md`, `docs/adoption.md`, `Dockerfile`) and enforced in none, which
means the first person to type `--workers 4` got a deployment that looked
fine and corrupted a paused approval eventually.

## Why refuse rather than support

Two independent in-process mechanisms make a second worker wrong, and the
project ships only one of the two fixes:

| What breaks | Why | Shipped fix |
| --- | --- | --- |
| Checkpoints and long-term memory | `SqliteSaver`/`SqliteStore` serialise writes with a `threading.Lock` held **per instance**; two OS processes do not share it | **yes** — `openstategraph.postgres`, the `[postgres]` extra |
| Live catalogue events (`GET /api/events`) | `api/catalogue_events.py` is an in-process deque fan-out; a publish in worker A never reaches a subscriber on worker B | **no** — needs Postgres `LISTEN`/`NOTIFY` or Redis behind the same `publish`/`subscribe` pair |

Shipping only the first half is the failure the gap register already warns
about: it *looks* like the ceiling lifted, and the symptom is a customer's
`/chat` picker silently missing a workflow half the time. So the refusal is
**unconditional** — configuring Postgres does not lift it — and the message
says so, because a deployer who fixes the named half and is refused again for
an unnamed one has been sent on an errand.

## Two mechanisms, because one of them is blind

- **Reading the configuration** catches `openstategraph serve --workers N`,
  `WEB_CONCURRENCY` and `UVICORN_WORKERS`, and refuses *before a socket is
  bound* — the cheapest, clearest place to fail.
- **An OS-level exclusive lock** catches everything else. `uvicorn --workers 4`
  and `gunicorn -w 4 -k uvicorn.workers.UvicornWorker` leave no trace in the
  environment of the child that serves, so configuration-reading alone would
  have left the biggest hole open. `SingleServerLock` takes an exclusive
  advisory lock on a file in the **state directory** — the same directory that
  holds the sqlite files being contended for, so the lock is scoped to exactly
  the resource at risk. It needs no cooperation from whoever launched the
  process, and the OS releases it on death, so a crash never wedges it.

The lock is deliberately **not** taken by `openstategraph run` or the stdio MCP
server. Those are short-lived single writers with no SSE subscribers, and
locking them would break a workflow people use today (a CLI run in one terminal
while `serve` holds the port in another) in the name of a hazard an order of
magnitude smaller. That narrower caveat is stated in `docs/deploying.md` rather
than enforced, and it is the one caveat this ticket leaves as words.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)

#: Every environment variable a deployment might use to ask for more than one
#: worker. `WEB_CONCURRENCY` is uvicorn's and gunicorn's shared convention;
#: `UVICORN_WORKERS` and `GUNICORN_WORKERS` are the spellings deployment
#: templates use. Read all three: a variable we do not read is a refusal that
#: does not happen.
WORKER_ENV_VARS: tuple[str, ...] = ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS")

#: The lock file, inside `state_dir()`. Named for what it means rather than for
#: what it is, so an operator who finds it can guess right.
SERVE_LOCK_NAME = "serve.lock"


class AnotherServerIsRunning(RuntimeError):
    """A second process tried to serve state a first process already holds.

    Raised rather than logged: this is the case where continuing produces
    interleaved sqlite writes with no error anywhere, which is the outcome the
    whole module exists to prevent.
    """


def configured_worker_count() -> tuple[int, str] | None:
    """The worker count the environment asks for, and which variable said it.

    `None` when nothing readable asked. A value we cannot parse (`auto`, an
    empty string, a shell expression that did not expand) is *unknown*, not
    zero and not a refusal — refusing a deployment over a value we could not
    read would be worse than the hazard, and `SingleServerLock` catches the
    case anyway without needing to understand it.
    """
    for name in WORKER_ENV_VARS:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            return int(raw), name
        except ValueError:
            logger.debug("%s=%r is not a number; ignoring it", name, raw)
    return None


def refusal(count: int, source: str) -> str:
    """The whole explanation, in the one place that owns it.

    Four things, in the order a reader needs them: what was asked, why it is
    refused, what *not* to try, and the exact line to type instead.
    """
    return (
        f"{source} asks for {count} workers, and OpenStateGraph supports exactly one.\n"
        "\n"
        "Two things in this process are per-process, and a second worker breaks both:\n"
        "  * the checkpointer and the long-term memory store — SqliteSaver and\n"
        "    SqliteStore serialise writes with a threading.Lock held per instance,\n"
        "    which two OS processes do not share, so two workers interleave writes\n"
        "    to a paused approval with no error anywhere;\n"
        "  * the catalogue event fan-out behind GET /api/events — an in-process\n"
        "    queue, so a workflow published on one worker never reaches a browser\n"
        "    subscribed to another.\n"
        "\n"
        "Configuring Postgres (`pip install 'openstategraph[postgres]'`,\n"
        "OPENSTATEGRAPH_POSTGRES_URL) fixes the first and is worth doing for\n"
        "durability — but it is NOT enough to lift this limit, because the event\n"
        "fan-out has no cross-process transport yet. Both halves or neither.\n"
        "\n"
        "Run one worker (`--workers 1`) and scale by giving it more concurrency,\n"
        "or run several one-worker instances with separate state directories\n"
        "behind a session-affinity proxy. See docs/deploying.md."
    )


def check_worker_count(explicit: int | None = None) -> str | None:
    """The refusal text if this deployment asked for more than one worker.

    `explicit` is a command-line argument and therefore outranks the
    environment, per the project-wide precedence rule (convention < config file
    < environment < explicit argument).
    """
    if explicit is not None:
        return None if explicit <= 1 else refusal(explicit, f"--workers {explicit}")
    configured = configured_worker_count()
    if configured is None:
        return None
    count, source = configured
    return None if count <= 1 else refusal(count, f"{source}={count}")


#: Locks already held by *this* process, keyed by the resolved lock path.
#:
#: `fcntl.flock` is held per open file description, so a second `flock` in the
#: same process on a second file descriptor conflicts with the first — which
#: would mean two `create_app()` calls in one interpreter refusing each other.
#: Two apps in one process are two *threads* sharing one saver, which is the
#: supported case; only another *process* is the hazard. So the lock is opened
#: once per path and refcounted here.
_HELD: dict[Path, list[object]] = {}


class SingleServerLock:
    """An exclusive advisory lock on one deployment's state directory.

    Three public members — `path`, `acquire`, `release` — and one reason to
    change. `acquire` raises `AnotherServerIsRunning`; `release` is idempotent,
    because the caller is a `finally` block and a lifespan shutdown that may
    both run.
    """

    def __init__(self, state_directory: Path | str) -> None:
        self.path = Path(state_directory) / SERVE_LOCK_NAME

    def acquire(self) -> None:
        """Take the lock, or raise `AnotherServerIsRunning` explaining why not.

        Never blocks. A deployer waiting silently on a lock is a hang, and a
        hang is the one failure shape worse than the refusal.
        """
        held = _HELD.get(self.path)
        if held is not None:
            held.append(self)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        try:
            _lock_exclusive(handle)
        except OSError as exc:
            handle.close()
            raise AnotherServerIsRunning(
                f"another OpenStateGraph server already holds {self.path}.\n"
                "\n"
                "Only one process may serve one state directory: the checkpointer,\n"
                "the memory store and the /api/events fan-out are all per-process\n"
                "(see docs/deploying.md). This is what `uvicorn --workers N` and\n"
                "`gunicorn -w N` look like from inside a worker.\n"
                "\n"
                "Run one worker, or give this instance its own state directory with\n"
                "OPENSTATEGRAPH_STATE_DIR."
            ) from exc
        _HELD[self.path] = [self]
        self._handle: IO[str] | None = handle

    def release(self) -> None:
        """Give it up. Safe to call twice, and safe if `acquire` never ran."""
        held = _HELD.get(self.path)
        if held is None or self not in held:
            return
        held.remove(self)
        if held:
            return
        _HELD.pop(self.path, None)
        handle = getattr(self, "_handle", None)
        if handle is not None:
            self._handle = None
            try:
                handle.close()  # releases the flock with the file description
            except OSError:  # pragma: no cover - already closed
                logger.debug("could not close %s", self.path, exc_info=True)


def _lock_exclusive(handle: IO[str]) -> None:
    """Non-blocking exclusive lock, on whichever API this OS has.

    Both are stdlib, so there is no dependency and no platform where this
    silently does nothing — which matters, because a guard that no-ops on
    someone's OS is the caveat this module was written to delete.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        # Reached through `getattr` because typeshed gates `msvcrt.locking` and
        # `LK_NBLCK` behind `sys.platform == "win32"`, so a POSIX mypy run
        # cannot see them and a direct call fails the gate on the platform that
        # never executes this branch. The behaviour is identical to `flock`
        # here: a non-blocking exclusive lock that raises OSError when someone
        # else holds it.
        import msvcrt

        handle.seek(0)
        getattr(msvcrt, "locking")(handle.fileno(), getattr(msvcrt, "LK_NBLCK"), 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


__all__ = [
    "WORKER_ENV_VARS",
    "AnotherServerIsRunning",
    "SingleServerLock",
    "check_worker_count",
    "configured_worker_count",
    "refusal",
]
