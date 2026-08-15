"""`tool.mcp` — one card, a whole MCP server's tools.

Every other atom in this repository is one node → one tool, and every one of
them is a synchronous `func`. An MCP server is one node → **N** tools, and
those tools are `coroutine`-only. Both of those are structural, so both are
answered structurally rather than worked around:

- **Plural.** `BaseTool.as_langchain_tools()` is declared once on the base and
  defaults to `[self.as_langchain_tool()]`, so every existing atom is
  unchanged and the singular case is simply the plural case with one element.
- **Sync.** Each async tool is re-wrapped as a `StructuredTool` carrying the
  original `coroutine` *and* a `func` that runs it with `asyncio.run`.

`asyncio.run` here is legal for a checkable reason rather than by luck: the
graph is driven by `graph.invoke()`/`graph.stream()` on a worker thread where
**no event loop is running** (`api/streaming.py` says so outright — the
threadpool exists *because* the stream blocks), so there is no loop to nest
inside. And it is not the hidden-loop antipattern, because
`MultiServerMCPClient` is stateless by default: `call_tool` opens a fresh
`ClientSession` per call under `async with`. Loop lifetime *is* session
lifetime *is* one tool call. Nothing outlives the call, so there is nothing to
shut down and nothing to leak.

The honest cost, measured on `langchain-mcp-adapters` 0.3.2 against the live
docs server: a call is 1.2–1.5 s, of which ≈0.8 s is reconnection. Roughly
half of every MCP tool call is the handshake. That number is on the card,
because a cost nobody can see gets blamed on the model.

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
from typing import Any, Iterable, Mapping, Sequence

from openstategraph.abc.tool import BaseTool, NoArgs, ToolResult

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- #
# Data keys. Module-level literals so the extractor in
# `test_data_key_contract.py` can see them, and so the TypeScript field
# schema has something stable to be compared against.
# --------------------------------------------------------------------- #

KEY_SERVER = "server"
KEY_URL = "url"
KEY_TRANSPORT = "transport"
KEY_AUTH_KIND = "authKind"
KEY_AUTH_HEADER_NAME = "authHeaderName"
KEY_AUTH_TOKEN_ENV = "authTokenEnv"
KEY_TOOLS = "tools"
KEY_NOTE = "mcpNote"

#: Every key `configure()` reads, plus the read-only note the card renders.
#: Compared against the TypeScript declaration by `test_mcp_field_contract.py`.
MCP_FIELD_KEYS = (
    KEY_SERVER,
    KEY_URL,
    KEY_TRANSPORT,
    KEY_AUTH_KIND,
    KEY_AUTH_HEADER_NAME,
    KEY_AUTH_TOKEN_ENV,
    KEY_TOOLS,
    KEY_NOTE,
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

#: `DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT` is **300 s** in the library, so a
#: server that accepts a connection and then says nothing would hang a panel
#: for five minutes and a compile for as long. Every handshake this module
#: makes is wrapped in this.
MCP_TIMEOUT_SECONDS = 15.0

#: A POSIX environment variable name. The field wants a name; this is how we
#: tell a name from the key somebody pasted into it by mistake.
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    return catalogue


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
    if not _ENV_NAME.match(name):
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
    """`(status, message)` — the three panel answers, and only three.

    A **404 page and a plain HTML page give the identical 405**, because both
    are POST-to-a-GET-endpoint failures rather than MCP failures. So "wrong
    path" and "wrong host" are deliberately not distinguished: the wire does
    not carry that difference, and inventing it would produce a message that
    is confidently wrong half the time.
    """
    import httpx

    for cause in flatten_causes(exc):
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

    started = time.monotonic()
    try:
        name, version, tools = asyncio.run(
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


def _discover_tools(
    definition: McpServerDefinition, headers: Mapping[str, str], *, timeout: float
) -> list[Any]:
    """`asyncio.run(get_tools())` — a network call in the compile path.

    Named as its own module-level function for two reasons. It is the seam a
    unit test replaces, so no test in this repository needs a server; and it
    is the *one* place to look when asking what compiling a document can
    reach, which is a question worth being able to answer in one file.

    Measured: 1.08 s for one remote server on 0.3.2. N servers cost roughly
    one server's latency rather than N — `get_tools()` with no `server_name`
    gathers over all connections — but each `tool.mcp` node binds exactly one,
    so that concurrency is not ours to claim.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient({definition.name: definition.connection(headers)})
    return asyncio.run(asyncio.wait_for(client.get_tools(server_name=definition.name), timeout))


def _wrap_async_tool(tool: Any) -> Any:
    """The sync shim: the original `coroutine`, plus a `func` that runs it.

    `response_format` is carried across deliberately. Every MCP tool arrives
    as `content_and_artifact`, so the coroutine returns a `(content,
    artifact)` tuple — a wrapper defaulting to `"content"` would stringify
    that tuple and hand the model its own artifact as text.
    """
    from langchain_core.tools import StructuredTool

    coroutine = tool.coroutine

    def _call(**kwargs: Any) -> Any:
        return asyncio.run(coroutine(**kwargs))

    return StructuredTool(
        name=tool.name,
        description=getattr(tool, "description", "") or "",
        args_schema=tool.args_schema,
        func=_call,
        coroutine=coroutine,
        response_format=getattr(tool, "response_format", "content"),
        metadata=getattr(tool, "metadata", None),
    )


# --------------------------------------------------------------------- #
# The atom
# --------------------------------------------------------------------- #


def _rows(value: Any) -> list[str]:
    """The `repeatable-group` filter, as a list of names.

    Blank rows are not a filter. Somebody pressing *Add tool* and then
    changing their mind must not silently bind nothing.
    """
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


class McpTool(BaseTool):
    """One card, a whole MCP server's tools — filtered, if you like.

    **One node is one server, not one tool.** The alternative was considered
    and rejected in research: a thirty-tool server would be thirty cards, and
    the filter below does the same job in one.

    The singular seam refuses rather than guessing — see `as_langchain_tool`.
    """

    name = "mcp_server"
    description = (
        "Binds every tool an MCP server offers onto this agent. Configured on the canvas, "
        "not called directly."
    )
    node_type = "tool.mcp"
    Args = NoArgs

    def __init__(
        self,
        definition: McpServerDefinition | None = None,
        selected: Sequence[str] = (),
        *,
        data: Mapping[str, Any] | None = None,
        problem: str | None = None,
    ) -> None:
        self.definition = definition
        self.selected = tuple(selected)
        self.problem = problem
        self._data = dict(data or {})

    # -- configuration -------------------------------------------------- #

    def configure(self, data: dict[str, Any]) -> "McpTool":
        """One node's own fields, resolved into a server definition.

        A fresh instance, never a mutation of the shared registry one: two
        `tool.mcp` nodes pointing at two servers in one document is the
        expected case, not the exotic one.
        """
        server_name = str(data.get(KEY_SERVER, "")).strip()
        url = str(data.get(KEY_URL, "")).strip()
        selected = _rows(data.get(KEY_TOOLS))

        if server_name:
            registered = mcp_server_catalogue(_configured_servers()).get(server_name)
            if registered is None:
                return McpTool(
                    None,
                    selected,
                    data=data,
                    problem=(
                        f'No MCP server named "{server_name}" is registered in this project, '
                        f"and this node configures none of its own. Add it to "
                        f"openstategraph.yaml under mcp_servers, or fill in the server's URL "
                        f"on the card."
                    ),
                )
            return McpTool(registered, selected, data=data)

        if not url:
            return McpTool(
                None,
                selected,
                data=data,
                problem=(
                    "An MCP server node names no registered server and carries no URL, so "
                    "there is nothing for it to connect to. Pick a server or type its URL."
                ),
            )

        transport = str(data.get(KEY_TRANSPORT, "")).strip()
        return McpTool(
            McpServerDefinition(
                # An inline server has no registered name; the URL is the only
                # honest identity it has, and every warning below names it.
                name=url,
                url=url,
                # A transport this build does not implement (websocket, stdio)
                # falls back rather than failing: the document may have been
                # written by a newer editor, and HTTP is the only one of the
                # four that both carries a credential and needs no subprocess.
                transport=transport if transport in TRANSPORTS else TRANSPORT_HTTP,
                auth=McpAuth(
                    kind=str(data.get(KEY_AUTH_KIND, AUTH_NONE)).strip() or AUTH_NONE,
                    header_name=str(data.get(KEY_AUTH_HEADER_NAME, "")).strip(),
                    token_env=str(data.get(KEY_AUTH_TOKEN_ENV, "")).strip(),
                ),
                origin="inline",
            ),
            selected,
            data=data,
        )

    def document_state(self) -> dict[str, Any]:
        """Everything this node would serialise. Exists to be tested.

        The map's rule is that `workflow.json` stays shareable — a document
        may name a server, never a credential. A rule with no test is a
        wish, so `test_prebuilt_mcp.py` sets a variable to a recognisable
        secret and asserts it appears nowhere in here.
        """
        return dict(self._data)

    # -- the seam ------------------------------------------------------- #

    def as_langchain_tools(self, warnings: list[str] | None = None) -> list[Any]:
        """Every tool this server offers, filtered, wrapped, never raising.

        A network call in the compile path is what this is, and nothing else
        here is one. So the rule that makes it acceptable is enforced at every
        exit: **a failure contributes a warning and zero tools.** The agent
        then runs without the capability, loudly, instead of the compile dying
        for a server that happened to be down.
        """

        def warn(message: str) -> list[Any]:
            if warnings is not None:
                warnings.append(message)
            else:  # a caller that wants none still gets the log line
                logger.warning(message)
            return []

        if self.problem:
            return warn(self.problem)
        definition = self.definition
        if definition is None:  # pragma: no cover — `problem` is always set with it
            return warn("An MCP server node resolved to no server at all.")

        headers, problem = resolve_auth_headers(definition.auth, server_name=definition.name)
        if problem:
            return warn(problem)

        try:
            discovered = _discover_tools(definition, headers, timeout=MCP_TIMEOUT_SECONDS)
        except BaseException as exc:  # noqa: BLE001 — ExceptionGroup is a BaseException
            status, _panel_message = classify_mcp_failure(exc)
            return warn(_bind_sentence(status, definition))

        available = {tool.name: tool for tool in discovered}
        if not self.selected:
            # G7: an absent filter means "all, now and later". Storing the
            # resolved list would silently freeze the server's surface.
            chosen = list(discovered)
        else:
            chosen = [tool for tool in discovered if tool.name in set(self.selected)]
            missing = [name for name in self.selected if name not in available]
            if missing:
                # The failure that would otherwise be reported as success: a
                # filter naming three tools where the server offers two binds
                # two and looks entirely healthy.
                named = ", ".join(sorted(missing))
                warn(
                    f'MCP server "{definition.name}" has no tool named {named}. '
                    f"Bound {len(chosen)} of the {len(self.selected)} tools this node asks for."
                )

        return [_wrap_async_tool(tool) for tool in chosen]

    def as_langchain_tool(self) -> Any:
        """Refuses, and names the plural seam.

        "Which one of my server's tools am I?" has no true answer, and this
        repository's settled response to a question with no true answer is an
        honest refusal rather than a plausible-looking first element. The
        canvas never takes this path — `NodeRuntime._bind_tools` calls
        `as_langchain_tools` — so the refusal is a guard on the *other*
        callers, not a behaviour anyone should meet.
        """
        return super().as_langchain_tool()

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
    if status == STATUS_AUTH_REQUIRED:
        return (
            f'MCP server "{definition.name}" rejected the credential in '
            f"{definition.auth.token_env or 'its configured variable'}. None of its tools are "
            f"available for this run."
        )
    if status == STATUS_NOT_MCP:
        return (
            f"{definition.url} answered, but it does not speak MCP. Check the URL and the "
            f'transport for server "{definition.name}".'
        )
    return (
        f'MCP server "{definition.name}" could not be reached at {definition.url}. None of '
        f"its tools are available for this run."
    )


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
    "MCP_FIELD_KEYS",
    "MCP_TIMEOUT_SECONDS",
    "MCP_TOOLS",
    "STATUS_AUTH_REQUIRED",
    "STATUS_LIVE",
    "STATUS_NOT_MCP",
    "STATUS_UNREACHABLE",
    "TRANSPORTS",
    "TRANSPORT_HTTP",
    "TRANSPORT_SSE",
    "McpAuth",
    "McpServerDefinition",
    "McpTool",
    "McpValidation",
    "classify_mcp_failure",
    "flatten_causes",
    "mcp_server_catalogue",
    "resolve_auth_headers",
    "validate_mcp_server",
]
