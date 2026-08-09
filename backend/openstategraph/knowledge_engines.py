"""SQL engine adapters — the trainer's per-engine introspection seam.

The build button doesn't know about databases; the SQL builder doesn't know
about *engines*. It knows about **connection refs** — the strings the
workflow's own tool nodes are configured with — and answers two questions
through this module:

- ``recognize(connection_ref)`` — which engine is this, read from the wiring
  (a URL scheme, or a bare path meaning SQLite). Reading, never guessing.
- ``IEngineAdapter`` — one adapter per engine answers *what's inside*:
  ``list_tables``, ``table_schema`` (columns, PKs, and FKs **both
  directions**), and ``sample``. ``table_brief`` composes them into the one
  shape every engine's topics share.

Adding an engine is an adapter registered in ``ENGINE_ADAPTERS`` — never a
new builder, never an edit to the builder or the endpoint.

**Drivers are optional.** SQLite ships with Python; Postgres and MSSQL need
a driver this deployment may not have. The import is lazy, behind
``available()``: a recognized source whose driver is missing is reported as
*recognized but unavailable* with an actionable warning — discovery never
crashes over a missing wheel.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

#: URL scheme → engine name. A ref with no scheme is a filesystem path,
#: which means SQLite — exactly what the sql tool nodes have always meant.
_SCHEME_ENGINES = {
    "sqlite": "sqlite",
    "postgres": "postgres",
    "postgresql": "postgres",
    "mssql": "mssql",
    "sqlserver": "mssql",
}


def recognize(connection_ref: str) -> str | None:
    """The engine a connection ref names, from its wiring alone.

    ``postgres://…``/``postgresql://…`` → postgres; ``mssql://…``/
    ``sqlserver://…`` → mssql; ``sqlite://…`` or a bare path → sqlite.
    An unrecognized scheme is None — a skipped source, never a guess.
    """
    ref = connection_ref.strip()
    if not ref:
        return None
    if "://" not in ref:
        return "sqlite"
    scheme = ref.split("://", 1)[0].lower()
    return _SCHEME_ENGINES.get(scheme)


@runtime_checkable
class IEngineAdapter(Protocol):
    """The contract the SQL builder depends on — a shape, not a class."""

    engine: str

    def available(self) -> tuple[bool, str | None]: ...

    def list_tables(self, connection_ref: str) -> list[str]: ...

    def table_schema(self, connection_ref: str, table: str) -> str: ...

    def sample(self, connection_ref: str, table: str, rows: int = 5) -> str: ...


class BaseEngineAdapter(ABC):
    """Shared composition: ``table_brief`` is the one shape per topic."""

    engine: ClassVar[str]

    def available(self) -> tuple[bool, str | None]:
        """(usable, warning). The default engine machinery is stdlib —
        adapters with an optional driver override this."""
        return True, None

    @abstractmethod
    def list_tables(self, connection_ref: str) -> list[str]: ...

    @abstractmethod
    def table_schema(self, connection_ref: str, table: str) -> str:
        """Columns with types and PKs, plus FKs both directions, Markdown."""

    @abstractmethod
    def sample(self, connection_ref: str, table: str, rows: int = 5) -> str: ...

    def table_brief(self, connection_ref: str, table: str, rows: int = 5) -> str:
        """Everything the drafting model needs about one table."""
        parts = [self.table_schema(connection_ref, table)]
        sample = self.sample(connection_ref, table, rows)
        if sample:
            parts += ["\n## Data sample", sample]
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# SQLite — stdlib, always available. The original builder code, moved here.
# ---------------------------------------------------------------------------


def _sqlite_connect(connection_ref: str) -> sqlite3.Connection:
    path = connection_ref.removeprefix("sqlite://")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


class SqliteEngineAdapter(BaseEngineAdapter):
    engine = "sqlite"

    def list_tables(self, connection_ref: str) -> list[str]:
        with _sqlite_connect(connection_ref) as conn:
            return [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]

    def table_schema(self, connection_ref: str, table: str) -> str:
        with _sqlite_connect(connection_ref) as conn:
            columns = [
                f"- {r[1]} ({r[2] or 'ANY'})" + (" PRIMARY KEY" if r[5] else "")
                for r in conn.execute(f'PRAGMA table_info("{table}")')
            ]
            outbound = [
                f"- JOIN rule: {table}.{r[3]} references {r[2]}.{r[4]}"
                for r in conn.execute(f'PRAGMA foreign_key_list("{table}")')
            ]
            inbound = []
            for other in self.list_tables(connection_ref):
                if other == table:
                    continue
                for r in conn.execute(f'PRAGMA foreign_key_list("{other}")'):
                    if r[2] == table:
                        inbound.append(
                            f"- JOIN rule (referenced by): {other}.{r[3]} references {table}.{r[4]}"
                        )
        parts = ["## Columns", *columns]
        if outbound:
            parts += ["\n## Foreign keys (outbound)", *outbound]
        if inbound:
            parts += ["\n## Foreign keys (inbound)", *inbound]
        return "\n".join(parts)

    def sample(self, connection_ref: str, table: str, rows: int = 5) -> str:
        with _sqlite_connect(connection_ref) as conn:
            cursor = conn.execute(f'SELECT * FROM "{table}" LIMIT {int(rows)}')
            headers = [d[0] for d in cursor.description or []]
            lines = [
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
                *("| " + " | ".join(str(c) for c in row) + " |" for row in cursor.fetchall()),
            ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Driver-backed engines — lazy optional imports, pinned introspection SQL.
# ---------------------------------------------------------------------------


class _DriverBackedAdapter(BaseEngineAdapter):
    """Shared shape for adapters whose driver is an optional dependency.

    Subclasses declare the driver module candidates and the introspection
    SQL as class constants — pinned by tests without a live server — and
    the row-to-Markdown folding lives here once.
    """

    #: Importable driver modules, tried in order.
    DRIVER_MODULES: ClassVar[tuple[str, ...]]
    #: `pip install` hint for the warning when no driver is importable.
    DRIVER_HINT: ClassVar[str]

    LIST_TABLES_SQL: ClassVar[str]
    COLUMNS_SQL: ClassVar[str]
    FOREIGN_KEYS_SQL: ClassVar[str]

    def _driver(self) -> Any | None:
        import importlib

        for name in self.DRIVER_MODULES:
            try:
                return importlib.import_module(name)
            except ImportError:
                continue
        return None

    def available(self) -> tuple[bool, str | None]:
        if self._driver() is not None:
            return True, None
        return False, (
            f"the {self.engine} driver is not installed "
            f"({' or '.join(self.DRIVER_MODULES)}; {self.DRIVER_HINT})"
        )

    @abstractmethod
    def _connect(self, connection_ref: str) -> Any: ...

    def _query(self, connection_ref: str, sql: str, params: tuple[Any, ...] = ()) -> list[tuple]:
        conn = self._connect(connection_ref)
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return list(cursor.fetchall())
        finally:
            conn.close()

    def list_tables(self, connection_ref: str) -> list[str]:
        return [str(r[0]) for r in self._query(connection_ref, self.LIST_TABLES_SQL)]

    def table_schema(self, connection_ref: str, table: str) -> str:
        columns = [
            f"- {r[0]} ({r[1]})" + ("" if str(r[2]).upper() == "YES" else " NOT NULL")
            for r in self._query(connection_ref, self.COLUMNS_SQL, (table,))
        ]
        outbound: list[str] = []
        inbound: list[str] = []
        # FK rows: (from_table, from_column, to_table, to_column), both
        # directions filtered client-side from one query per table.
        for from_table, from_column, to_table, to_column in self._query(
            connection_ref, self.FOREIGN_KEYS_SQL, (table, table)
        ):
            if str(from_table) == table:
                outbound.append(
                    f"- JOIN rule: {from_table}.{from_column} references {to_table}.{to_column}"
                )
            else:
                inbound.append(
                    f"- JOIN rule (referenced by): {from_table}.{from_column} "
                    f"references {to_table}.{to_column}"
                )
        parts = ["## Columns", *columns]
        if outbound:
            parts += ["\n## Foreign keys (outbound)", *outbound]
        if inbound:
            parts += ["\n## Foreign keys (inbound)", *inbound]
        return "\n".join(parts)


class PostgresEngineAdapter(_DriverBackedAdapter):
    engine = "postgres"
    DRIVER_MODULES = ("psycopg", "psycopg2")
    DRIVER_HINT = "pip install 'psycopg[binary]'"

    LIST_TABLES_SQL = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    )
    COLUMNS_SQL = (
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "ORDER BY ordinal_position"
    )
    #: pg_catalog is the authority for FKs — one row per referencing column,
    #: both directions selected by the two placeholders (from-table, to-table).
    FOREIGN_KEYS_SQL = (
        "SELECT src.relname, a.attname, dst.relname, af.attname "
        "FROM pg_constraint c "
        "JOIN pg_class src ON src.oid = c.conrelid "
        "JOIN pg_class dst ON dst.oid = c.confrelid "
        "JOIN unnest(c.conkey) WITH ORDINALITY AS ck(attnum, ord) ON TRUE "
        "JOIN unnest(c.confkey) WITH ORDINALITY AS cfk(attnum, ord) "
        "ON cfk.ord = ck.ord "
        "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ck.attnum "
        "JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = cfk.attnum "
        "WHERE c.contype = 'f' AND (src.relname = %s OR dst.relname = %s) "
        "ORDER BY src.relname, a.attname"
    )

    def _connect(self, connection_ref: str) -> Any:
        driver = self._driver()
        assert driver is not None, "available() gates every call path"
        return driver.connect(connection_ref)

    def sample(self, connection_ref: str, table: str, rows: int = 5) -> str:
        result = self._query(
            connection_ref, f'SELECT * FROM "{table}" LIMIT {int(rows)}'  # noqa: S608
        )
        return "\n".join("| " + " | ".join(str(c) for c in row) + " |" for row in result)


class MssqlEngineAdapter(_DriverBackedAdapter):
    engine = "mssql"
    DRIVER_MODULES = ("pyodbc", "pymssql")
    DRIVER_HINT = "pip install pyodbc"

    LIST_TABLES_SQL = (
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
    )
    COLUMNS_SQL = (
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
        "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? "
        "ORDER BY ORDINAL_POSITION"
    )
    #: sys.foreign_keys is the authority — INFORMATION_SCHEMA's referential
    #: constraint views drop multi-column ordering and cross-schema detail.
    FOREIGN_KEYS_SQL = (
        "SELECT src.name, pc.name, dst.name, rc.name "
        "FROM sys.foreign_key_columns fkc "
        "JOIN sys.tables src ON src.object_id = fkc.parent_object_id "
        "JOIN sys.tables dst ON dst.object_id = fkc.referenced_object_id "
        "JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id "
        "AND pc.column_id = fkc.parent_column_id "
        "JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id "
        "AND rc.column_id = fkc.referenced_column_id "
        "WHERE src.name = ? OR dst.name = ? "
        "ORDER BY src.name, pc.name"
    )

    def _connect(self, connection_ref: str) -> Any:
        driver = self._driver()
        assert driver is not None, "available() gates every call path"
        return driver.connect(connection_ref)

    def sample(self, connection_ref: str, table: str, rows: int = 5) -> str:
        result = self._query(
            connection_ref, f"SELECT TOP {int(rows)} * FROM [{table}]"  # noqa: S608
        )
        return "\n".join("| " + " | ".join(str(c) for c in row) + " |" for row in result)


#: The extension point: register an adapter here, never edit the builder.
ENGINE_ADAPTERS: dict[str, BaseEngineAdapter] = {
    adapter.engine: adapter
    for adapter in (SqliteEngineAdapter(), PostgresEngineAdapter(), MssqlEngineAdapter())
}


__all__ = [
    "ENGINE_ADAPTERS",
    "BaseEngineAdapter",
    "IEngineAdapter",
    "MssqlEngineAdapter",
    "PostgresEngineAdapter",
    "SqliteEngineAdapter",
    "recognize",
]
