"""Which MCP servers this project knows, and whether one actually answers.

Two routes, and the split is the same one `/api/providers` draws: the first
says what is *registered*, the second makes a real call. They are different
questions, and the gap between them is where the confusing failures live — a
server can be registered, correctly spelled, and down.

Neither route touches `WorkflowServices`. A server registry is a property of
the project's config and the process environment, so these read those
directly rather than gaining a dependency on a workflow being open.

**No credential is ever accepted, returned or logged.** `McpAuthPayload` has
no field a value could travel in; the editor posts a variable *name* and the
handshake below resolves it from this server's own environment. That is the
map's secrets rule expressed as a schema rather than as a convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from openstategraph.api.schemas import (
    McpAuthPayload,
    McpServerResponse,
    McpValidateRequest,
    McpValidateResponse,
)

if TYPE_CHECKING:  # `prebuilt_mcp` imports the adapters lazily; keep it off the
    # import path of a server that never validates a connection.
    from openstategraph.prebuilt_mcp import McpAuth

router = APIRouter()


@router.get(
    "/api/mcp/servers",
    response_model=list[McpServerResponse],
    summary="Which MCP servers this project can bind",
    tags=["Operations"],
)
def mcp_servers() -> list[McpServerResponse]:
    """The two built-in defaults, with the project's own layered over by name.

    Both defaults are public and keyless — the LangChain documentation and the
    LangChain API reference — so a brand-new project has two working servers
    without configuring anything. A project entry sharing a name replaces the
    default it names and leaves the other alone.
    """
    from openstategraph.config_file import ConfigError, config_mcp_servers
    from openstategraph.prebuilt_mcp import mcp_server_catalogue

    try:
        configured = config_mcp_servers()
    except ConfigError as exc:
        # A malformed entry must not take the whole list down: the two
        # defaults are still bindable, and the editor showing them plus this
        # message is strictly better than an empty panel and a 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [
        McpServerResponse(**server.as_payload())
        for server in mcp_server_catalogue(configured).values()
    ]


@router.post(
    "/api/mcp/validate",
    response_model=McpValidateResponse,
    summary="Shake hands with one MCP server, and list what it offers",
    tags=["Operations"],
)
def validate_mcp(request: McpValidateRequest) -> McpValidateResponse:
    """`initialize` + `list_tools`, wrapped in a 15-second ceiling.

    **It never refuses to answer.** Every outcome is a verdict with a status
    the panel can render as a badge — that is the map's decision that
    validation *saves* with a live/unreachable/auth-required badge rather than
    blocking a developer who is mid-typing.

    The ceiling is not caution. `DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT` is
    **300 seconds**, so a server that accepts a connection and then says
    nothing would hold this request open for five minutes.

    Measured against the public docs server: 0.86 s for both round trips.
    """
    from openstategraph.config_file import ConfigError, config_mcp_servers
    from openstategraph.prebuilt_mcp import (
        McpServerDefinition,
        TRANSPORTS,
        mcp_server_catalogue,
        validate_mcp_server,
    )

    name = request.server.strip()
    if name:
        try:
            configured = config_mcp_servers()
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        definition = mcp_server_catalogue(configured).get(name)
        if definition is None:
            # An unknown *name* is a client error, not a verdict: answering it
            # with "unreachable" would send a developer looking at a network
            # they never reached.
            raise HTTPException(
                status_code=404, detail=f'No MCP server named "{name}" is registered.'
            )
    else:
        url = request.url.strip()
        if not url:
            raise HTTPException(
                status_code=400, detail="Name a registered server or give a URL to check."
            )
        transport = request.transport.strip()
        definition = McpServerDefinition(
            name=url,
            url=url,
            transport=transport if transport in TRANSPORTS else TRANSPORTS[0],
            auth=_auth_of(request.auth),
            origin="inline",
        )

    return McpValidateResponse(**validate_mcp_server(definition).as_payload())


def _auth_of(payload: McpAuthPayload) -> "McpAuth":
    from openstategraph.prebuilt_mcp import McpAuth

    return McpAuth(
        kind=payload.kind.strip() or "none",
        header_name=payload.headerName.strip(),
        token_env=payload.tokenEnv.strip(),
    )
