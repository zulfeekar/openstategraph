"""What a workflow's SQL tools can actually reach — read from the database.

**Why this module exists.** `tool.chinook-get-schema` used to carry a `Table`
listbox with eleven table names typed into a TypeScript file and a default of
`Artist`. The backend tool takes `table` as a *model* argument and declares no
`configure()`, so the listbox changed nothing about what ran — it only told a
reader "this node fetches Artist's schema", which was false twice over: the
agent picks the table, and the names in the box were a copy of a `.sqlite`
file that nothing kept in sync.

Removing the control alone would have left the reader with less than before.
The honest replacement is this: one read that answers, **from the file the
tool actually opens**, which tables the wired tools can reach and what is in
each one — so the card shows the agent's whole field of view rather than a
fiction about one table.

It composes what already exists and adds no new knowledge of its own:
`sql_sources_in_document` reads the wiring (which database each SQL tool node
names; the chinook family implies the bundled one), and the `IEngineAdapter`
seam answers what is inside. A new engine is an adapter, exactly as before —
never an edit here.

**Every failure is data.** A missing file is already invisible to
`sql_sources_in_document` (it only reports sources that resolve to a real
file inside `workflows/`); a file that is not a database, a driver that is not
installed, or a table that will not introspect become a `warning` on the
source. This is a read for a card — it never raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openstategraph.knowledge_builders import sql_sources_in_document
from openstategraph.knowledge_engines import ENGINE_ADAPTERS

#: A card is a card. Past this many tables the answer stops being readable and
#: starts being a download, so it is truncated *and says so* — a silently
#: shortened list would be the same kind of lie this module exists to remove.
TABLE_CAP = 60


@dataclass(frozen=True)
class ReachableTable:
    """One table, and the Markdown the agent would get for it."""

    name: str
    #: Columns, types, primary key and foreign keys **both directions** — the
    #: adapter's own `table_schema`, i.e. the same text the knowledge builder
    #: drafts from and near enough what the tool returns at run time.
    detail: str


@dataclass(frozen=True)
class ReachableSource:
    """One database the document's SQL tools are wired to."""

    database: str
    engine: str
    tables: list[ReachableTable] = field(default_factory=list)
    #: Recognized but not fully readable — reported, never a crash, never a
    #: silent empty list that reads as "this database has no tables".
    warning: str = ""


def reachable_schema(
    document: dict[str, Any], workflows_root: Path, table_cap: int = TABLE_CAP
) -> list[ReachableSource]:
    """Every SQL source this document wires, with the tables it can reach."""
    root = workflows_root.resolve()
    found: list[ReachableSource] = []

    for ref, engine in sql_sources_in_document(document, workflows_root):
        adapter = ENGINE_ADAPTERS[engine]
        usable, unavailable = adapter.available()
        if not usable:
            found.append(
                ReachableSource(
                    database=ref,
                    engine=engine,
                    warning=f"Recognized as {engine}, but unavailable — {unavailable}",
                )
            )
            continue

        connection_ref = str(root / ref) if engine == "sqlite" else ref
        try:
            names = list(adapter.list_tables(connection_ref))
        except Exception as exc:  # a broken file is a warning, not a 500
            found.append(
                ReachableSource(
                    database=ref,
                    engine=engine,
                    warning=f"Could not be read: {type(exc).__name__}: {exc}",
                )
            )
            continue

        tables: list[ReachableTable] = []
        for name in names[:table_cap]:
            try:
                detail = adapter.table_schema(connection_ref, name)
            except Exception as exc:
                detail = f"_Schema unavailable: {type(exc).__name__}: {exc}_"
            tables.append(ReachableTable(name=name, detail=detail))

        warning = (
            "" if len(names) <= table_cap else f"Showing {table_cap} of {len(names)} tables."
        )
        found.append(
            ReachableSource(database=ref, engine=engine, tables=tables, warning=warning)
        )

    return found


__all__ = ["TABLE_CAP", "ReachableSource", "ReachableTable", "reachable_schema"]
