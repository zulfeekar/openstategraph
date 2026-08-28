"""`tool.mcp` — one card, a whole MCP server's tools.

Every other atom in this repository is one node → one tool, and every one of
them is a synchronous `func`. An MCP server is one node → **N** tools, and
those tools are `coroutine`-only. Both of those are structural, so both are
answered structurally rather than worked around:

- **Plural.** `BaseTool.as_langchain_tools()` is declared once on the base and
  defaults to `[self.as_langchain_tool()]`, so every existing atom is
  unchanged and the singular case is simply the plural case with one element.
- **Sync.** Each async tool is re-wrapped as a `StructuredTool` carrying the
  original `coroutine` *and* a `func`. Both entry points marshal the call onto
  the one long-lived loop in `mcp_sessions`, which is where the session lives.

## The handshake used to be half of every call

Until this was fixed, the two sentences below stood in this header as a
measured cost rather than as a defect:

> a call is 1.2–1.5 s, of which ≈0.8 s is reconnection. Roughly half of every
> MCP tool call is the handshake.

That was true, and it was ours. `MultiServerMCPClient` is stateless *by
default* — `get_tools()` builds tools carrying a `connection`, and the
adapters' tool body then re-opens the socket and re-runs `initialize` +
`notifications/initialized` + `tools/list` before every single `tools/call`.
The library's other arm takes a live `session` and calls it directly.

So `_discover_tools` now hands `load_mcp_tools` a **session** — a pooled
`McpSessionProxy` — and the handshake is paid once per server per process
instead of once per call. `asyncio.run` is gone from every entry point here
for the same reason: a loop per call is a session per call.

`mcp_sessions` carries the full account, including why the session needs a
loop of its own and why the proxy, not the raw session, is what gets handed
over.

## One card, N servers (ticket 04)

A `tool.mcp` node carries a **list of server rows**, not one server. The grill
that settled it is worth keeping: N servers on one node give up per-server
*routing*, because the card's output feeds one place and every row travels
together — and the case it was asked for, several services with one agent
choosing per task, is precisely where that costs nothing, because they already
share a consumer. The guidance the card carries is the same sentence: **one
node per group of servers that share a consumer**, a second node when two
agents need different servers.

What rows must *not* share is a fate. Discovery runs `asyncio.gather` across
them — one client per row rather than one client holding every connection,
because `get_tools()` over a multi-server client answers a failure as one
`ExceptionGroup` and a warning that cannot name a row is a warning nobody can
act on. So each row is reached independently, a sick row degrades to a
capability warning naming its ordinal and its server, and every healthy row
still binds.

## What is here and what is deliberately not

**HTTP only.** `streamable_http` and the deprecated `sse`. WebSocket cannot
carry a header, so it cannot carry a credential, so it cannot satisfy this
project's secrets rule. `stdio` spawns a subprocess per call and would let a
canvas document name an arbitrary executable — a security posture question,
not a dropdown entry. Both are decisions, recorded in
`.scratch/mcp-connect/research/01-adapters.md`.

**A name, never a value.** The document and the project config store the
*name* of the environment variable holding a credential. `resolve_auth_headers`
is the only place a value exists, it happens at bind time, and it never
appears in a warning, a log line or a response.

**Nothing here calls a model.** A test asserts it, so the card's claim that a
bound MCP server costs latency rather than tokens stays true.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence, cast

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult
from openstategraph.abc.tool_findings import result_envelope
from openstategraph.abc.tool_notes import (
    ToolFailure,
    ToolNote,
    notes_for_model,
    record_notes,
)
from openstategraph.abc.tool_sentences import describe_tool_call
from openstategraph.progress import NARRATES_ITSELF, report_progress

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- #
# Data keys. Module-level literals so the extractor in
# `test_data_key_contract.py` can see them, and so the TypeScript field
# schema has something stable to be compared against.
# --------------------------------------------------------------------- #

KEY_SERVERS = "servers"
KEY_SERVER = "server"
KEY_URL = "url"
KEY_TRANSPORT = "transport"
KEY_AUTH_KIND = "authKind"
KEY_AUTH_HEADER_NAME = "authHeaderName"
KEY_AUTH_TOKEN_ENV = "authTokenEnv"
KEY_TOOLS = "tools"
#: Keys on the **node's own** `data` — what `defaultsFrom(fields)` emits, and
#: therefore what the generated port table declares. Since ticket 04
#: everything a server is described by moved *into* a row, so this is the row
#: list and nothing else. Compared against the TypeScript declaration by
#: `test_mcp_field_contract.py`.
#:
#: It briefly also held `mcpGuide` and `mcpNote` — the card's two read-only
#: blocks — because the editor seeded them into every node's `data` and saved
#: them into the user's `workflow.json` (production-ready 52). They are
#: inspector prose declared on the schema, not configuration; a `readonly`
#: field is now display-only on both sides, so there is no key here to mirror.
MCP_NODE_KEYS = (KEY_SERVERS,)

#: Keys within one server row. The same seven the app-level panel renders flat,
#: because a row and a panel entry are the same field set in two containers —
#: `src/nodes/tools/mcpServerFields.ts` declares them once and the contract test
#: fails if the two vocabularies drift.
MCP_ROW_KEYS = (
    KEY_SERVER,
    KEY_URL,
    KEY_TRANSPORT,
    KEY_AUTH_KIND,
    KEY_AUTH_HEADER_NAME,
    KEY_AUTH_TOKEN_ENV,
    KEY_TOOLS,
)

#: The `StreamableHttpConnection` literal. Three spellings alias to one branch
#: in the library (`streamable_http` / `streamable-http` / `http`); one is
#: stored, and the UI labels it *HTTP*.
TRANSPORT_HTTP = "streamable_http"
#: Offered, labelled deprecated by the MCP spec. Legacy servers only.
TRANSPORT_SSE = "sse"
TRANSPORTS = (TRANSPORT_HTTP, TRANSPORT_SSE)

AUTH_NONE = "none"
AUTH_BEARER = "bearer"
AUTH_HEADER = "header"
AUTH_KINDS = (AUTH_NONE, AUTH_BEARER, AUTH_HEADER)

STATUS_LIVE = "live"
STATUS_UNREACHABLE = "unreachable"
STATUS_AUTH_REQUIRED = "auth_required"
STATUS_NOT_MCP = "not_mcp"
#: The one verdict that is about **this** machine. Every other status is a
#: fact about the remote server; this one says the extra that speaks MCP was
#: never installed, so nothing was ever asked. It is its own status rather
#: than a `not_mcp` with a better sentence because the badge is what a reader
#: acts on, and "not an MCP server" sends them to the URL box for a problem
#: `pip` fixes (mcp-connect ticket 05).
STATUS_NOT_INSTALLED = "not_installed"

#: Every verdict a handshake can reach, in the order the research's taxonomy
#: sets them out — `live` first, then the three facts about the server, then
#: the one fact about this machine.
#:
#: A tuple, beside `TRANSPORTS` and `AUTH_KINDS`, because those two had one and
#: this did not — so the three vocabularies this atom shares with the editor
#: were pinnable, pinnable and un-nameable (framework-packaging ticket 10).
#: `MCP_STATUSES` in `src/core/runtime/McpRegistryClient.ts` is the other half,
#: and `backend/tests/test_mcp_field_contract.py` holds them together.
MCP_STATUSES = (
    STATUS_LIVE,
    STATUS_UNREACHABLE,
    STATUS_AUTH_REQUIRED,
    STATUS_NOT_MCP,
    STATUS_NOT_INSTALLED,
)

#: `DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT` is **300 s** in the library, so a
#: server that accepts a connection and then says nothing would hang a panel
#: for five minutes and a compile for as long. Every handshake this module
#: makes is wrapped in this.
MCP_TIMEOUT_SECONDS = 15.0

#: A POSIX environment variable name. The field wants a name; this is how we
#: tell a name from the key somebody pasted into it by mistake.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _looks_like_a_secret(value: str) -> bool:
    """Reuses the config loader's own list rather than keeping a second one.

    Imported at the call site because `config_file` imports Pydantic and this
    module is deliberately importable without much; the alternative — a copy
    of fourteen vendor prefixes — is the duplicated *knowledge* the DRY rule
    is about, and it would go stale in exactly one direction.
    """
    from openstategraph.config_file import looks_like_a_secret

    return looks_like_a_secret(value)


# --------------------------------------------------------------------- #
# The definition
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class McpAuth:
    """How a server is authenticated — as a document may express it.

    `token_env` is the **name** of an environment variable. That is the whole
    reason this type exists rather than a `headers` dict: a dict would invite
    a value, and a value in a committed file is a leaked credential.
    """

    kind: str = AUTH_NONE
    #: `header` only. The vendor's own header name, e.g. `LANGSMITH-API-KEY` —
    #: real, and the reason bearer alone would not have been enough.
    header_name: str = ""
    token_env: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, "headerName": self.header_name, "tokenEnv": self.token_env}


@dataclass(frozen=True)
class McpServerDefinition:
    """One server, as project config declares it and a document names it."""

    name: str
    url: str
    transport: str = TRANSPORT_HTTP
    auth: McpAuth = field(default_factory=McpAuth)
    #: Where this entry came from, for the panel: `built-in` or `project`.
    origin: str = "built-in"
    #: `False` is a **tombstone**: a project entry that removes the server it
    #: names rather than defining one. It exists because the two defaults are
    #: not declared by any file, so "delete this row" has no line to delete —
    #: and a list whose first two rows are the only undeletable ones reads as
    #: a bug rather than as a policy. Never reaches a payload: the catalogue
    #: drops it, so nothing downstream can see a server that is not there.
    enabled: bool = True

    def as_payload(self) -> dict[str, Any]:
        """What the API hands the editor. Names and booleans, never a value."""
        return {
            "name": self.name,
            "url": self.url,
            "transport": self.transport,
            "auth": self.auth.as_payload(),
            "origin": self.origin,
            # Presence, not validity — the same distinction `/api/providers`
            # draws, and for the same reason: a set variable can still be
            # rejected, and only a call can tell you that.
            "credentialConfigured": bool(
                self.auth.kind == AUTH_NONE or os.getenv(self.auth.token_env, "").strip()
            ),
        }

    def connection(self, headers: Mapping[str, str]) -> dict[str, Any]:
        """The library's `Connection` TypedDict, as a plain dict."""
        connection: dict[str, Any] = {"url": self.url, "transport": self.transport}
        if headers:
            connection["headers"] = dict(headers)
        return connection


#: The two servers every project starts with — probed live, both keyless, both
#: streamable HTTP. There is **no separate LangGraph docs host**: LangGraph's
#: documentation lives inside `docs.langchain.com`, and the candidates were
#: probed and eliminated (research 01 §5). The honest pair is prose plus API
#: reference: one covers how, one covers exactly which symbol.
#:
#: Deliberately *not* a default: `api.smith.langchain.com/mcp`, which is real
#: and OAuth-authenticated. Shipping it would put a broken red server in every
#: new project.
DEFAULT_MCP_SERVERS: tuple[McpServerDefinition, ...] = (
    McpServerDefinition(name="LangChain docs", url="https://docs.langchain.com/mcp"),
    McpServerDefinition(
        name="LangChain API reference", url="https://reference.langchain.com/mcp"
    ),
)


def mcp_server_catalogue(
    configured: Iterable[McpServerDefinition] | None = None,
) -> dict[str, McpServerDefinition]:
    """The two defaults, with a project's own entries layered over by name.

    "Present unless overridden" rather than "present unless a project declares
    anything": a project that adds one server of its own has not asked to lose
    the documentation, and a default that vanishes the first time you use the
    feature is a default nobody can rely on.
    """
    catalogue = {server.name: server for server in DEFAULT_MCP_SERVERS}
    for server in configured or ():
        catalogue[server.name] = server
    # Layer first, then drop: a tombstone has to be able to remove a built-in
    # it is standing on top of, which is the only case it exists for.
    return {name: server for name, server in catalogue.items() if server.enabled}


# --------------------------------------------------------------------- #
# Auth — the only place a credential exists
# --------------------------------------------------------------------- #


def resolve_auth_headers(
    auth: McpAuth, *, server_name: str
) -> tuple[dict[str, str], str | None]:
    """`(headers, problem)`. Never raises, and never echoes the value.

    The problem sentence is written for a *developer reading a run's
    warnings*, so it names the variable and the fix. It never names the
    value — not even when the value is what is wrong, which is exactly the
    case a careless implementation would print.
    """
    if auth.kind == AUTH_NONE or not auth.kind:
        return {}, None

    name = auth.token_env.strip()
    if not name:
        return {}, (
            f'MCP server "{server_name}" is set to use {auth.kind} authentication but names '
            f"no environment variable to read the credential from. None of its tools are "
            f"available for this run."
        )
    # Two checks, because one is provably not enough: `ghp_aaaa…` is a legal
    # environment-variable name *and* a GitHub token, so the shape check
    # accepted it until a test tried it. The prefix list is the same one the
    # config loader refuses a committed file over.
    if not _ENV_NAME.match(name) or _looks_like_a_secret(name):
        return {}, (
            f'MCP server "{server_name}" needs the *name* of an environment variable holding '
            f"its credential, not the credential itself. Put the value in .env and name the "
            f"variable here — for example MY_MCP_TOKEN."
        )

    value = os.getenv(name, "").strip()
    if not value:
        return {}, (
            f'MCP server "{server_name}" needs the credential in {name}, which is not set in '
            f"this environment. None of its tools are available for this run."
        )

    if auth.kind == AUTH_BEARER:
        return {"Authorization": f"Bearer {value}"}, None
    if auth.kind == AUTH_HEADER:
        header = auth.header_name.strip()
        if not header:
            return {}, (
                f'MCP server "{server_name}" is set to use a custom header but does not say '
                f"which one. Name the header the vendor documents — LANGSMITH-API-KEY, for "
                f"example."
            )
        return {header: value}, None

    return {}, (
        f'MCP server "{server_name}" declares an authentication type this build does not '
        f"implement ({auth.kind!r}). None of its tools are available for this run."
    )


# --------------------------------------------------------------------- #
# Classification — the taxonomy, unwrapped
# --------------------------------------------------------------------- #


def flatten_causes(exc: BaseException) -> list[BaseException]:
    """Every exception inside an anyio `ExceptionGroup`, and its cause chain.

    Every MCP failure arrives as a bare
    `builtins.ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`
    from anyio's task group. Catching `Exception` and showing `str(e)` gives a
    developer nothing and collapses three distinct answers into one useless
    one, so the group is walked rather than printed.
    """
    if isinstance(exc, BaseExceptionGroup):
        return [cause for sub in exc.exceptions for cause in flatten_causes(sub)]
    causes = [exc]
    if exc.__cause__ is not None:
        causes.extend(flatten_causes(exc.__cause__))
    return causes


def classify_mcp_failure(exc: BaseException) -> tuple[str, str]:
    """`(status, message)` — the four panel answers, and only four.

    A **404 page and a plain HTML page give the identical 405**, because both
    are POST-to-a-GET-endpoint failures rather than MCP failures. So "wrong
    path" and "wrong host" are deliberately not distinguished: the wire does
    not carry that difference, and inventing it would produce a message that
    is confidently wrong half the time.

    Three of the four are facts about the server. The fourth,
    `STATUS_NOT_INSTALLED`, is a fact about **us**, and it is tested first —
    before `httpx` is even imported — because it is the only arm that can be
    true while no socket was ever opened. Without it a missing `[mcp]` extra
    fell to the terminal line below, whose own comment promises the transport
    succeeded, and both seeded defaults came back red in 16 ms blaming a
    server that was answering fine (mcp-connect ticket 05).
    """
    causes = flatten_causes(exc)
    if any(isinstance(cause, ImportError) for cause in causes):
        from openstategraph._extras import install_hint

        # No URL, no server name, no "answered": every word here is about a
        # thing the reader can type. `MissingProviderPackage` set the shape —
        # our gap, named with the exact line (install-experience 38).
        return (
            STATUS_NOT_INSTALLED,
            f"MCP support is not installed here — {install_hint('mcp')}.",
        )

    import httpx

    for cause in causes:
        if isinstance(cause, httpx.HTTPStatusError):
            code = cause.response.status_code
            if code in (401, 403):
                return STATUS_AUTH_REQUIRED, "The server answered, but rejected the credential."
            return STATUS_NOT_MCP, "Something answered, but it does not speak MCP."
        if isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout, OSError)):
            return STATUS_UNREACHABLE, "Nothing answered at that address."
        if isinstance(cause, (asyncio.TimeoutError, TimeoutError)):
            return (
                STATUS_UNREACHABLE,
                f"Nothing answered at that address within {int(MCP_TIMEOUT_SECONDS)} seconds.",
            )

    # The transport succeeded and the handshake did not: an McpError, a
    # protocol validation failure, anything after the socket opened.
    return STATUS_NOT_MCP, "Connected, but the MCP handshake failed."


# --------------------------------------------------------------------- #
# Validation — what the panel calls
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class McpValidation:
    """One handshake's verdict. `tools` is the answer a developer wants."""

    status: str
    message: str
    server_name: str = ""
    server_version: str = ""
    tools: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_LIVE

    def as_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "serverName": self.server_name,
            "serverVersion": self.server_version,
            "tools": list(self.tools),
            "elapsedSeconds": round(self.elapsed_seconds, 3),
        }


async def _handshake(connection: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    """`initialize` + `list_tools` on one session.

    `list_tools` is one extra round trip on an already-open session and is
    worth taking: it is the only thing that proves the server has a *tool
    surface*, which is what the atom will actually bind, and the names are the
    validation result a developer wants to see.
    """
    from langchain_mcp_adapters.sessions import create_session

    async with create_session(connection) as session:  # type: ignore[arg-type]
        info = await session.initialize()
        listed = await session.list_tools()
        server = getattr(info, "serverInfo", None)
        return (
            getattr(server, "name", "") or "",
            getattr(server, "version", "") or "",
            tuple(tool.name for tool in listed.tools),
        )


def validate_mcp_server(
    definition: McpServerDefinition, *, timeout: float = MCP_TIMEOUT_SECONDS
) -> McpValidation:
    """Live-check one server. Never raises; every outcome is a verdict.

    Measured against the public docs server on 0.3.2: 0.86 s for both round
    trips. Sub-second, which is why the panel takes both.
    """
    import time

    headers, problem = resolve_auth_headers(definition.auth, server_name=definition.name)
    if problem:
        return McpValidation(status=STATUS_AUTH_REQUIRED, message=problem)

    from openstategraph.mcp_sessions import run_on_mcp_loop

    started = time.monotonic()
    try:
        # A *fresh* session on purpose — a panel asking "is this reachable"
        # must open a socket rather than inherit a healthy pooled one. Only
        # the loop is shared, so probing does not tear down live sessions.
        name, version, tools = run_on_mcp_loop(
            asyncio.wait_for(_handshake(definition.connection(headers)), timeout)
        )
    except BaseException as exc:  # noqa: BLE001 — an ExceptionGroup is a BaseException
        status, message = classify_mcp_failure(exc)
        return McpValidation(
            status=status, message=message, elapsed_seconds=time.monotonic() - started
        )

    return McpValidation(
        status=STATUS_LIVE,
        message=(
            f"{name or 'The server'} answered with "
            f"{len(tools)} tool{'' if len(tools) == 1 else 's'}."
        ),
        server_name=name,
        server_version=version,
        tools=tools,
        elapsed_seconds=time.monotonic() - started,
    )


# --------------------------------------------------------------------- #
# Discovery — the one function in this module that opens a socket
# --------------------------------------------------------------------- #


async def _discover_tools(
    definition: McpServerDefinition, headers: Mapping[str, str], *, timeout: float
) -> list[Any]:
    """`get_tools()` for one server — a network call in the compile path.

    Named as its own module-level function for two reasons. It is the seam a
    unit test replaces, so no test in this repository needs a server; and it
    is the *one* place to look when asking what compiling a document can
    reach, which is a question worth being able to answer in one file.

    Measured: 1.08 s for one remote server on 0.3.2. A coroutine rather than a
    blocking call because a card carries N rows and `_discover_all` gathers
    over them, so N servers cost roughly one server's latency — and since the
    session it opens is pooled and kept, this is also the *only* time most
    runs pay a handshake at all.

    **One client per row, not one client holding every connection.** The
    library would gather for us if handed all the connections at once, and it
    would also collapse every failure into one `ExceptionGroup` with no way to
    say which server it came from. Attribution is the feature; the concurrency
    is available either way.
    """
    from langchain_mcp_adapters.tools import load_mcp_tools

    from openstategraph.mcp_sessions import session_proxy

    # A **session**, not a connection. `load_mcp_tools(connection=…)` builds
    # tools that re-handshake on every call — the defect this whole seam was
    # rewritten to remove. Handed a session, the adapters' tool body takes its
    # other arm and calls `session.call_tool` directly.
    #
    # The session is a pooled `McpSessionProxy`, so it is shared with every
    # other card naming this server and it reconnects itself; nothing here
    # captures a socket that can go stale.
    proxy = session_proxy(definition.connection(headers), timeout=timeout)
    return await asyncio.wait_for(
        load_mcp_tools(cast(Any, proxy), server_name=definition.name), timeout
    )


def _discover_all(
    jobs: Sequence[tuple[McpServerDefinition, Mapping[str, str]]], *, timeout: float
) -> list[Any]:
    """Every row's tools, or the exception that row raised, in row order.

    One `asyncio.run` for the whole card rather than one per row: the loop's
    lifetime is still exactly this call, which is what makes the shim honest,
    and `gather` is what turns three servers into one server's wait.

    `return_exceptions=True` is the isolation. Without it the first row to
    fail cancels the others, and a card with one dead server would bind
    nothing — the failure this ticket exists to prevent.
    """
    if not jobs:
        return []

    async def gather() -> list[Any]:
        # Bound rather than returned directly: `asyncio.gather`'s stub is
        # `Any`-shaped on 3.11 and precise on 3.13, so the direct return is a
        # `no-any-return` error on the floor version only — caught by the
        # matrix, invisible on this machine.
        results: list[Any] = await asyncio.gather(
            *(_discover_tools(definition, headers, timeout=timeout) for definition, headers in jobs),
            return_exceptions=True,
        )
        return results

    from openstategraph.mcp_sessions import run_on_mcp_loop

    # Not `asyncio.run`: sessions opened here have to outlive this call, and a
    # loop that is torn down at the end of discovery takes every one of them
    # with it. `gather` still turns three servers into one server's wait.
    return run_on_mcp_loop(gather())


#: The floor for a remote tool the sentence table has never met
#: (`launch-readiness/112`). It says the one true thing that needs no
#: internals: the work is not happening here.
_UNKNOWN_REMOTE_CALL = "Asking a connected service."


#: The one key a server declares its notes under, and the kinds it may name.
#:
#: `kind` is **required** here even though every member of the union defaults
#: it — that default exists so a tool author writing `Correction(text=…)` in
#: Python need not repeat themselves, and applying it to a stranger's JSON
#: would turn any object carrying a `text` field into a corrective addressed to
#: the model. Strict in trusting means the server names the kind.
_NOTES_KEY = "notes"
_NOTE_KINDS = frozenset({"next_step", "substitution", "source_choice"})


def _declared_notes(content: Any, artifact: Any) -> tuple[ToolNote, ...]:
    """The notes an MCP server declared about this call, believed or dropped.

    `launch-readiness/157`. `record_notes` is called from `BaseTool.run`, and
    nothing an MCP server offers passes through it — the tools arrive as
    `StructuredTool`s from `load_mcp_tools` and are re-wrapped here. So the
    recording seam moves to where the result is, and this is the half that
    decides *what there is to record*.

    **Nothing is inferred.** A server is a stranger's, so deriving a
    substitution from a payload shape would put one package's vocabulary into
    `core/` — and `mcp_resolve_lens`'s `entities[].value` looks exactly like a
    dozen fields that mean something else. A server **declares** its notes,
    under `notes`, in the same envelope it already returns.

    Tolerant in reading, strict in trusting (CLAUDE.md), and the strict half is
    the one that regresses:

    - the envelope is read from the text *and* from the structured content,
      because an MCP result carries both and a server may use either;
    - `notes` is read only where it is a **list** — a result set with a column
      called `notes`, or a `"notes": "no remarks"` field, is ordinary data and
      is left alone;
    - every entry must name a `kind` this build knows, and must then validate
      against that member of the union in full. A `Substitution` with no
      `how_matched` is refused rather than defaulted, which is the whole of
      `127`: a substitution that cannot say how it knew is exactly the record
      this must be unable to make.

    A payload this cannot parse costs nothing: no notes, and the result travels
    on untouched.
    """
    envelopes = [result_envelope(content)]
    if isinstance(artifact, Mapping):
        structured = artifact.get("structured_content")
        if isinstance(structured, Mapping):
            envelopes.append(dict(structured))

    found: list[ToolNote] = []
    for envelope in envelopes:
        if not isinstance(envelope, Mapping):
            continue
        declared = envelope.get(_NOTES_KEY)
        if not isinstance(declared, list):
            continue
        for entry in declared:
            note = _believable(entry)
            if note is not None:
                found.append(note)
    return tuple(found)


def _believable(entry: Any) -> ToolNote | None:
    """One declared entry, validated against the union, or `None`.

    Failure is silent by design. A server that ships a malformed note has said
    nothing this build can act on, and raising here would turn a disclosure
    somebody added as a courtesy into a dead tool call.
    """
    from pydantic import TypeAdapter, ValidationError

    if not isinstance(entry, Mapping):
        return None
    if entry.get("kind") not in _NOTE_KINDS:
        return None
    try:
        return cast(ToolNote, TypeAdapter(ToolNote).validate_python(dict(entry)))
    except ValidationError:
        return None


def _with_declared_notes(result: Any) -> Any:
    """Record this call's notes on the run, and append the model's half.

    The two rails `abc/tool_notes` describes, reached from a tool that is
    legitimately not a `BaseTool`. `record_notes` puts the reader's half on the
    run for `compile/node_runtime._output` to render; `notes_for_model` rides
    back with the result, in the same message, which is the whole of `117`.

    Byte-for-byte the previous behaviour when a server declares nothing —
    which is every server today — right down to the tuple the agent receives.
    """
    if not isinstance(result, tuple) or len(result) != 2:
        # `response_format` is carried across from the discovered tool, so a
        # server answering in the plain `"content"` shape is a real case. It
        # carries no artifact and no structured content; read what there is.
        content, artifact = result, None
    else:
        content, artifact = result

    notes = _declared_notes(content, artifact)
    if not notes:
        return result

    record_notes(notes)
    addendum = notes_for_model(notes)
    if addendum:
        content = _append_text(content, addendum)
    return (content, artifact) if isinstance(result, tuple) else content


def _append_text(content: Any, addendum: str) -> Any:
    """The addendum, in whichever shape this content already is.

    A string for the plain case, one more text block for the content-block
    list an MCP tool actually produces. Anything else is returned untouched
    rather than stringified — handing a model its own artifact as text is the
    defect `response_format` is carried across to prevent.
    """
    if isinstance(content, str):
        return f"{content}\n\n{addendum}"
    if isinstance(content, list) and all(
        isinstance(block, dict) and block.get("type") == "text" for block in content
    ):
        return [*content, {"type": "text", "text": addendum}]
    return content


#: Where the argument-shape hint is parked on the exception on its way past.
#:
#: An attribute rather than a rebuilt exception: `_MCPToolExecutionError` is
#: private to `langchain_mcp_adapters`, and its own docstring says its message
#: is a snapshot of `tool_content` taken at construction — so reconstructing it
#: or mutating that list is how the two fall out of step. The hint is composed
#: where the arguments are (the shim) and read where the content is composed
#: (`_error_content`), and nothing in between has to know about it.
_HINT_ATTR = "_openstategraph_argument_hint"

#: What a service's own words look like when the refusal really *was* about
#: credentials. Read rather than assumed, because `156` is the case where
#: asserting the negative sent the owner to check a token that was fine — and
#: asserting it the other way would be the same defect pointing the other way.
_AUTHORISATION_MARKERS = (
    "401",
    "403",
    "unauthor",
    "authenticat",
    "authoriz",
    "authoris",
    "forbidden",
    "credential",
    "access denied",
    "permission denied",
    "api key",
)


def _looks_like_authorisation(detail: str) -> bool:
    lowered = detail.casefold()
    return any(marker in lowered for marker in _AUTHORISATION_MARKERS)


def _argument_shape_hint(schema: Any, sent: Mapping[str, Any]) -> str | None:
    """The shape this tool actually wants, when its own schema says so.

    `156`'s live case in one sentence: `mcp_resolve_lens` and `mcp_prepare`
    declare `{"properties": {"inp": {"$ref": …}}, "required": ["inp"]}`, the
    model sent `{"question": …}` — the obvious move for a field named
    `document` — and the server refused. The agent then guessed
    `departure_port`, `departure_date` and `loading_port` for three turns
    against a table whose columns are `load_port` and `load_date`, because the
    two tools that would have told it were the two it could not call.

    **The schema is ours to read and was already in hand at bind time.** It is
    also honest — `158` carries that correction: the nested form works, the
    schema reaches the model intact, and a weaker model flattened the `$ref`.
    Since `158` the forced case is *adapted* rather than reported, so what
    reaches here is a refusal no schema could forecast — and saying which shape
    the tool wanted is still the most useful thing to say about it.

    Strict in trusting, and narrowly so: a hint is offered only where the
    schema declares **exactly one** required property, that property is an
    object, and the caller sent something other than it. Every other failure
    gets the service's own message and nothing invented on top — a hint
    produced because a call failed would be this map's own defect wearing a
    helpful face.
    """
    if not isinstance(schema, Mapping):
        return None
    required = schema.get("required")
    if not isinstance(required, list) or len(required) != 1:
        return None
    wrapper = required[0]
    if not isinstance(wrapper, str) or wrapper in sent:
        return None
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return None
    declared = properties.get(wrapper)
    if not isinstance(declared, Mapping):
        return None
    if "$ref" not in declared and declared.get("type") != "object":
        return None
    flat = ", ".join(sorted(str(key) for key in sent)) or "no arguments"
    return (
        f'Argument shape: this tool takes a single object nested under "{wrapper}". '
        f"You sent {flat} at the top level. Retry with "
        f'{{"{wrapper}": {{ … the fields you just sent … }}}}.'
    )


def _object_schema(schema: Mapping[str, Any], declared: Any) -> Mapping[str, Any] | None:
    """One property's own schema, resolved through a local `$ref`, if it is an object.

    Only `#/$defs/…` and `#/definitions/…` inside this same document. A remote
    or non-local reference is something this build cannot read, and a shape it
    cannot read is a shape it must not rewrite a call into.
    """
    if not isinstance(declared, Mapping):
        return None
    reference = declared.get("$ref")
    if isinstance(reference, str):
        for prefix, key in (("#/$defs/", "$defs"), ("#/definitions/", "definitions")):
            if reference.startswith(prefix):
                pool = schema.get(key)
                target = pool.get(reference[len(prefix) :]) if isinstance(pool, Mapping) else None
                return target if isinstance(target, Mapping) else None
        return None
    if declared.get("type") == "object" or isinstance(declared.get("properties"), Mapping):
        return declared
    return None


def _adapted_arguments(schema: Any, sent: Mapping[str, Any]) -> dict[str, Any] | None:
    """The one legal wrapping of a flattened call, or `None`.

    `launch-readiness/158`, and the correction that produced it. `156` was
    filed believing `mcp_resolve_lens` was *uncallable* because its schema
    nests its arguments under `inp`. It is not: the nested form answers
    `ok: true`, the schema reaches the model intact through
    `langchain-mcp-adapters`, and other clients call it without trouble.
    **`gpt-4o-mini` flattened the `$ref`.** Nothing is wrong with that service.

    That is still ours, because *"it doesn't matter which model — the app
    should work"*. `156` makes the refusal readable so a model can retry; this
    removes the dependency on the retry being right, which is the same move
    CLAUDE.md's own worked example asks for (`every-workflow-green/13`: an
    argument typed `str`, an agent sending the object its name invited, and a
    run that died re-appending it).

    **The strict half is the whole risk**, because tolerance here rewrites what
    the model asked for. So nothing is adapted unless the schema *forces* the
    wrapping, which is all four of:

    - exactly one required top-level property;
    - that property is an object, inline or through a local `$ref`;
    - every key sent is one of that object's own properties;
    - nothing sent matches a top-level property name.

    Where a second wrapping is legal, or a flat call is itself a legal
    top-level call missing its wrapper, nothing happens and `156`'s readable
    refusal stands — an adapter that rewrites a wrong call into a *different*
    wrong call is worse than the failure it replaced. An unknown field is
    therefore never smuggled inside the wrapper: the model's mistake was the
    field name, and it has to read that back.

    Deliberately one-directional. Unwrapping a nested call for a flat schema is
    not done, because no case has been seen, and every widening here needs the
    test that proves ordinary calls are untouched.
    """
    if not isinstance(schema, Mapping) or not sent:
        return None
    required = schema.get("required")
    if not isinstance(required, list) or len(required) != 1:
        return None
    wrapper = required[0]
    if not isinstance(wrapper, str) or wrapper in sent:
        return None
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return None
    if any(key in properties for key in sent):
        return None
    inner = _object_schema(schema, properties.get(wrapper))
    if inner is None:
        return None
    fields = inner.get("properties")
    if not isinstance(fields, Mapping):
        return None
    if any(key not in fields for key in sent):
        return None
    return {wrapper: dict(sent)}


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


#: The hint's own block opens with a blank line, because a provider that
#: concatenates content blocks bare does exist — the live 2026-08-28 re-run
#: read `…/v/missingArgument shape: this tool takes…`, one word running into
#: the next. A block boundary is not a line break anywhere it matters.
_HINT_LEAD = "\n\n"


def _error_content(error: Any) -> Any:
    """`handle_tool_error`: a refusal the model can read and act on.

    **This is the whole of `156`, and it is a restoration rather than an
    invention.** `convert_mcp_tool_to_langchain_tool` already sets
    `handle_tool_error=_handle_mcp_tool_error` on the tool it builds, so a
    bare MCP client hands an `isError=True` result to the model as a
    `ToolMessage` with `status="error"`. `_wrap_async_tool` rebuilt the
    `StructuredTool` from six fields and did not carry that one across — so a
    `ToolException` raised out of the shim, was caught nowhere in
    `openstategraph/`, and `agent1` died on an argument mistake it could
    trivially have corrected. **We were strictly worse than no wrapper.**

    The library's boundary is kept exactly where the library puts it: only a
    `ToolException` reaches here at all, so a transport or session failure
    still propagates. That parity is deliberate in both directions — a refused
    call is something a model can fix, and a dead session is not, and hiding
    the second behind a model's prose would be `156` again with a different
    cause.
    """
    content = getattr(error, "tool_content", None)
    hint = getattr(error, _HINT_ATTR, "")
    if isinstance(content, list) and content:
        blocks = list(content)
        return [*blocks, _text_block(_HINT_LEAD + hint)] if hint else blocks
    body = str(error) or "The service refused this call and returned no message."
    return [_text_block(body)] + ([_text_block(_HINT_LEAD + hint)] if hint else [])


def _record_the_refusal(name: str, error: Any, schema: Any, sent: Mapping[str, Any]) -> None:
    """Park the hint on the exception, and put the refusal on the run.

    Tolerant is not silent. The model is about to be handed the service's own
    message and may well correct itself — but *may well* is precisely what
    `127` established cannot be the disclosure, and here the model did worse
    than forget: it invented a cause specific enough to send the owner
    checking credentials that were never wrong. So the run records the
    rejection, and `compile/node_runtime._output` renders it whatever the
    answer above says.
    """
    hint = _argument_shape_hint(schema, sent)
    if hint:
        setattr(error, _HINT_ATTR, hint)
    detail = str(error)
    record_notes(
        (
            ToolFailure(
                tool=name,
                detail=detail,
                looked_like_authorisation=_looks_like_authorisation(detail),
            ),
        )
    )


def _wrap_async_tool(tool: Any, server: str) -> Any:  # noqa: ARG001 — see below
    """The sync shim: the original `coroutine`, plus a `func` that runs it.

    `response_format` is carried across deliberately. Every MCP tool arrives
    as `content_and_artifact`, so the coroutine returns a `(content,
    artifact)` tuple — a wrapper defaulting to `"content"` would stringify
    that tuple and hand the model its own artifact as text.

    **It is also the one place an MCP call can say it has started**
    (production-ready 50). This module's own header measures a call at
    1.2–1.5 s of which ≈0.8 s is reconnection, and that is a floor, not a
    typical case — a server paging an API spends as long as it likes. `update`
    fires when the *node* finishes and `token` only while a model types, so
    without this line the gap is genuinely unreported.

    **Both entry points, not just the shim.** `StructuredTool` carries a
    `func` and a `coroutine` and the caller picks; instrumenting only the
    sync one would make the feature disappear under an async agent, which is
    the runtime most likely to be doing several of these at once.

    **What it says changed** (`launch-readiness/112`). It used to say
    `"Calling mcp_list_lenses on http://localhost:8080/mcp/"`, composed once
    per tool, and that line is the ticket's own title: it reports *that*
    something is happening and names two internals — a tool id and a server
    address — to a panel a customer can be looking at. Both `abc/narration.py`
    ("a tool is never named aloud") and CLAUDE.md ("free of internals") forbid
    it; the earlier decision to name both halves predates the sentence table
    that makes a better line possible.

    It now asks `describe_tool_call` what this call *is doing*, per call,
    because the answer can depend on the arguments. Two consequences worth
    knowing:

    - It is the **same** sentence `NarrationMiddleware` composes for the same
      call, out of the same table — deliberately, so a reader never meets two
      vocabularies for one action. Until `launch-readiness/145` both were
      *emitted* and the duplicate was hidden by every surface collapsing a
      repeat, which is a plaster over a line nobody should have authored
      twice. The wrapper now marks itself `NARRATES_ITSELF` in `metadata` and
      the middleware stands down for the before-line; the finding after the
      call is still the middleware's, because that is the only place holding
      the result.
    - A tool the table has never met falls back to a line that still names
      nothing. `server` is dropped rather than softened: there is no phrasing
      of a URL that is not an internal. The parameter is **kept** rather than
      removed — it is what a future developer-channel line would be composed
      from (`developer_channel.py` is the seam that already separates the two
      audiences), and deleting it would make restoring that a signature
      change at the one call site.
    """
    from langchain_core.tools import StructuredTool, ToolException

    from openstategraph.mcp_sessions import run_on_mcp_loop, run_on_mcp_loop_async

    inner = tool.coroutine
    name = getattr(tool, "name", "") or ""
    # The tool's own declaration of the arguments it wants, held here so the
    # shim can say which shape a refused call should have had (`156`).
    schema = getattr(tool, "args_schema", None)

    def _line(kwargs: dict[str, Any]) -> str:
        return describe_tool_call(name, kwargs) or _UNKNOWN_REMOTE_CALL

    async def _coroutine(**kwargs: Any) -> Any:
        report_progress(_line(kwargs))
        # The session belongs to the MCP loop, and anyio streams cannot be
        # awaited from a foreign one. `run_on_mcp_loop_async` suspends this
        # loop on an ordinary future while the work happens over there — no
        # thread is blocked, which is what makes an async agent running four
        # of these at once still concurrent.
        kwargs = _adapted_arguments(schema, kwargs) or kwargs
        try:
            answer = await run_on_mcp_loop_async(inner(**kwargs))
        except ToolException as refused:
            _record_the_refusal(name, refused, schema, kwargs)
            raise
        return _with_declared_notes(answer)

    def _call(**kwargs: Any) -> Any:
        report_progress(_line(kwargs))
        # Not `asyncio.run`: that opened a loop per call, and a loop per call
        # is a session per call, which is the handshake this seam removes.
        kwargs = _adapted_arguments(schema, kwargs) or kwargs
        try:
            answer = run_on_mcp_loop(inner(**kwargs))
        except ToolException as refused:
            _record_the_refusal(name, refused, schema, kwargs)
            raise
        return _with_declared_notes(answer)

    return StructuredTool(
        name=tool.name,
        description=getattr(tool, "description", "") or "",
        args_schema=tool.args_schema,
        func=_call,
        coroutine=_coroutine,
        response_format=getattr(tool, "response_format", "content"),
        # `launch-readiness/156`. Carried across rather than defaulted away:
        # the tool this re-wraps already had one, and dropping it is what
        # turned a self-describing refusal into a dead run.
        handle_tool_error=_error_content,
        # `launch-readiness/145`: the declaration that stops the same sentence
        # being said twice. `NarrationMiddleware` narrates every tool call it
        # wraps, and for an MCP tool that is the *identical* line out of the
        # *identical* table — a duplicate that was invisible only because every
        # surface collapsed a repeat. The line here is kept rather than the
        # middleware's because it is the one that survives where the middleware
        # is absent (a subagent's stack is assembled by `create_deep_agent`),
        # and the middleware stands down for the before-line when it sees this.
        metadata={**(getattr(tool, "metadata", None) or {}), NARRATES_ITSELF: True},
    )


# --------------------------------------------------------------------- #
# The atom
# --------------------------------------------------------------------- #


def _tool_filter(value: Any) -> list[str]:
    """One row's tool filter, as names — typed on a line, or a list of rows.

    Two containers, one meaning. A server row has no room for a sub-table, so
    the card's row spells its filter as one comma-separated line; a document
    written before ticket 04 (and the app-level panel's own field set) spells
    it as `[{"name": …}]`. Both are read here rather than migrated, because a
    reader who opens an old workflow must not have it rewritten under them.

    Blank entries are not a filter either way. Somebody pressing *Add tool* and
    then changing their mind must not silently bind nothing.
    """
    if isinstance(value, str):
        return [name.strip() for name in re.split(r"[,\n]", value) if name.strip()]
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for row in value:
        if isinstance(row, Mapping):
            name = str(row.get("name", "")).strip()
        else:
            name = str(row).strip()
        if name:
            names.append(name)
    return names


def _names_a_server(row: Mapping[str, Any]) -> bool:
    """Whether this row points at anything at all."""
    return any(str(row.get(key, "")).strip() for key in (KEY_SERVER, KEY_URL))


def workflows_naming_mcp_server(server_name: str) -> list[str]:
    """Slugs of saved packages with a `tool.mcp` row naming this server.

    The indirection a card relies on — a node NAMES a server, the project
    config defines it — is what makes a copied package carry no URL of yours,
    and it is also why deleting a server can break a document nobody has open
    (mcp-connect ticket 06). Nothing warned about that, so this is the read
    that lets a confirm name the documents.

    Reads `workflow.json` and nothing else: no compile, no import of a node
    runtime, no model. A package that cannot be parsed is skipped rather than
    raising — this answers a confirmation dialog, and rubble on disk is a
    different problem with its own report.
    """
    import json

    from openstategraph.workflows_root import workflows_root

    wanted = server_name.strip()
    if not wanted:
        return []

    found: list[str] = []
    root = workflows_root()
    if not root.is_dir():
        return []

    for directory in sorted(root.iterdir()):
        document = directory / "workflow.json"
        if not document.is_file():
            continue
        try:
            envelope = json.loads(document.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        nodes = envelope.get("document", envelope)
        nodes = nodes.get("nodes", []) if isinstance(nodes, Mapping) else []
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, Mapping) or node.get("type") != "tool.mcp":
                continue
            data = node.get("data")
            if not isinstance(data, Mapping):
                continue
            if any(
                str(row.get(KEY_SERVER, "")).strip() == wanted for row in _server_rows(data)
            ):
                found.append(directory.name)
                break
    return found


def _server_rows(data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """A node's server rows — or its flat fields, read as the one row they were.

    The fallback is compatibility, not migration: nothing is rewritten, so
    opening a workflow saved before the card went plural neither changes the
    file nor loses its server.

    It is reached when **no row names anything**, rather than when the row list
    is absent, and that is the case that actually occurs: a new card seeds one
    empty row, so an old document opened in a new editor carries an empty row
    list *and* its flat fields, and a fallback keyed on absence would silently
    bind nothing. A card with even one filled row is a card that has been
    edited, and its rows are the whole truth.
    """
    listed = data.get(KEY_SERVERS)
    rows = [row for row in listed if isinstance(row, Mapping)] if isinstance(listed, list) else []
    if any(_names_a_server(row) for row in rows):
        return rows
    return [data] if _names_a_server(data) else []


@dataclass(frozen=True)
class McpBinding:
    """One row of the card: a server, its filter, and what is wrong with it.

    `problem` is set at configure time — a name nothing registers, a row with
    nothing in it — and it is per row rather than per node, which is the whole
    of ticket 04 in one field: a card with a bad row still has good ones.
    """

    #: Zero-based position on the card. Warnings quote it one-based, because
    #: the developer counting rows is counting from one.
    index: int
    definition: McpServerDefinition | None = None
    selected: tuple[str, ...] = ()
    problem: str | None = None


class McpTool(BaseTool):
    """One card, N servers' tools — each row filtered, if you like.

    **One node is a server list, not one tool.** The alternative was considered
    and rejected in research: a thirty-tool server would be thirty cards, and a
    row's filter does the same job in one line. Ticket 04 then took the node
    from one server to a list, because three services an agent chooses between
    per task share a consumer, and sharing a consumer is exactly when rows cost
    nothing.

    The singular seam refuses rather than guessing — see `as_langchain_tool`.
    """

    name = "mcp_server"
    description = (
        "Binds every tool an MCP server offers onto this agent. Configured on the canvas, "
        "not called directly."
    )
    node_type = "tool.mcp"
    #: **Deliberately not declared read-only, and it never can be**
    #: (`launch-readiness` 121). One card is a whole MCP server, whose
    #: tools are a stranger's and are discovered at bind time — a filesystem
    #: writer and a search index look identical from here. This is the case
    #: that decides the default: guessing 'read-only' about somebody else's
    #: server is the silent, unsafe direction.
    side_effecting = True
    Args = NoArgs

    def __init__(
        self,
        bindings: Sequence[McpBinding] = (),
        *,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        self.bindings = tuple(bindings)
        self._data = dict(data or {})

    # -- configuration -------------------------------------------------- #

    def configure(self, data: dict[str, Any]) -> "McpTool":
        """One node's server rows, each resolved into a server definition.

        A fresh instance, never a mutation of the shared registry one: two
        `tool.mcp` nodes pointing at two sets of servers in one document is the
        expected case, not the exotic one.
        """
        catalogue: dict[str, McpServerDefinition] | None = None
        bindings: list[McpBinding] = []

        for index, row in enumerate(_server_rows(data)):
            server_name = str(row.get(KEY_SERVER, "")).strip()
            url = str(row.get(KEY_URL, "")).strip()
            selected = tuple(_tool_filter(row.get(KEY_TOOLS)))

            if server_name:
                # Read once per node rather than once per row: the project's
                # config is one file, and three rows naming three registered
                # servers must not be three reads of it.
                if catalogue is None:
                    catalogue = mcp_server_catalogue(_configured_servers())
                registered = catalogue.get(server_name)
                bindings.append(
                    McpBinding(index, registered, selected)
                    if registered is not None
                    else McpBinding(
                        index,
                        selected=selected,
                        problem=(
                            f'No MCP server named "{server_name}" is registered in this '
                            f"project, and this row configures none of its own. Add it to "
                            f"openstategraph.yaml under mcp_servers, or fill in the server's "
                            f"URL on the card."
                        ),
                    )
                )
                continue

            if not url:
                bindings.append(
                    McpBinding(
                        index,
                        selected=selected,
                        problem=(
                            "This row names no registered server and carries no URL, so there "
                            "is nothing for it to connect to. Pick a server or type its URL."
                        ),
                    )
                )
                continue

            transport = str(row.get(KEY_TRANSPORT, "")).strip()
            bindings.append(
                McpBinding(
                    index,
                    McpServerDefinition(
                        # An inline server has no registered name; the URL is
                        # the only honest identity it has, and every warning
                        # below names it.
                        name=url,
                        url=url,
                        # A transport this build does not implement (websocket,
                        # stdio) falls back rather than failing: the document
                        # may have been written by a newer editor, and HTTP is
                        # the only one of the four that both carries a
                        # credential and needs no subprocess.
                        transport=transport if transport in TRANSPORTS else TRANSPORT_HTTP,
                        auth=McpAuth(
                            kind=str(row.get(KEY_AUTH_KIND, AUTH_NONE)).strip() or AUTH_NONE,
                            header_name=str(row.get(KEY_AUTH_HEADER_NAME, "")).strip(),
                            token_env=str(row.get(KEY_AUTH_TOKEN_ENV, "")).strip(),
                        ),
                        origin="inline",
                    ),
                    selected,
                )
            )

        return McpTool(bindings, data=data)

    def document_state(self) -> dict[str, Any]:
        """Everything this node would serialise. Exists to be tested.

        The map's rule is that `workflow.json` stays shareable — a document
        may name a server, never a credential. A rule with no test is a
        wish, so `test_prebuilt_mcp.py` sets a variable to a recognisable
        secret and asserts it appears nowhere in here.
        """
        return dict(self._data)

    # -- the seam ------------------------------------------------------- #

    def _row_prefix(self, binding: McpBinding) -> str:
        """Which row a sentence is about — and nothing at all when there is one.

        A card with a single server says "Row 1 of 1" to no one's benefit, and
        every sentence in this module was written to read without it.
        """
        total = len(self.bindings)
        return f"Row {binding.index + 1} of {total} — " if total > 1 else ""

    def as_langchain_tools(self, warnings: list[str] | None = None) -> list[Any]:
        """Every tool every healthy row offers, filtered, wrapped, never raising.

        A network call in the compile path is what this is, and nothing else
        here is one. So the rule that makes it acceptable is enforced at every
        exit: **a failure contributes a warning and zero tools** — for that
        row. The agent runs without the capability, loudly, instead of the
        compile dying for a server that happened to be down, and instead of
        two healthy servers dying with it.
        """

        def warn(message: str, binding: McpBinding | None = None) -> None:
            sentence = f"{self._row_prefix(binding)}{message}" if binding else message
            if warnings is not None:
                warnings.append(sentence)
            else:  # a caller that wants none still gets the log line
                logger.warning(sentence)

        if not self.bindings:
            warn(
                "An MCP server node has no servers on it, so it contributes no tools. Add a "
                "row naming a registered server, or one carrying a URL."
            )
            return []

        # Two passes: everything resolvable without a socket first, so a row
        # that cannot be reached at all never enters the gather and its
        # warning still comes out in row order.
        jobs: list[tuple[McpBinding, McpServerDefinition, dict[str, str]]] = []
        for binding in self.bindings:
            if binding.problem:
                warn(binding.problem, binding)
                continue
            definition = binding.definition
            if definition is None:  # pragma: no cover — `problem` is always set with it
                warn("This row resolved to no server at all.", binding)
                continue
            headers, problem = resolve_auth_headers(definition.auth, server_name=definition.name)
            if problem:
                warn(problem, binding)
                continue
            jobs.append((binding, definition, headers))

        outcomes = _discover_all([(job[1], job[2]) for job in jobs], timeout=MCP_TIMEOUT_SECONDS)

        bound: list[Any] = []
        claimed: dict[str, McpBinding] = {}
        for (binding, definition, _headers), outcome in zip(jobs, outcomes):
            if isinstance(outcome, BaseException):
                status, _panel_message = classify_mcp_failure(outcome)
                warn(_bind_sentence(status, definition), binding)
                continue
            for tool in self._chosen(binding, definition, outcome, warn):
                first = claimed.get(tool.name)
                if first is not None:
                    # One card is one namespace: `ToolNode` keys tools by name,
                    # so binding both would shadow the first silently and the
                    # agent would call a server nobody chose.
                    warn(
                        f'Two servers on this node offer a tool named "{tool.name}". The '
                        f"agent gets the one from row {first.index + 1}; filter one of the "
                        f"two rows, or split them across two nodes.",
                        binding,
                    )
                    continue
                claimed[tool.name] = binding
                bound.append(_wrap_async_tool(tool, definition.name))
        return bound

    def _chosen(
        self,
        binding: McpBinding,
        definition: McpServerDefinition,
        discovered: list[Any],
        warn: Any,
    ) -> list[Any]:
        """One row's filter applied to what its server answered with."""
        if not binding.selected:
            # G7: an absent filter means "all, now and later". Storing the
            # resolved list would silently freeze the server's surface.
            return list(discovered)

        available = {tool.name: tool for tool in discovered}
        chosen = [tool for tool in discovered if tool.name in set(binding.selected)]
        missing = [name for name in binding.selected if name not in available]
        if missing:
            # The failure that would otherwise be reported as success: a
            # filter naming three tools where the server offers two binds two
            # and looks entirely healthy.
            named = ", ".join(sorted(missing))
            warn(
                f'MCP server "{definition.name}" has no tool named {named}. '
                f"Bound {len(chosen)} of the {len(binding.selected)} tools this row asks for.",
                binding,
            )
        return chosen

    def as_langchain_tool(self, on_call: Callable[[str], None] | None = None) -> Any:
        """Refuses, and names the plural seam.

        "Which one of my server's tools am I?" has no true answer, and this
        repository's settled response to a question with no true answer is an
        honest refusal rather than a plausible-looking first element. The
        canvas never takes this path — `NodeRuntime._bind_tools` calls
        `as_langchain_tools` — so the refusal is a guard on the *other*
        callers, not a behaviour anyone should meet.

        **`on_call` is passed straight through, and the override exists only
        for this docstring.** It was written before the hook did and was never
        taught about it, so it dropped the parameter — which made this class
        unsubstitutable for its base (`organisms-first-class` 48) and cost the
        knowledge explorer a `TypeError` on any document carrying an MCP node,
        `tool.mcp` not being on `EXPLORER_DENY_PREFIXES`. A refusal that runs
        is still a run, so the hook fires: the caller asked which tools were
        used, and this one was.
        """
        return super().as_langchain_tool(on_call)

    def _execute(self, args: Any) -> ToolResult:
        return ToolResult.failure(
            "An MCP server node contributes its server's tools to an agent; it is not itself "
            "one of them. Bind it through as_langchain_tools()."
        )


def _bind_sentence(status: str, definition: McpServerDefinition) -> str:
    """The model-facing half of the taxonomy, one sentence per condition.

    Separate from `classify_mcp_failure`'s message, which is written for the
    *panel* — "Nothing answered at that address" is the right thing to put
    under a URL box and the wrong thing to put in a run's warnings, where
    nobody can see which URL box it was about.
    """
    if status == STATUS_NOT_INSTALLED:
        from openstategraph._extras import install_hint

        # Deliberately the same fix in both surfaces. A run that degraded with
        # "could not be reached" sent a developer to check a server that was
        # never contacted.
        return (
            f"MCP support is not installed, so no tools from any MCP server are available "
            f"for this run — {install_hint('mcp')}."
        )
    if status == STATUS_AUTH_REQUIRED:
        return (
            f'MCP server "{definition.name}" rejected the credential in '
            f"{definition.auth.token_env or 'its configured variable'}. None of its tools are "
            f"available for this run."
        )
    if status == STATUS_NOT_MCP:
        if _is_nameless(definition):
            return (
                f"{definition.url} answered, but it does not speak MCP. Check the URL and "
                f"the transport."
            )
        return (
            f"{definition.url} answered, but it does not speak MCP. Check the URL and the "
            f'transport for server "{definition.name}".'
        )
    if _is_nameless(definition):
        return (
            f"MCP server {definition.url} could not be reached. None of its tools are "
            f"available for this run."
        )
    return (
        f'MCP server "{definition.name}" could not be reached at {definition.url}. None of '
        f"its tools are available for this run."
    )


def _is_nameless(definition: McpServerDefinition) -> bool:
    """Whether this row's "name" is only its address wearing a name's clothes.

    An inline row has no registered name, so `McpTool.configure` fills the slot
    with the URL — the only honest identity it has. Every sentence that names
    both then printed one string twice:

        MCP server "https://…/mcp" could not be reached at https://…/mcp.

    Read as a *reader* rather than as an author, that sentence says the product
    has confused two servers — which is the worst possible doubt to plant in
    the one message whose entire job is to be believed about a degradation.

    The test is the equality, not `origin == "inline"`. `origin` says where the
    row came from; this asks whether the two slots hold the same string, which
    is the thing the sentence actually cares about and stays true if some other
    path ever fills a name from a URL.
    """
    return definition.name.strip() == definition.url.strip()


def _configured_servers() -> list[McpServerDefinition]:
    """A project's own `mcp_servers:`, or nothing.

    Read through `config_file.active_config()` rather than passed in, because
    a tool is configured from a node's `data` and a server registry is a
    property of the *project* — the same precedence chain every other
    project-level setting already uses.
    """
    try:
        from openstategraph.config_file import active_config, config_mcp_servers

        return config_mcp_servers(active_config())
    except Exception:  # pragma: no cover — a broken config must not lose the defaults
        logger.debug("Project MCP servers unavailable; using built-in defaults", exc_info=True)
        return []


#: The family, in the shape `registries.py` layers.
MCP_TOOLS: tuple[BaseTool, ...] = (McpTool(),)


__all__ = [
    "AUTH_BEARER",
    "AUTH_HEADER",
    "AUTH_KINDS",
    "AUTH_NONE",
    "DEFAULT_MCP_SERVERS",
    "MCP_NODE_KEYS",
    "MCP_ROW_KEYS",
    "MCP_STATUSES",
    "MCP_TIMEOUT_SECONDS",
    "MCP_TOOLS",
    "STATUS_AUTH_REQUIRED",
    "STATUS_LIVE",
    "STATUS_NOT_INSTALLED",
    "STATUS_NOT_MCP",
    "STATUS_UNREACHABLE",
    "TRANSPORTS",
    "TRANSPORT_HTTP",
    "TRANSPORT_SSE",
    "McpAuth",
    "McpBinding",
    "McpServerDefinition",
    "McpTool",
    "McpValidation",
    "classify_mcp_failure",
    "flatten_causes",
    "mcp_server_catalogue",
    "resolve_auth_headers",
    "validate_mcp_server",
]
