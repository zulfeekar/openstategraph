"""What every warehouse dialect shares — the rung `osg-agent-experience/40` split out.

`39` split the SQL family once: `_SqlExplorerBase` kept what no dialect can
change (reading is not a side effect, the `maxRows` parse, the truncation-aware
markdown table) and `_SqliteExplorerBase` kept the file. It left the *warehouse*
concerns — the statement gate, the allowlist, the environment-variable name, the
shape of one query's execution — sitting inside `prebuilt_mssql.py`, where they
read as T-SQL's because that was the only leaf.

They are not. `40`'s own question was the test: *"if a leaf needs more than a
driver, a connection and a dialect name to exist, the base is wrong."* Building
`tool.databricks-query` against the module as `39` left it would have meant
copying two hundred lines of gate and allowlist into a second file, which is the
duplication-of-knowledge defect `CLAUDE.md` names — two copies of one rule, and
the second copy is the one that stops being fixed.

So this rung holds the four things a warehouse leaf inherits rather than repeats:

1. **The statement gate.** Exactly one statement, and a `SELECT` or a
   `WITH … SELECT`, with comments stripped first so `/**/dRoP` is not a comment.
   This is the string matching the SQLite module was right to avoid and no
   warehouse driver lets us avoid.
2. **The allowlist.** A YAML inside the workflows root whose `resolvers.*.pin`
   **values** are the only tables a query may name.
3. **The environment-variable name.** A field holds the *name* of a variable,
   never its value: a workflow document is committed (honesty gate 13). A pasted
   value is refused as a value and is never echoed back — including one that is
   also a legal variable name, which is why `looks_like_a_secret` is consulted
   as well as the regex.
4. **The order the refusals happen in**, which is itself a decision: the
   allowlist and the statement gate are checked *before* a connection is
   resolved, so a query that could never be allowed does not need a warehouse to
   be refused, and an unconfigured node still answers usefully.

A leaf supplies exactly three things: `_connection()` (the environment variables
it reads, resolved to whatever its driver's `connect` wants), `_open()` (the one
lazy driver seam), and the two `_driver_*` strings that name its extra in a
refusal. That is the shape `40` asserts.

**Read-only is a weaker word here than in `prebuilt_sql`, for every dialect.**
SQLite gets `mode=ro`, a property of the *file*, so however a write is spelled
the engine refuses it. No warehouse driver in this family offers an equivalent,
and the two strings an experienced reader reaches for are not one:
`ApplicationIntent=ReadOnly` is an availability-group **routing** hint, and
Databricks SQL has no session-level read-only at all. So the guarantee is the
statement gate plus the allowlist, and a workflow that needs the strong version
wants a login that cannot write. Whether a leaf can *also* decline to commit is
a property of its driver, not of this rung — `MssqlQueryTool` can and does;
`DatabricksQueryTool` says in its own docstring that it cannot.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable

from pydantic import BaseModel, Field

from openstategraph.abc.tool import ToolResult
from openstategraph.config_file import looks_like_a_secret
from openstategraph.prebuilt_sql import DEFAULT_MAX_ROWS, _SqlExplorerBase
from openstategraph.workflows_root import workflows_root

#: A POSIX environment-variable name. Anything else in a connection field is a
#: value somebody pasted, and is refused without being echoed.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: The keywords after which SQL names a table. Deliberately small: this is a
#: gate on what a query may *read*, run after the statement gate has already
#: established that the statement is a single `SELECT`. A keyword that belongs
#: to only one dialect (`apply` is T-SQL's) is kept for all of them — a keyword
#: no dialect uses can only cause a name to be *checked*, never to be admitted.
_TABLE_KEYWORDS = ("from", "join", "into", "update", "apply")

#: One dotted part of an identifier, brackets and quotes tolerated the way both
#: dialects write them. Matched part by part rather than by one regex with two
#: capture groups, which is what `34` wrote: two groups cannot see the third
#: part of `main.sales.invoice_line`, and Unity Catalog names are three parts.
#: The old regex read that as the table `main.sales`, which no pin can name, so
#: a legal Databricks query was refused with a sentence that could not be acted
#: on.
_PART = re.compile(r'[\[\]"`]?([A-Za-z_][\w$#]*)')


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


def _identifier(token: str) -> str | None:
    """`main.sales.invoice_line` → `main.sales.invoice_line`, quoting stripped.

    Every dotted part, not the first two: a two-group regex cannot see a Unity
    Catalog name, and silently reading one as its first two parts refuses a
    legal query for naming a table nobody wrote.
    """
    names: list[str] = []
    for part in token.split("."):
        match = _PART.match(part)
        if not match:
            break
        names.append(match.group(1).lower())
    return ".".join(names) if names else None


def tables_named(sql: str) -> set[str]:
    """Every table the statement reads, lowercased, qualification kept.

    Read after `statement_refusal` has passed, so the only shapes reaching here
    are a `SELECT` and a `WITH … SELECT`.
    """
    found: set[str] = set()
    text = _without_comments(sql)
    for keyword in _TABLE_KEYWORDS:
        for match in re.finditer(rf"\b{keyword}\s+([^\s,()]+)", text, re.I):
            name = _identifier(match.group(1).strip())
            if name:
                found.add(name)
    return found


def resolver_names(document: dict[str, Any]) -> list[str]:
    """Every resolver key the allowlist declares, in the order it wrote them.

    The vocabulary a `pins` selector is written against, so a refusal can name
    what a mistyped scope could have said instead of only what it was not.
    """
    resolvers = document.get("resolvers")
    if not isinstance(resolvers, dict):
        return []
    return [str(key) for key in resolvers]


def pins_from(document: dict[str, Any], scope: Iterable[str] = ()) -> set[str]:
    """Every physical table the named resolvers pinned — the allowlist itself.

    The **values** of `resolvers.*.pin`, never its keys: a key is the logical
    name and a value is the version a human chose.

    `scope` narrows to those resolver keys, matched case-insensitively; empty
    means every resolver, which is what a single-package workflow wants and is
    what this function did before `osg-agent-experience/61`.
    """
    wanted = {str(name).strip().lower() for name in scope if str(name).strip()}
    pins: set[str] = set()
    resolvers = document.get("resolvers")
    if not isinstance(resolvers, dict):
        return pins
    for key, resolver in resolvers.items():
        if wanted and str(key).strip().lower() not in wanted:
            continue
        pin = (resolver or {}).get("pin") if isinstance(resolver, dict) else None
        if isinstance(pin, dict):
            pins.update(str(value).lower() for value in pin.values() if value)
    return pins


class WarehouseQueryArgs(BaseModel):
    """The arguments every warehouse leaf takes.

    A leaf redeclares `query` only to name its own dialect in the description —
    that sentence is what an agent reads before it writes SQL, and "T-SQL" and
    "Databricks SQL" are genuinely different instructions. Duplication of shape,
    not of knowledge.
    """

    model_config = {"extra": "forbid"}
    query: str = Field(description="A single read-only SELECT statement.")
    max_rows: int | None = Field(default=None, ge=1, le=1000)


class _WarehouseExplorerBase(_SqlExplorerBase):
    """A read of a warehouse: the gate, the allowlist, and one query's run.

    Beside `_SqliteExplorerBase` rather than under it, for `39`'s reason: that
    rung's members name a `.sqlite` path inside `workflows/` and no warehouse
    has one.
    """

    #: Named by a leaf. `_driver_extra` is what a refusal tells somebody to
    #: install, and `_driver_label` is what it calls the thing that is missing.
    #: Protected rather than public on purpose: they are wiring between this
    #: rung and its leaves, not surface a consumer of the tool reads.
    _driver_extra = ""
    _driver_label = "database"

    def __init__(
        self, *, allowlist: str = "", pins: str = "", row_cap: int = DEFAULT_MAX_ROWS
    ) -> None:
        self.allowlist = allowlist
        self.pins = pins
        self.row_cap = row_cap
        self.description = self._described()

    # -- what a leaf supplies ------------------------------------------------

    def _connection(self) -> tuple[tuple[Any, ...], str | None]:
        """`(driver arguments, refusal)` — resolved from the environment."""
        raise NotImplementedError

    def _open(self, target: tuple[Any, ...]) -> Any:
        """A context manager yielding a DB-API connection. The one driver seam."""
        raise NotImplementedError

    # -- the refusals that happen before a socket is opened ------------------

    def _env_value(
        self, *, key: str, name: str, default: str, holds: str, required: bool = True
    ) -> tuple[str, str | None]:
        """`(value, refusal)` — a named variable's value, or why there is none.

        Three refusals, and the middle one is the reason this is a helper
        rather than three lines in a leaf: a field labelled *name* will have a
        value pasted into it, and the refusal must not echo what was pasted.
        The regex alone is not enough — a Databricks personal access token is
        also a legal environment-variable name — so the maintained prefix list
        is consulted too, exactly as `prebuilt_mcp` does.

        `required=False` drops **only the third** refusal, returning `("", None)`
        for a variable that is simply unset, and it exists because
        `osg-agent-experience/73` gave one leaf a second way to log in: with
        `OPENSTATEGRAPH_MSSQL_URL` unset the T-SQL leaf composes its connection
        from named parts, so "unset" is a fork rather than a refusal there. The
        first two refusals are unconditional for every leaf — a field that holds
        a pasted value is a committed credential whichever shape answers next.
        """
        configured = (name or "").strip()
        if not configured:
            return "", (
                f"No '{key}' variable configured. Set the node's '{key}' field to the "
                f"NAME of an environment variable, e.g. '{default}'."
            )
        if not _ENV_NAME.match(configured) or looks_like_a_secret(configured):
            return "", (
                f"The '{key}' field holds the NAME of an environment variable, not "
                f"{holds} — a workflow document is committed. Set it to a name such "
                f"as '{default}' and put the value in that variable."
            )
        value = os.environ.get(configured, "").strip()
        if not value:
            if not required:
                return "", None
            return "", (
                f"The environment variable '{configured}' is unset or empty, so there "
                f"is nothing to connect to. Set it to {holds} and run again; no query "
                "was sent."
            )
        return value, None

    def _scope(self) -> tuple[str, ...]:
        """The resolver keys this binding declared, if any.

        Commas or whitespace, because both are what somebody types into a
        one-line field and neither is a legal resolver key.
        """
        return tuple(part for part in re.split(r"[,\s]+", self.pins or "") if part)

    def _described(self) -> str:
        """This binding's own sentence for the model, tables named.

        The gate is only half of `osg-agent-experience/61`: the other half is
        that the schema a mounted specialist's model is *offered* named every
        table in the shared file, so the model was invited to write a query
        the gate would then refuse. The description is therefore an instance
        attribute, resolved once at bind time from whatever this binding can
        actually read.

        Silent when the allowlist does not resolve: an unconfigured tool in a
        registry has nothing to name, and a broken path is the refusal's job
        to explain, not the schema's.
        """
        base = type(self).description
        if not (self.allowlist or "").strip():
            return base
        try:
            pins, refusal = self._pins()
        except Exception:  # a workflows root that will not resolve at import time
            return base
        if refusal or not pins:
            return base
        return f"{base} Readable tables for this binding: {', '.join(sorted(pins))}."

    def _pins(self) -> tuple[set[str], str | None]:
        """`(pins, refusal)` — the tables *this binding* may read, or why not.

        Scoped by `pins` since `osg-agent-experience/61`. One shared,
        hand-curated allowlist and fifteen mounted specialists was the shape
        that made this necessary, and the rejected alternative — fifteen
        copies of the file — is the drift the file exists to prevent.
        """
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
        document = document if isinstance(document, dict) else {}
        scope = self._scope()
        names = resolver_names(document)
        if scope:
            known = {name.strip().lower() for name in names}
            unknown = [part for part in scope if part.strip().lower() not in known]
            if unknown:
                return set(), (
                    f"The 'pins' field names {', '.join(unknown)}, which the allowlist "
                    f"'{configured}' has no resolver for. Its resolvers are: "
                    f"{', '.join(names) or '(none)'}."
                )
        pins = pins_from(document, scope)
        if not pins:
            where = f" under {', '.join(scope)}" if scope else ""
            return set(), (
                f"The allowlist '{configured}' names no pinned tables{where}. Every "
                "readable table is a value under some resolver's 'pin:' map."
            )
        return pins, None

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

    # -- one query, in the order the refusals have to happen ------------------

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, WarehouseQueryArgs)

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

        target, refusal = self._connection()
        if refusal:
            return ToolResult.failure(refusal)

        cap = min(args.max_rows or self.row_cap, self.row_cap)
        try:
            with self._open(target) as connection:
                cursor = connection.cursor().execute(args.query)
                headers = [d[0] for d in cursor.description or []]
                rows = list(cursor.fetchmany(cap + 1))
        except ModuleNotFoundError:
            return ToolResult.failure(
                f"The {self._driver_label} driver is not installed. Install the extra: "
                f"pip install '{self._driver_extra}'. No query was sent."
            )
        except Exception as exc:  # the server's own refusal, handed back as data
            return ToolResult.failure(
                f"The database refused the query: {exc}. Rewrite the SELECT against "
                f"the allowed tables: {', '.join(sorted(pins))}."
            )

        return ToolResult(content=self._capped_table(headers, rows, cap))
