"""One read-only SQLite connection, and the sentence `mode=ro` does not say.

Six modules opened a read-only database by writing the same URI by hand, and
each of them was proud of the same property in its own docstring: *safety is
the driver's, not string matching* — a write is refused by SQLite however the
statement is spelled, so nothing here parses SQL. That design is right and is
kept exactly as it is.

What the six did not say is that `mode=ro` describes **one file**. The URI
form is used because it is the only way to spell `mode=ro` at all — there is
no non-URI read-only open in the stdlib, and `PRAGMA query_only=ON` is not a
substitute, being a per-connection flag a statement can turn back off. But
`uri=True` also makes SQLite honour URI parameters in `ATTACH`, and an
attached database carries **its own** mode. Probed against a real `mode=ro`
connection on 2026-08-29 (`the-boundary-nobody-checked/06`):

    ATTACH DATABASE 'file:/tmp/…?mode=rwc' AS x   ->  ok, file created
    VACUUM INTO '/tmp/…'                          ->  ok, 825 KB written

`VACUUM INTO` is the one that sets the size of it. `ATTACH` alone is bounded
the way the ticket recorded — sqlite3 refuses two statements per `execute()`
and every caller here opens a fresh connection, so a model gets an attach it
can neither write through nor read back, i.e. an empty file at a path of its
choosing. `VACUUM INTO` needs neither a second statement nor an attachment:
**one model-authored statement copies the whole database to any absolute path
the process can write.**

## The mechanism, and why it is not a parser

`sqlite3.Connection.set_authorizer` is the driver's own callback, consulted
while a statement is *prepared*. SQLite reports `ATTACH`, `DETACH`, `VACUUM`
and `VACUUM INTO` to it as `SQLITE_ATTACH` / `SQLITE_DETACH` with the target
path as `arg1`, so denying that pair closes the whole family — including
spellings nobody has thought of — without this module ever looking at the
text of a statement. That is the same guarantee `mode=ro` gives about writes,
extended to the file the connection is allowed to be about.

**Denied by action, not by path**, although the path is available. A path
allow-list would be a second jail to keep in step with `_resolve_database`'s,
and there is no caller that wants a second file: the answer to "which paths
may I attach?" is none.

## What is deliberately still allowed

`PRAGMA` executes. `prebuilt_sql` and `knowledge_engines` *depend* on
`table_info` and `foreign_key_list`, and a blanket `SQLITE_PRAGMA` denial
breaks the schema tool. The pragmas that write were probed on this
connection and are already refused by `mode=ro` itself — `PRAGMA
journal_mode=WAL` answers *attempt to write a readonly database* — and
`temp_store_directory` sets a directory rather than creating one. Extension
loading is refused by the driver before any authorizer runs: `sqlite3` ships
with `enable_load_extension` off, so `SELECT load_extension('x')` answers
*not authorized* on a bare connection. Enumerated rather than guessed, which
is what the ticket asked for.

One thing this connection still discloses and did before: `PRAGMA
database_list` returns the absolute host path of the file it is about. That
is the path the node was configured with, so it tells a model where the
server keeps its workflows and nothing else. Recorded here rather than
closed, because closing it means a pragma deny-list and this module's whole
argument is against carrying one.
"""

from __future__ import annotations

import sqlite3
import weakref
from contextlib import closing
from pathlib import Path

#: The action codes that mean *a second file*. `VACUUM INTO` reports as
#: `SQLITE_ATTACH`; `SQLITE_DETACH` is here so the pair cannot be half-denied.
_SECOND_FILE = (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH)


class ReadOnlyConnection(sqlite3.Connection):
    """A `mode=ro` connection that is also about exactly one file.

    The refusal is recorded rather than only raised, because the driver's own
    word for it is `not authorized` — a sentence that tells a model nothing it
    can do differently. `sql_error_text` turns the record into our words.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        #: The path most recently refused, or `""`. Never a list: one statement
        #: per `execute` means there is only ever one.
        self.refused_second_file = ""
        here = weakref.ref(self)

        def authorize(
            action: int,
            arg1: str | None,
            arg2: str | None,
            database: str | None,
            trigger: str | None,
        ) -> int:
            if action not in _SECOND_FILE:
                return sqlite3.SQLITE_OK
            live = here()
            if live is not None:
                live.refused_second_file = arg1 or "(unnamed)"
            return sqlite3.SQLITE_DENY

        self.set_authorizer(authorize)


def readonly_connection(path: Path | str) -> ReadOnlyConnection:
    """Open `path` read-only, and about `path` alone."""
    connection = sqlite3.connect(
        f"file:{path}?mode=ro", uri=True, factory=ReadOnlyConnection
    )
    assert isinstance(connection, ReadOnlyConnection)
    return connection


def readonly_closing(path: Path | str) -> "closing[ReadOnlyConnection]":
    """The same connection, in a `with` block that actually CLOSES it.

    `contextlib.closing`, not the bare connection: sqlite3's own context
    manager is a *transaction* manager — it commits or rolls back and leaves
    the descriptor open.
    """
    return closing(readonly_connection(path))


def sql_error_text(
    connection: ReadOnlyConnection,
    exc: BaseException,
    *,
    instead: str = "",
) -> str:
    """What a model should read when a statement failed.

    `docs/declaring-a-next-step.md`, applied to our own tool: a refusal with no
    destination in it leaves the model the same wrong moves, so it makes them
    again. The `instead` clause is the caller's, because only the caller knows
    which of its tools the model should reach for.
    """
    refused = connection.refused_second_file
    if not refused:
        return f"SQL error: {exc}"
    said = (
        f"This connection reads one database file and cannot open a second one, "
        f"so '{refused}' was refused. ATTACH, DETACH and VACUUM INTO are refused "
        f"here whatever the path or the mode."
    )
    return f"{said} Next step: {instead}" if instead else said
