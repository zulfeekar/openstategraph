"""`tool.mssql-query` — one read-only T-SQL statement against a warehouse.

The sibling of `prebuilt_sql`'s SQLite family, on the same family base, and the
two places it differs are the two places it must: **the dialect and the
connection**. What the base owns — `side_effecting = False`, the `maxRows`
parse, the truncation-aware markdown table — is inherited rather than repeated
(`osg-agent-experience/34`).

It sits *beside* `_SqliteExplorerBase` rather than under it
(`osg-agent-experience/39`). That rung holds `database`, `_db()` and
`_refusal()`, and a warehouse read over ODBC has no file for any of them to
name; while this class inherited them, a refusal reachable from an MSSQL node
could have told its reader to set a `.sqlite` path. The refusals here are
`_dsn()` and `_pins()`, and they are the only ones.

**Read-only here is not what read-only is over there, and saying so is the
point.** `prebuilt_sql`'s docstring is proud that safety is the driver's,
not string matching: `mode=ro` is a property of the *file* SQLite opens, so
however a write is spelled the engine refuses it. No MSSQL driver offers an
equivalent. `ApplicationIntent=ReadOnly` — the string an experienced reader
will expect to see here — is an availability-group **routing** hint: it picks
a replica to talk to, and against a standalone server it refuses nothing. So
the guard is two mechanisms, both named:

1. **A statement gate.** Exactly one statement, and it must be a `SELECT` or a
   `WITH … SELECT`. This is the string matching the SQLite module was right to
   avoid and this module cannot, which is why it is written down here instead
   of being discovered later by somebody comparing the two.
2. **A transaction that is never committed.** The connection is opened with
   `autocommit=False` and rolled back and closed in a `finally`, so anything
   that reached the server despite the gate does not survive the call.

And a third thing, which is not a read-only guard but is the reason this atom
exists at all: **the allowlist**. The `allowlist` field names a YAML inside the
workflows root whose `resolvers.*.pin` **values** are the only tables a query
may name. A pin is a human's choice of which version of a logical table may be
read; naming the unversioned logical name is exactly the mistake a pin exists
to catch, so it is refused too, with the pin list printed.

**No credential is ever held.** The `connection` field holds the *name* of an
environment variable, never a connection string — a document is committed. A
value pasted where a name goes is refused as a value, and the refusal does not
echo it back.

`pyodbc` is an optional extra (`openstategraph[mssql]`), imported lazily at the
one seam below, so the base wheel gains nothing and the unconfigured path — the
only path this pass can prove, by the owner's decision of 2026-09-04 — needs no
driver at all.

`yaml` is not a new dependency: `langchain-core`, one of the four core
requirements, requires `pyyaml>=5.3`, so it is present in every install of the
base wheel.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
from typing import Any, Iterator

from pydantic import BaseModel, Field

from openstategraph.abc.tool import ToolResult
from openstategraph.prebuilt_sql import DEFAULT_MAX_ROWS, _SqlExplorerBase
from openstategraph.workflows_root import workflows_root

#: The variable a document names when its author names nothing else. A default
#: *name* is safe in a way a default value never is — it is a pointer, and the
#: thing it points at is refused when unset.
DEFAULT_CONNECTION_ENV = "OPENSTATEGRAPH_MSSQL_URL"

#: The extra that carries the driver. Named in the refusal rather than in a
#: doc page, because the refusal is where somebody is standing when they need it.
DRIVER_EXTRA = "openstategraph[mssql]"

#: A POSIX environment-variable name. Anything else in `connection` is a value
#: somebody pasted, and is refused without being echoed.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The keywords after which T-SQL names a table. Deliberately small: this is a
#: gate on what a query may *read*, run after the statement gate has already
#: established that the statement is a single `SELECT`.
_TABLE_KEYWORDS = ("from", "join", "into", "update", "apply")

#: A schema-qualified or bare identifier, brackets and quotes tolerated the way
#: T-SQL writes them.
_IDENTIFIER = re.compile(r'[\[\]"`]?([A-Za-z_][\w$#]*)[\[\]"`]?(?:\.[\[\]"`]?([A-Za-z_][\w$#]*)[\[\]"`]?)?')


def _without_comments(sql: str) -> str:
    """`/* … */` and `-- …` removed, so a comment cannot hide a keyword.

    `/**/dRoP TABLE` is the recorded input this exists for: it is a write whose
    first token, read naively, is a comment.
    """
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def statement_refusal(sql: str) -> str | None:
    """`None` when `sql` is a single read; otherwise the sentence to return.

    Public because the guard is the feature: a caller that wants to know
    whether a string would be accepted should ask this rather than re-derive it.
    """
    stripped = _without_comments(sql).strip().rstrip(";").strip()
    if not stripped:
        return "Empty query. Write one SELECT statement."
    if ";" in stripped:
        return (
            "Only one statement per call. Send a single SELECT — the part before "
            "the first ';' — and call again for the next one."
        )
    head = stripped.split(None, 1)[0].lower()
    if head not in ("select", "with"):
        return (
            f"Refused: this tool runs one read-only statement and '{head.upper()}' "
            "is not one. Write a SELECT, or a WITH ... SELECT."
        )
    if head == "with" and not re.search(r"\bselect\b", stripped, re.I):
        return "A WITH clause must end in a SELECT."
    if re.search(r"\binto\b", stripped, re.I) and not re.search(
        r"\binsert\s+into\b", stripped, re.I
    ):
        # `SELECT … INTO other FROM …` writes a table while reading like a read.
        return (
            "Refused: SELECT ... INTO creates a table. Return the rows instead "
            "and let the caller keep them."
        )
    return None


def tables_named(sql: str) -> set[str]:
    """Every table the statement reads, lowercased, schema qualification kept.

    Read after `statement_refusal` has passed, so the only shapes reaching here
    are a `SELECT` and a `WITH … SELECT`.
    """
    found: set[str] = set()
    text = _without_comments(sql)
    for keyword in _TABLE_KEYWORDS:
        for match in re.finditer(rf"\b{keyword}\s+([^\s,()]+)", text, re.I):
            name = _IDENTIFIER.match(match.group(1).strip())
            if not name:
                continue
            schema, table = name.group(1), name.group(2)
            found.add(f"{schema}.{table}".lower() if table else schema.lower())
    return found


def pins_from(document: dict[str, Any]) -> set[str]:
    """Every physical table any resolver pinned — the allowlist itself.

    The **values** of `resolvers.*.pin`, never its keys: a key is the logical
    name and a value is the version a human chose.
    """
    pins: set[str] = set()
    resolvers = document.get("resolvers")
    if not isinstance(resolvers, dict):
        return pins
    for resolver in resolvers.values():
        pin = (resolver or {}).get("pin") if isinstance(resolver, dict) else None
        if isinstance(pin, dict):
            pins.update(str(value).lower() for value in pin.values() if value)
    return pins


@contextlib.contextmanager
def _connect(dsn: str) -> Iterator[Any]:
    """The one driver seam — lazy, uncommitted, always closed.

    Lazy so the base wheel carries no driver and the unconfigured path needs
    none. `autocommit=False` with an unconditional `rollback()` is the half of
    read-only the driver can actually give; the other half is
    `statement_refusal`.
    """
    pyodbc = importlib.import_module("pyodbc")
    connection = pyodbc.connect(dsn, autocommit=False)
    try:
        yield connection
    finally:
        with contextlib.suppress(Exception):
            connection.rollback()
        with contextlib.suppress(Exception):
            connection.close()


class MssqlQueryArgs(BaseModel):
    model_config = {"extra": "forbid"}
    query: str = Field(description="A single read-only T-SQL SELECT statement.")
    max_rows: int | None = Field(default=None, ge=1, le=1000)


class MssqlQueryTool(_SqlExplorerBase):
    """One T-SQL SELECT, against tables an allowlist pinned."""

    name = "mssql_query"
    node_type = "tool.mssql-query"
    description = (
        "Run one read-only T-SQL SELECT against the configured MSSQL database. "
        "Only tables pinned in the workflow's allowlist may be named; the "
        "refusal lists them."
    )
    Args = MssqlQueryArgs

    def __init__(
        self,
        *,
        connection: str = DEFAULT_CONNECTION_ENV,
        allowlist: str = "",
        row_cap: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.connection = connection
        self.allowlist = allowlist
        self.row_cap = row_cap

    def configure(self, data: dict[str, Any]) -> "MssqlQueryTool":
        connection = str(data.get("connection") or "").strip() or self.connection
        allowlist = str(data.get("allowlist") or "").strip() or self.allowlist
        row_cap = self._row_cap_from(data, self.row_cap)
        return type(self)(connection=connection, allowlist=allowlist, row_cap=row_cap)

    # -- the three refusals that happen before a socket is opened ------------

    def _dsn(self) -> tuple[str, str | None]:
        """`(dsn, refusal)` — the variable's value, or why there is none."""
        name = (self.connection or "").strip()
        if not name:
            return "", (
                "No connection variable configured. Set the node's 'connection' "
                f"field to the NAME of an environment variable, e.g. "
                f"'{DEFAULT_CONNECTION_ENV}'."
            )
        if not _ENV_NAME.match(name):
            return "", (
                "The 'connection' field holds the NAME of an environment variable, "
                "not a connection string — a workflow document is committed. Set it "
                f"to a name such as '{DEFAULT_CONNECTION_ENV}' and put the "
                "connection string in that variable."
            )
        value = os.environ.get(name, "").strip()
        if not value:
            return "", (
                f"The environment variable '{name}' is unset or empty, so there is no "
                "database to read. Set it to an ODBC connection string and run again; "
                "no query was sent."
            )
        return value, None

    def _pins(self) -> tuple[set[str], str | None]:
        """`(pins, refusal)` — the allowlist's pinned tables, or why not."""
        configured = (self.allowlist or "").strip()
        if not configured:
            return set(), (
                "No allowlist configured. Set the node's 'allowlist' field to a YAML "
                "file inside workflows/ whose resolvers carry 'pin:' entries; without "
                "one this tool refuses every query rather than exposing the warehouse."
            )
        root = workflows_root()
        candidate = (root / configured).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return set(), (
                f"The allowlist '{configured}' resolves outside the workflows root. "
                "Give a path relative to it, e.g. 'my-flow/lenses.yaml'."
            )
        if not candidate.is_file():
            return set(), f"No allowlist file at '{configured}' inside the workflows root."
        import yaml

        try:
            document = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            return set(), f"The allowlist '{configured}' is not readable YAML: {exc}"
        pins = pins_from(document if isinstance(document, dict) else {})
        if not pins:
            return set(), (
                f"The allowlist '{configured}' names no pinned tables. Every readable "
                "table is a value under some resolver's 'pin:' map."
            )
        return pins, None

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, MssqlQueryArgs)

        pins, refusal = self._pins()
        if refusal:
            return ToolResult.failure(refusal)

        refusal = statement_refusal(args.query)
        if refusal:
            return ToolResult.failure(refusal)

        unpinned = sorted(tables_named(args.query) - pins - self._local_names(args.query))
        if unpinned:
            return ToolResult.failure(
                f"Not in the allowlist: {', '.join(unpinned)}. "
                f"Readable tables are: {', '.join(sorted(pins))}."
            )

        dsn, refusal = self._dsn()
        if refusal:
            return ToolResult.failure(refusal)

        cap = min(args.max_rows or self.row_cap, self.row_cap)
        try:
            with _connect(dsn) as connection:
                cursor = connection.cursor().execute(args.query)
                headers = [d[0] for d in cursor.description or []]
                rows = list(cursor.fetchmany(cap + 1))
        except ModuleNotFoundError:
            return ToolResult.failure(
                "The MSSQL driver is not installed. Install the extra: "
                f"pip install '{DRIVER_EXTRA}'. No query was sent."
            )
        except Exception as exc:  # the server's own refusal, handed back as data
            return ToolResult.failure(
                f"The database refused the query: {exc}. Rewrite the SELECT against "
                f"the allowed tables: {', '.join(sorted(pins))}."
            )

        return ToolResult(content=self._capped_table(headers, rows, cap))

    @staticmethod
    def _local_names(sql: str) -> set[str]:
        """Names a `WITH` clause introduced — they are not warehouse tables.

        Without this, every CTE reads as an unpinned table and a legal query is
        refused for naming something the query itself defined.
        """
        return {
            match.group(1).lower()
            for match in re.finditer(
                r"(?:\bwith\b|,)\s*([A-Za-z_][\w$#]*)\s+as\s*\(", _without_comments(sql), re.I
            )
        }


MSSQL_TOOLS = [MssqlQueryTool()]
