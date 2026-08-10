"""Postgres-backed checkpoints and long-term memory — the `[postgres]` extra.

**What this buys, stated precisely, because the obvious reading is wrong.** It
does *not* raise the worker ceiling. `openstategraph.deployment` still refuses
more than one worker with this configured, because the catalogue-events fan-out
behind `GET /api/events` is an in-process queue and has no cross-process
transport yet. Shipping half a scale-out story and letting people discover the
other half in production is the failure the gap register (RC-03) warned about;
the refusal is what makes shipping this half safe.

What it buys is **operational**: a paused `human.approval` and an agent's saved
memories live in a database an operations team already backs up, replicates and
restores, instead of a sqlite file whose durability story is "do not lose the
container". That is worth having on one worker, and it is the harder half of
the eventual multi-worker work, done.

## Three decisions worth stating

**Environment only.** `OPENSTATEGRAPH_POSTGRES_URL`, never `openstategraph.yaml`.
A DSN carries a password and that file is committed — `config_file._reject_secrets`
already refuses to let a credential into it, and that refusal is the reason the
file is safe to check in. So the URL lives where the provider keys live.

**A misconfiguration raises; it does not degrade.** Everywhere else in this
codebase an unavailable backend degrades loudly to a working default, because
the default is durable and an adopter must not be blocked. Postgres is
different in kind: it is never a default, so somebody typed it, in a deployment
where somebody else will later ask where the data is. Quietly writing their
approvals to a local sqlite file instead is a surprise discovered at restore
time. Startup fails instead, with the reason.

**A pool, not a connection.** `PostgresSaver.from_conn_string` opens a single
`psycopg.Connection`, which serialises every request thread behind one lock —
precisely the property that makes sqlite single-worker. Trading one lock for
another buys nothing, so this module builds a `ConnectionPool` with the
connection settings langgraph's own pooled path uses (`autocommit`,
`prepare_threshold=0`, `dict_row`) and hands it to the constructor, which takes
either.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

#: The one place a Postgres deployment is configured. A name in the
#: environment, like every other credential this project touches.
POSTGRES_URL_ENV = "OPENSTATEGRAPH_POSTGRES_URL"

#: Pool bounds. Small on purpose: one worker, and every checkpoint write is
#: short. `max_size` above the database's own `max_connections` is how a
#: deployment turns a busy minute into a refused connection.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 10


class PostgresUnavailable(RuntimeError):
    """The configured database could not be reached or set up.

    A `RuntimeError` so an existing `except Exception` still catches it, and a
    named type so a deployment's own startup checks can tell "your database is
    down" from "your document is invalid".
    """


def postgres_url() -> str | None:
    """The configured DSN, or None when this deployment is not using Postgres."""
    return os.environ.get(POSTGRES_URL_ENV, "").strip() or None


def configured() -> bool:
    """Whether Postgres is this deployment's answer for durable state."""
    return postgres_url() is not None


#: A URI DSN's password: everything between `:` and the `@` that ends the
#: userinfo. Anchored on `//` so a path containing `@` cannot be mistaken for
#: credentials.
_URI_PASSWORD = re.compile(r"(?<=//)([^/@:\s]+):([^/@\s]*)@")
#: A keyword/value DSN's password (`host=db password=hunter2`).
_KEYWORD_PASSWORD = re.compile(r"(password\s*=\s*)(\S+)", re.IGNORECASE)


def redacted(url: str) -> str:
    """The DSN with its password removed, for logs and error messages.

    Every message in this module goes through it. A connection string is the
    single most useful thing to put in a "cannot connect" error and the single
    worst thing to leak, and the only way to have both is for there to be no
    path that formats one raw.
    """
    text = _URI_PASSWORD.sub(r"\1:***@", url)
    return _KEYWORD_PASSWORD.sub(r"\1***", text)


def _pool(url: str) -> Any:
    """An open `ConnectionPool` configured the way langgraph expects.

    The three connection settings are not ours to choose: langgraph's own
    pooled path sets them, its SQL is written against `dict_row`, and
    `prepare_threshold=0` is what keeps a pooled connection from accumulating
    server-side prepared statements it will never reuse.
    """
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise ImportError(
            f"{POSTGRES_URL_ENV} is set, but psycopg is not installed — "
            "pip install 'openstategraph[postgres]'"
        ) from exc

    pool = ConnectionPool(
        url,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        # Not opened by the constructor: psycopg deprecates that, and opening
        # explicitly is what lets an unreachable database fail *here*, with our
        # message, instead of on the first approval somebody tries to resume.
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    try:
        pool.open(wait=True, timeout=10.0)
    except Exception as exc:
        raise PostgresUnavailable(
            f"could not connect to {redacted(url)} ({exc}). "
            f"{POSTGRES_URL_ENV} is set, so this deployment asked for Postgres and "
            "will not silently fall back to a local sqlite file. Fix the database, "
            f"or unset {POSTGRES_URL_ENV} to use the state directory."
        ) from exc
    return pool


def checkpointer(url: str) -> Any:
    """A `PostgresSaver` on an open pool, tables migrated.

    `setup()` eagerly, exactly as the sqlite path does: it is what makes the
    tables exist *now*, so the startup line reports a database that is actually
    usable rather than one that will be on first write.
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:
        raise ImportError(
            f"{POSTGRES_URL_ENV} is set, but langgraph-checkpoint-postgres is not "
            "installed — pip install 'openstategraph[postgres]'"
        ) from exc

    pool = _pool(url)
    saver = PostgresSaver(pool)
    _migrate(saver, pool, url, "checkpointer")
    logger.info("approvals persist in Postgres at %s", redacted(url))
    return saver


def store(url: str) -> Any:
    """A `PostgresStore` on an open pool, tables migrated."""
    try:
        from langgraph.store.postgres import PostgresStore
    except ImportError as exc:
        raise ImportError(
            f"{POSTGRES_URL_ENV} is set, but langgraph-checkpoint-postgres is not "
            "installed — pip install 'openstategraph[postgres]'"
        ) from exc

    pool = _pool(url)
    memory_store = PostgresStore(conn=pool)
    _migrate(memory_store, pool, url, "memory store")
    logger.info("long-term memory persists in Postgres at %s", redacted(url))
    return memory_store


def _migrate(resource: Any, pool: Any, url: str, what: str) -> None:
    """Run `setup()`, closing the pool if it fails.

    The close matters: without it a deployment that raises on startup leaves a
    live pool holding connections against a database it is about to abandon,
    and a supervisor restarting the process exhausts `max_connections`.
    """
    try:
        resource.setup()
    except Exception as exc:
        pool.close()
        raise PostgresUnavailable(
            f"connected to {redacted(url)} but could not create the {what} tables "
            f"({exc}). The database user needs CREATE on its schema."
        ) from exc
