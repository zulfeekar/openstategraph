"""What a run actually executed, published so a person can read it.

## The gap this closes

`one-chinook-honest/30`. Neither `/api/runs` nor the SSE `done` frame said
which statement an agent sent. Two correctness diagnoses in one day had to
reconstruct the queries **from the model's own prose about what it did** — the
one artifact that cannot be trusted when the model got it wrong, and the
failure shape this project names repeatedly: the instrument agrees with the
thing it is supposed to check.

`launch-readiness/165` had already built the record. `tool_report` writes the
exchange to `tool_use[node]["queries"]` because `_agent` returns no `messages`
and every gate reading `state["messages"]` was blind on the agent rail. That
record is **graph state**: `counted_rows`, `grounded_numbers` and
`table_coverage` read it, and nothing published it. A run could be *judged* by
what it executed and could not be *asked*. This module is the asking.

## Why this is not a SQL feature

"What did this tool actually do" is the general question, so a published row is
`{node, tool, statement, result, truncated}` and says `statement`, never `sql`.
What stays narrow is what may *enter* the record: only a call argument some
recogniser accepted as a statement — today `looks_like_sql_query`, matched by
**shape and never by tool name** (`production-ready/95`), so a tool called
`warehouse` is read exactly as well as `mcp_execute_sql`. A second recogniser
joins by naming itself in `tool_report`, with no change to this channel, to
`DeveloperChannelResponse`, or to any client.

That is `CLAUDE.md`'s read-tolerantly/trust-strictly rule applied to a record
rather than to a parse, and it is also the credential answer.

## No credential can appear, and the first reason is structural

The record carries **one argument** — the one recognised as a statement — and
never the argument map. So an MCP tool's `connection_string`, `headers`,
`token` or `password` argument is not recorded at all, rather than recorded and
then scrubbed. A scrub that has to be right every time eventually is not; an
argument that was never copied cannot leak.

`scrubbed` is the second layer, for a credential embedded *inside* a statement
or its result — a DSN in a comment, an ODBC `PWD=`, a bearer token, a
key-shaped literal. It removes the value and **says it removed something**:
silent removal would be two situations rendering identically, which is the
defect this whole map is named after.

Its narrowness is the part that will regress. `SELECT secret_ingredient FROM
recipes` is an ordinary statement, and a scrubber that eats it teaches people
to distrust the record. So every widening owes the test that proves an
ordinary statement is still left byte-for-byte alone.

## Which audience

The developer one, and only that. It quotes node ids, tool names, table names
and literal values from a customer's own data — `143` binds what customer copy
may say, and `163` established the pattern one field along: the evidence rides
a developer-gated field, the customer keeps the sentence. `api/audience.py`
carries the table this row is declared in.
"""

from __future__ import annotations

import re
from typing import Any

from openstategraph.config_file import SECRET_VALUE_PREFIXES

#: What replaces a credential, wherever one is found. A marker rather than a
#: deletion: a reader must be able to tell "this statement had no password"
#: from "this statement's password is not shown".
REDACTED = "[redacted]"

#: A URI DSN's password — everything between the first `:` after the scheme's
#: credentials and the `@` that ends them. Same shape `postgres.redacted`
#: removes for logs; declared again here rather than imported because that
#: module owns *connecting*, and importing a driver seam into a transport one
#: to borrow a regex is the dependency this codebase declines.
_URI_PASSWORD = re.compile(r"(://[^\s:/@]+:)([^\s@/]+)(@)")

#: A keyword/value DSN's or ODBC connection string's password, whatever it is
#: spelled: `password=`, `pwd=`, `passwd=`. Bounded by whitespace, `;` or a
#: quote, which is every terminator these grammars use.
_KEYWORD_PASSWORD = re.compile(
    r"((?:password|passwd|pwd)\s*=\s*)([^\s;'\"]+)", re.IGNORECASE
)

#: An `Authorization: Bearer <token>` header pasted into a statement or
#: returned in an error envelope.
_BEARER = re.compile(r"(Bearer\s+)(\S+)")

#: Value shapes that are unambiguously credentials, borrowed **by import**
#: from `config_file.SECRET_VALUE_PREFIXES` so there is one list of them in
#: this codebase rather than two that drift. Matched as a whole token so a
#: column named `sk_id` is not mistaken for a key.
_KEY_SHAPED = re.compile(
    r"\b(?:"
    + "|".join(re.escape(prefix) for prefix in SECRET_VALUE_PREFIXES if prefix.strip())
    + r")[A-Za-z0-9_\-.]{6,}"
)


def scrubbed(text: str) -> str:
    """`text` with any recognisable credential replaced by `REDACTED`.

    Applied to both halves of a published row. A statement legitimately
    embeds *values* — that is what makes it evidence — so this removes only
    what is recognisably a credential, and every pattern here is one that has
    no other meaning.
    """
    if not text:
        return text
    out = _URI_PASSWORD.sub(rf"\1{REDACTED}\3", text)
    out = _KEYWORD_PASSWORD.sub(rf"\1{REDACTED}", out)
    out = _BEARER.sub(rf"\1{REDACTED}", out)
    return _KEY_SHAPED.sub(REDACTED, out)


def statements_executed(tool_use: Any) -> list[dict[str, Any]]:
    """Every statement this run sent, in the order the record holds them.

    Reads `tool_use[node]["queries"]`, written by `tool_report`. Tolerant
    about the shape for the reason `run_health` and `used_no_tools` are: the
    two run doors read state off different assemblies, a mounted child or an
    older checkpoint may have written neither key, and a record that cannot be
    read is worth an empty list rather than a 500 on a run that answered.

    Copies exactly five fields and never the row it came from, so a later key
    on the internal record cannot widen a published channel by accident —
    `redaction_report`'s rule, for `redaction_report`'s reason.

    `truncated` is present on **every** row, never only on the cut ones. The
    cap `155` put on a recorded result is why this module exists in the shape
    it does: a result that ended and a result the cap took render identically
    unless something says which happened, and a reader who has to know that
    absence means whole has been told nothing.
    """
    rows = tool_use if isinstance(tool_use, dict) else {}
    report: list[dict[str, Any]] = []
    for node_id, row in rows.items():
        if not isinstance(row, dict):
            continue
        for exchange in row.get("queries") or []:
            if not isinstance(exchange, dict):
                continue
            statement = scrubbed(str(exchange.get("sql") or ""))
            if not statement:
                continue
            report.append(
                {
                    "node": str(node_id),
                    "tool": str(exchange.get("tool") or ""),
                    "statement": statement,
                    "result": scrubbed(str(exchange.get("result") or "")),
                    "truncated": bool(exchange.get("truncated")),
                }
            )
    return report
