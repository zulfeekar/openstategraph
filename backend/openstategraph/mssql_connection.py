"""How `tool.mssql-query` logs in — the three shapes, resolved from named variables.

`osg-agent-experience/73`. The leaf knew exactly one way to reach a warehouse:
one environment variable holding a whole ODBC connection string. That is fine
until the login needs a secret, because a connection string is where the secret
then has to be pasted — beside a `SQL_AZURE_AD_CLIENT_SECRET` that already held
it — and it is fatal when the driver's own Azure AD flow is the thing that is
broken.

**The measurement this module exists for.** On 2026-09-06 the try project's
warehouse refused every query for a day with `HYT00 Login timeout expired`. TCP
reached the server in 0.14 s and Azure AD in 0.16 s; ODBC Driver 18's own
`Authentication=ActiveDirectoryServicePrincipal` flow hung for the full login
timeout and then reported a timeout. Fetching the token ourselves — MSAL client
credentials against `https://database.windows.net/.default` — reached Azure AD
at once and got back the cause the driver had swallowed: **AADSTS7000222, the
client secret is expired.** A wrong credential and an unreachable server had
been the same symptom for a day.

So the driver is never asked to do Azure AD. We acquire the token and hand it
over as `SQL_COPT_SS_ACCESS_TOKEN`, and a refusal arrives in the time one HTTPS
round trip takes, naming the AAD code.

Three shapes, in this order:

1. **A URL.** The variable the node's `connection` field names — by default
   `OPENSTATEGRAPH_MSSQL_URL`. Set, it wins: somebody who wrote a connection
   string meant it, and this module does not second-guess it.
2. **Parts plus an Azure AD service principal.** `MSSQL_DB_SERVER`,
   `MSSQL_DB_NAME` (`MSSQL_DB_PORT` optional) with
   `SQL_AZURE_AD_TENANT_ID`, `SQL_AZURE_AD_CLIENT_ID` and
   `SQL_AZURE_AD_CLIENT_SECRET`. The token route.
3. **Parts plus SQL authentication.** The same three, with `MSSQL_DB_USER` and
   `MSSQL_DB_PASSWORD`.

The trio outranks the user/password pair when both are complete, because the
trio is the shape somebody sets up deliberately and a stale `MSSQL_DB_USER` is
the shape somebody leaves behind. That decision has a consequence, and it is
enforced rather than trusted: on the token route the composed string is stripped
of `Authentication=`, `UID=` and `PWD=`, because ODBC takes a password beside an
access token as an instruction to try the password.

**Names, never values, in anything committed.** This module reads a mapping —
`os.environ` at the call site — and every sentence it can return names variables
and never their contents. `ConnectionPlan` redacts itself in `repr` for the same
reason: a plan holds a composed string with a password in it, and a plan reaches
a traceback the day something else goes wrong.
"""

from __future__ import annotations

import importlib
import re
import struct
from dataclasses import dataclass, field
from typing import Any, Mapping

from openstategraph.install_hint import install_hint

__all__ = [
    "AAD_SCOPE",
    "ACCESS_TOKEN_ATTRIBUTE",
    "AAD_VARS",
    "DEFAULT_ODBC_DRIVER",
    "DEFAULT_PORT",
    "DRIVER_EXTRA",
    "PART_VARS",
    "SQL_AUTH_VARS",
    "ConnectionPlan",
    "resolve_connection",
]

#: The extra that carries both optional imports this leaf can make — the ODBC
#: driver and the token library. Named in every refusal that needs one, because
#: the refusal is where somebody is standing when they need it.
DRIVER_EXTRA = "openstategraph[mssql]"

#: `SQL_COPT_SS_ACCESS_TOKEN`. The number rather than a symbol because pyodbc
#: publishes no constant for it and the ODBC header is not a dependency.
ACCESS_TOKEN_ATTRIBUTE = 1256

#: The only scope an Azure SQL access token is issued for.
AAD_SCOPE = "https://database.windows.net/.default"

#: The server, database and port — read by both part-based shapes. `port` is
#: optional; the other two are not.
PART_VARS = ("MSSQL_DB_SERVER", "MSSQL_DB_NAME")
PORT_VAR = "MSSQL_DB_PORT"
DEFAULT_PORT = "1433"

#: SQL authentication.
SQL_AUTH_VARS = ("MSSQL_DB_USER", "MSSQL_DB_PASSWORD")

#: An Azure AD service principal. All three or none — a pair is a setup half
#: done, and saying which one is missing is the whole point of this module.
AAD_VARS = (
    "SQL_AZURE_AD_TENANT_ID",
    "SQL_AZURE_AD_CLIENT_ID",
    "SQL_AZURE_AD_CLIENT_SECRET",
)

#: Overridable because 17 and 18 are both in the field and the difference is
#: not ours to decide. A name, not a secret, so it composes like the rest.
ODBC_DRIVER_VAR = "MSSQL_ODBC_DRIVER"
DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"

#: Keys that tell ODBC to authenticate some other way. Removed from a composed
#: string on the token route: a driver handed both a token and a password tries
#: the password, which is how the flow this module replaced used to hang.
_AUTH_KEYS = re.compile(r"(?:^|;)\s*(?:Authentication|UID|PWD)\s*=[^;]*", re.I)


def _strip_auth_keys(connection_string: str) -> str:
    """`Authentication=`, `UID=` and `PWD=` removed, whatever their case."""
    stripped = _AUTH_KEYS.sub("", connection_string)
    return re.sub(r";{2,}", ";", stripped).strip(";")


@dataclass(frozen=True)
class ConnectionPlan:
    """Everything `pyodbc.connect` needs, and nothing anybody may print.

    `attrs_before` is empty on every shape but the token one, so the caller
    passes it unconditionally and the driver sees an access token only when we
    fetched one.
    """

    connection_string: str = field(repr=False)
    attrs_before: dict[int, bytes] = field(default_factory=dict, repr=False)
    #: `url`, `azure-ad` or `sql-auth` — which shape answered. For a refusal or
    #: a log line; never carries a value.
    shape: str = "url"

    def __repr__(self) -> str:  # pragma: no cover - exercised through tests
        held = "an access token" if self.attrs_before else "no access token"
        return f"ConnectionPlan(shape={self.shape!r}, redacted, {held})"


def _present(env: Mapping[str, str], names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if (env.get(name) or "").strip())


def _missing(env: Mapping[str, str], names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if not (env.get(name) or "").strip())


def _compose(env: Mapping[str, str]) -> str:
    """The three parts as an ODBC string, encryption on and no credential yet."""
    driver = (env.get(ODBC_DRIVER_VAR) or "").strip() or DEFAULT_ODBC_DRIVER
    server = (env.get("MSSQL_DB_SERVER") or "").strip()
    port = (env.get(PORT_VAR) or "").strip() or DEFAULT_PORT
    database = (env.get("MSSQL_DB_NAME") or "").strip()
    return (
        f"Driver={{{driver}}};Server=tcp:{server},{port};Database={database};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30"
    )


def _nothing_configured(env: Mapping[str, str], url_name: str) -> str:
    """Which of the three shapes is configured, and what each one still needs.

    The readiness door for this connector. There is no `openstategraph
    connectors` verb to carry it, and inventing one would put the sentence two
    places (`osg-agent-experience/73`); the refusal is where a person actually
    stands when the answer matters, and it names variables rather than
    describing them.
    """
    parts_missing = _missing(env, PART_VARS)
    lines = [
        f"No MSSQL connection configured. '{url_name}' is unset, so the "
        "connection is composed from named variables instead — and none of the "
        "three shapes is complete:",
        f"  URL: set '{url_name}' to a whole ODBC connection string.",
    ]
    if parts_missing:
        needs = ", ".join(parts_missing)
        lines.append(
            f"  Parts: {needs} still unset (optional: {PORT_VAR}, default "
            f"{DEFAULT_PORT}; {ODBC_DRIVER_VAR}, default '{DEFAULT_ODBC_DRIVER}')."
        )
    else:
        lines.append(f"  Parts: {', '.join(PART_VARS)} are set.")
        for label, names in (("Azure AD", AAD_VARS), ("SQL auth", SQL_AUTH_VARS)):
            absent = _missing(env, names)
            if absent:
                lines.append(f"  {label}: {', '.join(absent)} still unset.")
    lines.append("No query was sent.")
    return "\n".join(lines)


def _token(env: Mapping[str, str]) -> tuple[bytes, str | None]:
    """`(the attribute's bytes, refusal)` — one HTTPS round trip, never a hang.

    UTF-16-LE and length-prefixed is what `SQL_COPT_SS_ACCESS_TOKEN` is
    specified to take; a token passed any other way is rejected by the driver
    with a message about the *connection*, not about the token.
    """
    try:
        msal = importlib.import_module("msal")
    except ModuleNotFoundError:
        return b"", (
            "An Azure AD service principal is configured "
            f"({', '.join(AAD_VARS)}), but the token library is not installed. "
            f"Install it with: {install_hint(DRIVER_EXTRA)}. No query was sent."
        )

    tenant = (env.get("SQL_AZURE_AD_TENANT_ID") or "").strip()
    application: Any = msal.ConfidentialClientApplication(
        (env.get("SQL_AZURE_AD_CLIENT_ID") or "").strip(),
        authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=(env.get("SQL_AZURE_AD_CLIENT_SECRET") or "").strip(),
    )
    try:
        answer = application.acquire_token_for_client(scopes=[AAD_SCOPE]) or {}
    except Exception as exc:  # a network refusal, handed back as data
        return b"", (
            f"Azure AD could not be reached for a token: {exc}. The service "
            f"principal is named by {', '.join(AAD_VARS)}. No query was sent."
        )

    access_token = str(answer.get("access_token") or "")
    if not access_token:
        code = str(answer.get("error") or "unknown_error")
        description = str(answer.get("error_description") or "").strip().splitlines()
        detail = description[0] if description else "no description was returned"
        return b"", (
            f"Azure AD refused the service principal ({code}): {detail} "
            f"The credential is the value of 'SQL_AZURE_AD_CLIENT_SECRET'; "
            "no query was sent."
        )

    encoded = access_token.encode("utf-16-le")
    return struct.pack("<i", len(encoded)) + encoded, None


def resolve_connection(
    env: Mapping[str, str], *, url: str = "", url_name: str = "OPENSTATEGRAPH_MSSQL_URL"
) -> tuple[ConnectionPlan | None, str | None]:
    """`(plan, refusal)` — how to log in, or which variable is missing by name.

    `url` is the already-resolved value of the node's connection variable; the
    leaf reads it, because the *name* of that variable is a field on the card
    and only the leaf knows it. Everything else is read from `env` here.
    """
    if url.strip():
        return ConnectionPlan(connection_string=url.strip(), shape="url"), None

    if _missing(env, PART_VARS) or not (
        _present(env, AAD_VARS) == AAD_VARS or _present(env, SQL_AUTH_VARS) == SQL_AUTH_VARS
    ):
        return None, _nothing_configured(env, url_name)

    composed = _compose(env)

    if _present(env, AAD_VARS) == AAD_VARS:
        attribute, refusal = _token(env)
        if refusal:
            return None, refusal
        return (
            ConnectionPlan(
                connection_string=_strip_auth_keys(composed),
                attrs_before={ACCESS_TOKEN_ATTRIBUTE: attribute},
                shape="azure-ad",
            ),
            None,
        )

    user = (env.get("MSSQL_DB_USER") or "").strip()
    password = (env.get("MSSQL_DB_PASSWORD") or "").strip()
    return (
        ConnectionPlan(
            connection_string=f"{composed};UID={user};PWD={password}",
            shape="sql-auth",
        ),
        None,
    )
